"""Ejecuta el comando y el notebook desde una copia aislada con nueve fuentes."""

import csv
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


RAIZ = Path(__file__).resolve().parents[1]
NOTEBOOK = "00_Unificar_CSV_2015_2023.ipynb"
TIENE_NOTEBOOK = all(importlib.util.find_spec(nombre) for nombre in ("nbformat", "nbclient", "ipykernel"))


class ReproduccionTests(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.exterior = Path(self.temporal.name)
        self.copia = self.exterior / "repositorio con espacios"
        (self.copia / "Python").mkdir(parents=True)
        (self.copia / "Notebooks").mkdir()
        entrada = self.copia / "Data_Raw" / "Nacimientos"
        entrada.mkdir(parents=True)
        for relativo in ("reproducir.py", "Python/__init__.py", "Python/centralizar_nacimientos.py",
                         f"Notebooks/{NOTEBOOK}"):
            shutil.copyfile(RAIZ / relativo, self.copia / relativo)
        for anio in range(2015, 2024):
            with (entrada / f"nac{anio}.csv").open("w", encoding="utf-8", newline="") as archivo:
                escritor = csv.writer(archivo)
                escritor.writerow(["ANO", "CODPTORE", "CODMUNRE", "AREA_RES", "EDAD_MADRE"])
                escritor.writerow([anio, "05", "001", "1", "2"])

    def test_comando_desde_otra_carpeta_y_sin_git(self):
        proceso = subprocess.run(
            [sys.executable, str(self.copia / "reproducir.py")], cwd=self.exterior,
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proceso.returncode, 0, proceso.stderr)
        manifiesto = self.copia / "Data_Processed" / "centralizacion_manifiesto.json"
        self.assertEqual(json.loads(manifiesto.read_text(encoding="utf-8"))["filas"], 9)

    @unittest.skipUnless(TIENE_NOTEBOOK, "Instalar requirements-notebook.txt para verificar el notebook.")
    def test_notebook_ejecuta_todas_las_celdas_en_una_copia_limpia(self):
        import nbformat
        from nbclient import NotebookClient

        notebook = nbformat.read(self.copia / "Notebooks" / NOTEBOOK, as_version=4)
        nbformat.validate(notebook)
        cliente = NotebookClient(
            notebook, timeout=60, kernel_name="python3",
            resources={"metadata": {"path": str(self.copia / "Notebooks")}},
        )
        ejecutado = cliente.execute()
        errores = [salida for celda in ejecutado.cells if celda.cell_type == "code"
                   for salida in celda.outputs if salida.output_type == "error"]
        self.assertEqual(errores, [])
        manifiesto = self.copia / "Data_Processed" / "centralizacion_manifiesto.json"
        self.assertEqual(json.loads(manifiesto.read_text(encoding="utf-8"))["filas"], 9)


if __name__ == "__main__":
    unittest.main()
