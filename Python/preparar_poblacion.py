"""Extrae los denominadores departamentales del DANE para 2015–2023."""

from __future__ import annotations

import csv
from pathlib import Path

import openpyxl

from Python.centralizar_nacimientos import RAIZ, sha256_archivo


FUENTES = (
    ("DCD-area-proypoblacion-dep-2005-2017_VP.xlsx", range(2015, 2018)),
    ("PPED-AreaDep-2018-2050_VP.xlsx", range(2018, 2024)),
)


def preparar_poblacion(carpeta: Path | None = None, destino: Path | None = None) -> dict:
    carpeta = Path(carpeta or RAIZ / "Poblacion")
    destino = Path(destino or RAIZ / "Data_Processed" / "poblacion_departamental.csv")
    filas = {}
    huellas = {}
    for nombre, periodo in FUENTES:
        ruta = carpeta / nombre
        huellas[nombre] = sha256_archivo(ruta)
        libro = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
        try:
            hoja = libro.worksheets[-1]
            for depto, _, anio, area, poblacion in hoja.values:
                if (isinstance(depto, str) and len(depto) == 2 and depto.isdigit()
                        and anio in periodo and area == "Total"):
                    clave = (int(anio), depto)
                    if clave in filas or not isinstance(poblacion, int) or poblacion <= 0:
                        raise ValueError(f"Denominador ambiguo o inválido: {clave}")
                    filas[clave] = poblacion
        finally:
            libro.close()
    if len(filas) != 9 * 33 or any(sum(1 for y, _ in filas if y == anio) != 33
                                   for anio in range(2015, 2024)):
        raise ValueError("La población no cubre 33 departamentos para cada año de 2015–2023.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(("ANIO", "DEPTO_RES_COD", "POBLACION", "FUENTE"))
        for (anio, depto), poblacion in sorted(filas.items()):
            fuente = FUENTES[0][0] if anio <= 2017 else FUENTES[1][0]
            escritor.writerow((anio, depto, poblacion, fuente))
    return {"filas": len(filas), "sha256": sha256_archivo(destino), "fuentes": huellas}


if __name__ == "__main__":
    print(preparar_poblacion())
