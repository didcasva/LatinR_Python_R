"""Pruebas de conservación de datos y fallos antes de publicar resultados."""

import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pyarrow.parquet as pq

from Python.centralizar_nacimientos import (
    MANIFIESTO, PARQUET, centralizar, descubrir_archivos, inspeccionar_fuente,
    sha256_archivo,
)


BASE = ["ANO", "CODPTORE", "CODMUNRE", "AREA_RES", "EDAD_MADRE"]


class CentralizacionTests(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.raiz = Path(self.temporal.name)
        self.entrada = self.raiz / "Data_Raw" / "Nacimientos"
        self.entrada.mkdir(parents=True)
        self.salida = self.raiz / "Data_Processed"

    def fuente(self, anio, filas, columnas=None, encoding="utf-8"):
        ruta = self.entrada / f"nac{anio}.csv"
        with ruta.open("w", encoding=encoding, newline="") as archivo:
            escritor = csv.writer(archivo)
            escritor.writerow(columnas or BASE)
            escritor.writerows(filas)
        return ruta

    def ejecutar(self, anios=(2015, 2016), filas_por_bloque=1):
        with contextlib.redirect_stdout(io.StringIO()):
            return centralizar(self.entrada, self.salida, anios, filas_por_bloque)

    def test_conserva_ceros_vacios_textos_nulos_y_procedencia(self):
        primera = self.fuente(2015, [
            ["2014", "05", "001", "1", "99", "NA"],
            ["2015", "05", "002", "9", "2", ""],
        ], BASE + ["NOTA"])
        segunda = self.fuente(2016, [
            ["2016", "08", "001", "2", "1", "niña\ncon observación", "001"],
        ], BASE + ["NOTA", "NUEVA"], encoding="latin-1")
        originales = {p.name: sha256_archivo(p) for p in (primera, segunda)}
        resultado = self.ejecutar()
        filas = pq.read_table(self.salida / PARQUET).to_pylist()
        self.assertEqual(resultado["filas"], 3)
        self.assertEqual([f["CODMUNRE"] for f in filas], ["001", "002", "001"])
        self.assertEqual([f["NOTA"] for f in filas], ["NA", "", "niña\ncon observación"])
        self.assertEqual([f["NUEVA"] for f in filas], [None, None, "001"])
        self.assertEqual([f["EDAD_MADRE"] for f in filas], ["99", "2", "1"])
        self.assertEqual([f["ANIO_FUENTE"] for f in filas], [2015, 2015, 2016])
        self.assertEqual([f["ANO"] for f in filas], ["2014", "2015", "2016"])
        self.assertEqual([f["ARCHIVO_FUENTE"] for f in filas], [primera.name, primera.name, segunda.name])
        self.assertEqual(originales, {p.name: sha256_archivo(p) for p in (primera, segunda)})
        manifiesto = json.loads((self.salida / MANIFIESTO).read_text(encoding="utf-8"))
        self.assertEqual(manifiesto["parquet"]["sha256"], sha256_archivo(self.salida / PARQUET))
        self.assertEqual(manifiesto["fuentes"][1]["codificacion"], "latin-1")
        self.assertIn("segundos_totales", manifiesto["recursos"])

    def test_faltantes_y_duplicados_no_se_resuelven_arbitrariamente(self):
        self.fuente(2015, [["2015", "05", "001", "1", "2"]])
        with self.assertRaisesRegex(ValueError, "falta el archivo de 2016"):
            descubrir_archivos(self.entrada, (2015, 2016))
        duplicado = self.entrada / "otro_2015.csv"
        duplicado.write_bytes((self.entrada / "nac2015.csv").read_bytes())
        with self.assertRaisesRegex(ValueError, "varios CSV"):
            descubrir_archivos(self.entrada, (2015,))

    def test_rechaza_registros_cortos_y_largos(self):
        for valores in (["2015", "05"], ["2015", "05", "001", "1", "2", "extra"]):
            with self.subTest(valores=valores):
                ruta = self.fuente(2015, [valores])
                with self.assertRaisesRegex(ValueError, "campos"):
                    inspeccionar_fuente(2015, ruta)

    def test_rechaza_encabezados_ambiguos_y_campos_reservados(self):
        for adicional in (" ANO ", "ANIO_FUENTE", ""):
            with self.subTest(adicional=adicional):
                ruta = self.fuente(2015, [["2015", "05", "001", "1", "2", "x"]], BASE + [adicional])
                with self.assertRaises(ValueError):
                    inspeccionar_fuente(2015, ruta)

    def test_rechaza_nul_para_evitar_truncamiento_silencioso(self):
        ruta = self.fuente(2015, [["2015", "05", "001\x00texto", "1", "2"]])
        with self.assertRaisesRegex(ValueError, "NUL"):
            inspeccionar_fuente(2015, ruta)

    def test_un_fallo_de_escritura_conserva_el_resultado_anterior(self):
        self.fuente(2015, [["2015", "05", "001", "1", "2"]])
        self.salida.mkdir()
        anterior = self.salida / PARQUET
        anterior.write_bytes(b"resultado previo")
        with patch("Python.centralizar_nacimientos.pq.ParquetWriter.write_table", side_effect=OSError("disco lleno")):
            with self.assertRaisesRegex(OSError, "disco lleno"):
                self.ejecutar(anios=(2015,))
        self.assertEqual(anterior.read_bytes(), b"resultado previo")
        self.assertFalse(list(self.salida.glob(".centralizacion-*")))
        self.assertFalse((self.salida / MANIFIESTO).exists())

    def test_no_permite_guardar_sobre_los_originales(self):
        for destino in (self.entrada, self.entrada / "salida", self.raiz):
            with self.subTest(destino=destino), self.assertRaisesRegex(ValueError, "separada"):
                centralizar(self.entrada, destino)

    def test_el_numero_de_bloques_no_cambia_los_datos(self):
        self.fuente(2015, [["2015", "05", "001", "1", "2"], ["2015", "08", "002", "3", "3"]])
        self.ejecutar(anios=(2015,), filas_por_bloque=1)
        primera = pq.read_table(self.salida / PARQUET)
        self.ejecutar(anios=(2015,), filas_por_bloque=10)
        self.assertTrue(primera.equals(pq.read_table(self.salida / PARQUET)))


if __name__ == "__main__":
    unittest.main()
