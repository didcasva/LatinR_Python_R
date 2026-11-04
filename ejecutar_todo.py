"""Reconstruye centralización, análisis R e informe HTML/PDF desde la raíz del proyecto."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


RAIZ = Path(__file__).resolve().parent


def ejecutar(etiqueta: str, comando: list[str], entorno: dict[str, str]) -> None:
    print(f"\n[{etiqueta}] {' '.join(comando)}", flush=True)
    subprocess.run(comando, cwd=RAIZ, env=entorno, check=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Reconstruye todas las etapas de natalidad 2015–2023.")
    parser.add_argument("--omitir-centralizacion", action="store_true",
                        help="Reutiliza el Parquet de la etapa 0 ya generado.")
    args = parser.parse_args(argv)
    rscript = shutil.which("Rscript")
    quarto = shutil.which("quarto")
    if not rscript or not quarto:
        print("Se requieren Rscript y Quarto en PATH. Consulta README.MD.", file=sys.stderr)
        return 2
    entorno = os.environ.copy()
    if os.name == "nt":
        entorno["LC_ALL"] = "English_United States.utf8"
    try:
        if not args.omitir_centralizacion:
            ejecutar("0 Centralización", [sys.executable, str(RAIZ / "reproducir.py")], entorno)
        elif not (RAIZ / "Data_Processed" / "nacimientos_consolidados.parquet").exists():
            raise FileNotFoundError("Falta Data_Processed/nacimientos_consolidados.parquet")
        ejecutar("1 Preparación", [sys.executable, "-m", "Python.preparar_nacimientos"], entorno)
        ejecutar("1 Población", [sys.executable, "-m", "Python.preparar_poblacion"], entorno)
        ejecutar("2 Dependencias R", [rscript, "-e", "renv::restore(prompt=FALSE)"], entorno)
        ejecutar("2 Análisis R", [rscript, "R/analizar_natalidad.R"], entorno)
        for formato in ("html", "typst"):
            ejecutar(f"3 Informe {formato}",
                    [quarto, "render", "Reports/reporte_natalidad.qmd", "--to", formato], entorno)
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("\nListo: Reports/reporte_natalidad.html y Reports/reporte_natalidad.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
