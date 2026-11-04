"""Etapa 1: variables de análisis y auditoría de residencia, sin descartar filas."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import openpyxl
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from Python.centralizar_nacimientos import RAIZ, sha256_archivo


CAMPOS = ("ANO", "ANIO_FUENTE", "ARCHIVO_FUENTE", "CODPRES", "CODPTORE",
          "CODMUNRE", "AREA_RES", "EDAD_MADRE", "SEXO")
EDADES = {str(i): f"{10 + 5 * (i - 1)}–{14 + 5 * (i - 1)}" for i in range(1, 10)}
AREAS = {"1": "Cabecera municipal", "2": "Centro poblado", "3": "Rural disperso"}
# El XLSX distribuido en este proyecto contiene caracteres de reemplazo en
# algunos nombres. Estas correcciones son únicamente de presentación.
NOMBRES = {
    "08": "Atlántico", "11": "Bogotá, D.C.", "13": "Bolívar", "15": "Boyacá",
    "18": "Caquetá", "23": "Córdoba", "27": "Chocó", "52": "Nariño",
    "63": "Quindío", "88": "Archipiélago de San Andrés, Providencia y Santa Catalina",
    "94": "Guainía", "97": "Vaupés", "44": "La Guajira",
    "54": "Norte de Santander", "76": "Valle del Cauca",
}
DERIVADAS = ("ANIO", "RESIDE_COLOMBIA", "DEPTO_RES_COD", "DEPTO_RES_NOMBRE",
             "MUNIC_RES_COD", "DIVIPOLA_2025", "AREA_RES_GRUPO", "EDAD_MADRE_GRUPO")


def leer_divipola(ruta: Path) -> tuple[dict[str, str], set[str]]:
    libro = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    try:
        hoja = libro["Municipios"]
        departamentos: dict[str, str] = {}
        municipios: set[str] = set()
        for fila in hoja.iter_rows(min_row=12, values_only=True):
            depto, nombre, municipio = fila[:3]
            if not (isinstance(depto, str) and re.fullmatch(r"\d{2}", depto)
                    and isinstance(municipio, str) and re.fullmatch(r"\d{5}", municipio)):
                continue
            if municipio[:2] != depto:
                raise ValueError(f"DIVIPOLA inconsistente: {depto} y {municipio}")
            departamentos[depto] = NOMBRES.get(depto, str(nombre).title())
            municipios.add(municipio)
        if len(departamentos) != 33 or len(municipios) < 1100:
            raise ValueError("El catálogo DIVIPOLA no contiene los departamentos y municipios esperados.")
        return departamentos, municipios
    finally:
        libro.close()


def transformar(bloque: pa.RecordBatch, departamentos: dict[str, str],
                municipios: set[str]) -> pd.DataFrame:
    datos = bloque.to_pandas()
    anio = pd.to_numeric(datos["ANO"], errors="coerce")
    if not anio.eq(datos["ANIO_FUENTE"]).all():
        raise ValueError("Hay registros cuyo año del hecho difiere del año del archivo.")
    for campo, permitidos in (("EDAD_MADRE", set(EDADES) | {"99", ""}),
                              ("AREA_RES", set(AREAS) | {"9", ""})):
        invalidos = datos[campo].dropna().loc[lambda x: ~x.isin(permitidos)].unique()
        if len(invalidos):
            raise ValueError(f"Códigos inesperados en {campo}: {invalidos[:10].tolist()}")
    pais = datos["CODPRES"].eq("170").fillna(False)
    depto = datos["CODPTORE"].where(pais & datos["CODPTORE"].isin(departamentos))
    codigo_municipio = datos["CODPTORE"].fillna("") + datos["CODMUNRE"].fillna("")
    codigo_municipio = codigo_municipio.where(depto.notna() & codigo_municipio.str.fullmatch(r"\d{5}"))
    coincide = codigo_municipio.isin(municipios)
    estado = pd.Series("No coincide con DIVIPOLA 2025", index=datos.index)
    estado.loc[~pais] = "Residencia exterior o sin país informado"
    estado.loc[pais & depto.isna()] = "Departamento sin código DIVIPOLA 2025"
    estado.loc[pais & depto.notna() & codigo_municipio.isna()] = "Municipio ausente o inválido"
    estado.loc[pais & coincide] = "Coincide con DIVIPOLA 2025"
    datos["ANIO"] = anio.astype("Int16")
    datos["RESIDE_COLOMBIA"] = pais.astype(bool)
    datos["DEPTO_RES_COD"] = depto
    datos["DEPTO_RES_NOMBRE"] = depto.map(departamentos)
    datos["MUNIC_RES_COD"] = codigo_municipio
    datos["DIVIPOLA_2025"] = estado
    datos["AREA_RES_GRUPO"] = datos["AREA_RES"].map(AREAS).fillna("Sin información")
    datos["EDAD_MADRE_GRUPO"] = datos["EDAD_MADRE"].map(EDADES).fillna("Sin información")
    return datos[list(CAMPOS) + list(DERIVADAS)]


def preparar(entrada: Path | None = None, divipola: Path | None = None,
            salida: Path | None = None, filas_por_bloque: int = 50_000) -> dict:
    entrada = Path(entrada or RAIZ / "Data_Processed" / "nacimientos_consolidados.parquet").resolve()
    divipola = Path(divipola or RAIZ / "Municipios" / "DIVIPOLA_Municipios.xlsx").resolve()
    salida = Path(salida or RAIZ / "Data_Processed").resolve()
    if filas_por_bloque <= 0:
        raise ValueError("El tamaño de bloque debe ser mayor que cero.")
    if not entrada.is_file() or not divipola.is_file():
        raise ValueError("Falta el Parquet centralizado o el catálogo DIVIPOLA.")
    if salida == entrada.parent and (salida / "nacimientos_preparados.parquet") == entrada:
        raise ValueError("La salida no puede sobrescribir la entrada.")
    departamentos, municipios = leer_divipola(divipola)
    fuente = pq.ParquetFile(entrada)
    faltan = set(CAMPOS) - set(fuente.schema_arrow.names)
    if faltan:
        raise ValueError(f"Faltan columnas en el Parquet centralizado: {sorted(faltan)}")
    salida.mkdir(parents=True, exist_ok=True)
    auditoria = defaultdict(Counter)
    anios_fuente = Counter()
    anios_hecho = Counter()
    with tempfile.TemporaryDirectory(prefix=".preparacion-", dir=salida) as temporal:
        carpeta = Path(temporal)
        destino = carpeta / "nacimientos_preparados.parquet"
        escritor = None
        try:
            for bloque in fuente.iter_batches(batch_size=filas_por_bloque, columns=list(CAMPOS)):
                datos = transformar(bloque, departamentos, municipios)
                tabla = pa.Table.from_pandas(datos, preserve_index=False)
                if escritor is None:
                    escritor = pq.ParquetWriter(destino, tabla.schema, compression="zstd")
                escritor.write_table(tabla, row_group_size=filas_por_bloque)
                for anio, grupo in datos.groupby("ANIO_FUENTE", dropna=False):
                    anios_fuente[int(anio)] += len(grupo)
                    for campo in ("DIVIPOLA_2025", "AREA_RES_GRUPO", "EDAD_MADRE_GRUPO"):
                        auditoria[(int(anio), campo)].update(grupo[campo].value_counts(dropna=False).to_dict())
                    auditoria[(int(anio), "RESIDE_COLOMBIA")].update(grupo["RESIDE_COLOMBIA"].value_counts().to_dict())
                anios_hecho.update(datos["ANIO"].value_counts(dropna=False).to_dict())
        finally:
            if escritor is not None:
                escritor.close()
        if escritor is None or pq.ParquetFile(destino).metadata.num_rows != fuente.metadata.num_rows:
            raise ValueError("No coincide el número de registros preparados y centralizados.")
        manifiesto = {
            "etapa": "1_preparacion_nacimientos", "fecha_utc": datetime.now(timezone.utc).isoformat(),
            "filas": fuente.metadata.num_rows, "filas_por_anio_fuente": dict(sorted(anios_fuente.items())),
            "anios_hecho": {str(k): v for k, v in anios_hecho.items()},
            "catalogo": {"archivo": str(divipola.relative_to(RAIZ)) if divipola.is_relative_to(RAIZ) else str(divipola),
                         "version": "diciembre 2025", "sha256": sha256_archivo(divipola),
                         "departamentos": len(departamentos), "codigos_municipales": len(municipios)},
            "entrada": {"archivo": str(entrada.relative_to(RAIZ)) if entrada.is_relative_to(RAIZ)
                        else str(entrada), "sha256": sha256_archivo(entrada)},
            "salida": {"archivo": destino.name, "sha256": sha256_archivo(destino)},
            "politica": "Todos los registros se conservan; los códigos de 2015–2023 se comparan con DIVIPOLA de diciembre 2025.",
            "auditoria": {f"{anio}|{campo}": {str(k): int(v) for k, v in conteo.items()}
                           for (anio, campo), conteo in sorted(auditoria.items())},
        }
        (carpeta / "preparacion_manifiesto.json").write_text(
            json.dumps(manifiesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(destino, salida / destino.name)
        os.replace(carpeta / "preparacion_manifiesto.json", salida / "preparacion_manifiesto.json")
    return manifiesto


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Etapa 1: preparar y auditar nacimientos.")
    parser.add_argument("--entrada", type=Path)
    parser.add_argument("--divipola", type=Path)
    parser.add_argument("--salida", type=Path)
    parser.add_argument("--filas-por-bloque", type=int, default=50_000)
    args = parser.parse_args(argv)
    try:
        resultado = preparar(args.entrada, args.divipola, args.salida, args.filas_por_bloque)
    except (ValueError, OSError, pa.ArrowException) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Preparados {resultado['filas']:,} registros. Auditoría en Data_Processed/preparacion_manifiesto.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
