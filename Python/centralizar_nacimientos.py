"""Centraliza los CSV de nacimientos sin aplicar limpieza estadística.

Los campos originales se conservan como texto. Las columnas que no existían
en un año se representan con null; un campo vacío original sigue siendo "".
La escritura por bloques limita la memoria y conserva el orden de los registros.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
import threading
import time

import pandas as pd
import psutil
import pyarrow as pa
import pyarrow.parquet as pq


RAIZ = Path(__file__).resolve().parents[1]
ANIOS = tuple(range(2015, 2024))
TRAZABILIDAD = ("ANIO_FUENTE", "ARCHIVO_FUENTE")
OBLIGATORIAS = {"ANO", "CODPTORE", "CODMUNRE", "AREA_RES", "EDAD_MADRE"}
PARQUET = "nacimientos_consolidados.parquet"
RESUMEN = "centralizacion_archivos.csv"
PRESENCIA = "centralizacion_columnas.csv"
MANIFIESTO = "centralizacion_manifiesto.json"


@dataclass(frozen=True)
class Fuente:
    anio: int
    ruta: Path
    codificacion: str
    columnas_originales: tuple[str, ...]
    columnas: tuple[str, ...]
    filas: int
    lineas_vacias: int
    bytes: int
    sha256: str


def sha256_archivo(ruta: Path) -> str:
    with ruta.open("rb") as archivo:
        return hashlib.file_digest(archivo, "sha256").hexdigest()


def descubrir_archivos(entrada: Path, anios=ANIOS) -> dict[int, Path]:
    """Exige exactamente un CSV por año; nunca elige uno arbitrariamente."""
    entrada = Path(entrada)
    anios = tuple(anios)
    if not anios or len(set(anios)) != len(anios):
        raise ValueError("Se requiere una lista no vacía de años distintos.")
    if not entrada.is_dir():
        raise ValueError(f"No existe la carpeta de nacimientos: {entrada}")
    encontrados = {anio: [] for anio in anios}
    for ruta in sorted(entrada.iterdir(), key=lambda ruta: ruta.name):
        if not ruta.is_file() or ruta.suffix.lower() != ".csv":
            continue
        coincidencias = re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", ruta.stem)
        if len(coincidencias) != 1:
            raise ValueError(f"El CSV debe identificar un único año: {ruta.name}")
        anio = int(coincidencias[0])
        if anio not in encontrados:
            raise ValueError(f"CSV fuera del período solicitado: {ruta.name}")
        encontrados[anio].append(ruta)
    problemas = []
    for anio, rutas in encontrados.items():
        if not rutas:
            problemas.append(f"falta el archivo de {anio}")
        elif len(rutas) > 1:
            problemas.append(f"hay varios CSV para {anio}: {', '.join(p.name for p in rutas)}")
    if problemas:
        raise ValueError("Inventario incompleto o ambiguo: " + "; ".join(problemas))
    return {anio: encontrados[anio][0] for anio in sorted(anios)}


def inspeccionar_fuente(anio: int, ruta: Path) -> Fuente:
    """Valida CSV, cuenta registros lógicos y registra la huella del original."""
    estado = ruta.stat()
    huella = sha256_archivo(ruta)
    # UTF-8 se comprueba sobre el archivo completo. Latin-1 es un respaldo
    # explícito para estas fuentes, no una detección universal de codificaciones.
    for codificacion in ("utf-8-sig", "latin-1"):
        try:
            with ruta.open(encoding=codificacion, errors="strict") as archivo:
                while bloque := archivo.read(1024 * 1024):
                    if "\x00" in bloque:
                        raise ValueError(f"CSV inválido {ruta.name}: contiene bytes NUL.")
            break
        except UnicodeDecodeError:
            continue
    with ruta.open(encoding=codificacion, newline="") as archivo:
        lector = csv.reader(archivo, strict=True)
        try:
            originales = tuple(next(lector))
            columnas = tuple(nombre.strip() for nombre in originales)
            if not columnas or any(not nombre for nombre in columnas):
                raise ValueError("encabezado vacío o con nombres vacíos")
            if len(set(columnas)) != len(columnas):
                raise ValueError("nombres de columnas repetidos después de retirar espacios")
            reservadas = set(columnas).intersection(TRAZABILIDAD)
            if reservadas:
                raise ValueError(f"columnas reservadas: {sorted(reservadas)}")
            faltantes = OBLIGATORIAS.difference(columnas)
            if faltantes:
                raise ValueError(f"faltan columnas de nacimientos: {sorted(faltantes)}")
            filas = vacias = 0
            for registro in lector:
                if not registro:
                    vacias += 1
                    continue
                if len(registro) != len(columnas):
                    raise ValueError(
                        f"registro terminado en línea {lector.line_num}: "
                        f"{len(registro)} campos, se esperaban {len(columnas)}"
                    )
                filas += 1
            if not filas:
                raise ValueError("el archivo no contiene registros")
        except (csv.Error, StopIteration, ValueError) as error:
            raise ValueError(f"CSV inválido {ruta.name}: {error}") from error
    final = ruta.stat()
    if (estado.st_size, estado.st_mtime_ns) != (final.st_size, final.st_mtime_ns):
        raise ValueError(f"El original cambió durante la inspección: {ruta.name}")
    return Fuente(anio, ruta, codificacion, originales, columnas, filas, vacias, estado.st_size, huella)


def columnas_unificadas(fuentes: list[Fuente]) -> list[str]:
    return list(dict.fromkeys(columna for fuente in fuentes for columna in fuente.columnas))


@contextmanager
def observar_recursos():
    """Muestrea RSS del proceso cada 0,1 s; no es una comparación de lenguajes."""
    proceso = psutil.Process()
    medicion = {"memoria_rss_max_observada_bytes": proceso.memory_info().rss}
    detener = threading.Event()

    def muestrear():
        while not detener.wait(0.1):
            medicion["memoria_rss_max_observada_bytes"] = max(
                medicion["memoria_rss_max_observada_bytes"], proceso.memory_info().rss
            )

    inicio = time.perf_counter()
    hilo = threading.Thread(target=muestrear, daemon=True)
    hilo.start()
    try:
        yield medicion
    finally:
        detener.set()
        hilo.join()
        medicion["segundos_totales"] = round(time.perf_counter() - inicio, 3)
        medicion["intervalo_muestreo_rss_segundos"] = 0.1


def validar_parquet(ruta: Path, fuentes: list[Fuente], esquema: pa.Schema) -> int:
    """Comprueba esquema, conteos y procedencia leyendo bloques del Parquet."""
    conteos = Counter()
    with pq.ParquetFile(ruta) as archivo:
        if not archivo.schema_arrow.equals(esquema, check_metadata=False):
            raise ValueError("El esquema del Parquet difiere del esperado.")
        for bloque in archivo.iter_batches(batch_size=50_000, columns=list(TRAZABILIDAD)):
            datos = bloque.to_pydict()
            conteos.update(zip(datos[TRAZABILIDAD[0]], datos[TRAZABILIDAD[1]]))
        esperados = Counter({(f.anio, f.ruta.name): f.filas for f in fuentes})
        if conteos != esperados or archivo.metadata.num_rows != sum(esperados.values()):
            raise ValueError("No coinciden los registros originales y los registros del Parquet.")
    return sum(conteos.values())


def _escribir_reportes(carpeta: Path, fuentes: list[Fuente], columnas: list[str]):
    with (carpeta / RESUMEN).open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(["ANIO_FUENTE", "ARCHIVO_FUENTE", "FILAS_ORIGINALES", "FILAS_PARQUET",
                           "COLUMNAS_ORIGINALES", "COLUMNAS_AUSENTES", "CODIFICACION", "BYTES", "SHA256"])
        for fuente in fuentes:
            ausentes = [c for c in columnas if c not in fuente.columnas]
            escritor.writerow([fuente.anio, fuente.ruta.name, fuente.filas, fuente.filas,
                               len(fuente.columnas), " | ".join(ausentes), fuente.codificacion,
                               fuente.bytes, fuente.sha256])
    with (carpeta / PRESENCIA).open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(["COLUMNA"] + [fuente.anio for fuente in fuentes])
        for columna in columnas:
            escritor.writerow([columna] + ["SI" if columna in f.columnas else "NO" for f in fuentes])


def centralizar(entrada: Path | None = None, salida: Path | None = None,
                anios=ANIOS, filas_por_bloque: int = 50_000) -> dict:
    entrada = Path(entrada or RAIZ / "Data_Raw" / "Nacimientos").resolve()
    salida = Path(salida or RAIZ / "Data_Processed").resolve()
    if filas_por_bloque <= 0:
        raise ValueError("El tamaño de bloque debe ser mayor que cero.")
    if (entrada == salida or salida.is_relative_to(entrada)
            or entrada.is_relative_to(salida) or salida.is_relative_to(RAIZ / "Data_Raw")):
        raise ValueError("La salida debe estar separada de los datos originales.")
    archivos = descubrir_archivos(entrada, anios)
    salida.mkdir(parents=True, exist_ok=True)
    # Sólo se reemplazan los productos definitivos después de validar todo.
    with tempfile.TemporaryDirectory(prefix=".centralizacion-", dir=salida) as temporal:
        trabajo = Path(temporal)
        with observar_recursos() as recursos:
            fuentes = []
            for anio, ruta in archivos.items():
                fuente = inspeccionar_fuente(anio, ruta)
                fuentes.append(fuente)
                print(f"Inspección {anio}: {fuente.filas:,} registros, {len(fuente.columnas)} columnas", flush=True)
            columnas = columnas_unificadas(fuentes)
            esquema = pa.schema([(c, pa.string()) for c in columnas]
                                + [(TRAZABILIDAD[0], pa.int16()), (TRAZABILIDAD[1], pa.string())])
            parquet = trabajo / PARQUET
            with pq.ParquetWriter(parquet, esquema, compression="zstd") as escritor:
                for fuente in fuentes:
                    escritas = 0
                    with pd.read_csv(
                        fuente.ruta, encoding=fuente.codificacion, dtype=str,
                        keep_default_na=False, na_filter=False, chunksize=filas_por_bloque,
                        on_bad_lines="error", index_col=False,
                    ) as lector:
                        for bloque in lector:
                            bloque.columns = fuente.columnas
                            arrays = [pa.array(bloque[c], type=pa.string()) if c in bloque
                                      else pa.nulls(len(bloque), type=pa.string()) for c in columnas]
                            arrays += [pa.array([fuente.anio] * len(bloque), type=pa.int16()),
                                       pa.array([fuente.ruta.name] * len(bloque), type=pa.string())]
                            tabla = pa.Table.from_arrays(arrays, schema=esquema)
                            escritor.write_table(tabla, row_group_size=filas_por_bloque)
                            escritas += len(bloque)
                    if escritas != fuente.filas:
                        raise ValueError(f"Difiere el conteo de CSV y pandas en {fuente.ruta.name}.")
                    print(f"Centralizado {fuente.anio}: {escritas:,} registros", flush=True)
            filas = validar_parquet(parquet, fuentes, esquema)
            for fuente in fuentes:
                if sha256_archivo(fuente.ruta) != fuente.sha256:
                    raise ValueError(f"El original cambió durante la ejecución: {fuente.ruta.name}")
            _escribir_reportes(trabajo, fuentes, columnas)
            manifiesto = {
                "etapa": "0_centralizacion_nacimientos", "version_formato": 1,
                "implementacion": {"archivo": "Python/centralizar_nacimientos.py",
                                   "sha256": sha256_archivo(Path(__file__))},
                "fecha_utc": datetime.now(timezone.utc).isoformat(),
                "anios": [f.anio for f in fuentes], "filas": filas,
                "columnas_originales": columnas, "columnas_trazabilidad": list(TRAZABILIDAD),
                "filas_por_bloque": filas_por_bloque,
                "politica": {"campos_originales": "texto sin recodificar",
                             "campo_vacio_original": "cadena vacia",
                             "columna_ausente_en_un_anio": "null",
                             "codificacion": "UTF-8 validado; respaldo Latin-1",
                             "orden": "anio fuente ascendente y orden original de registros"},
                "fuentes": [dict(anio=f.anio, archivo=f.ruta.name, filas=f.filas,
                                 columnas_originales=list(f.columnas_originales),
                                 columnas_normalizadas=list(f.columnas), codificacion=f.codificacion,
                                 bytes=f.bytes, sha256=f.sha256, lineas_vacias_omitidas=f.lineas_vacias)
                            for f in fuentes],
                "parquet": {"archivo": PARQUET, "bytes": parquet.stat().st_size,
                            "sha256": sha256_archivo(parquet), "compresion": "zstd"},
                "entorno": {"python": platform.python_version(), "sistema": platform.system(),
                            **{p: importlib.metadata.version(p) for p in ("pandas", "pyarrow", "psutil")}},
                "validaciones": {"conteo_independiente_csv": True, "conteos_parquet_por_fuente": True,
                                 "esquema_parquet": True, "originales_sin_cambios": True},
            }
        # El contexto ya completó las métricas. El manifiesto se publica al final
        # y contiene la huella del Parquet para detectar una publicación interrumpida.
        manifiesto["recursos"] = recursos
        (trabajo / MANIFIESTO).write_text(
            json.dumps(manifiesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for nombre in (PARQUET, RESUMEN, PRESENCIA, MANIFIESTO):
            os.replace(trabajo / nombre, salida / nombre)
    return manifiesto


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Etapa 0: centralización reproducible de nacimientos 2015–2023.")
    parser.add_argument("--entrada", type=Path, default=RAIZ / "Data_Raw" / "Nacimientos")
    parser.add_argument("--salida", type=Path, default=RAIZ / "Data_Processed")
    parser.add_argument("--filas-por-bloque", type=int, default=50_000,
                        help="Registros leídos por bloque; reducir para usar menos memoria.")
    args = parser.parse_args(argv)
    try:
        resultado = centralizar(args.entrada, args.salida, filas_por_bloque=args.filas_por_bloque)
    except (ValueError, OSError, pd.errors.ParserError, pa.ArrowException) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Verificados {resultado['filas']:,} registros de {len(resultado['fuentes'])} archivos.")
    print(f"Parquet: {args.salida.resolve() / PARQUET}")
    print(f"Manifiesto: {args.salida.resolve() / MANIFIESTO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
