"""Regresiones en códigos cuyo significado depende de la variable."""

import unittest

import pyarrow as pa

from Python.preparar_nacimientos import CAMPOS, transformar


class PreparacionTest(unittest.TestCase):
    def bloque(self, **cambios):
        filas = [
            {"ANO": "2023", "ANIO_FUENTE": 2023, "ARCHIVO_FUENTE": "2023.csv",
             "CODPRES": "170", "CODPTORE": "99", "CODMUNRE": "001", "AREA_RES": "3",
             "EDAD_MADRE": "9", "SEXO": "1"},
            {"ANO": "2023", "ANIO_FUENTE": 2023, "ARCHIVO_FUENTE": "2023.csv",
             "CODPRES": "170", "CODPTORE": "05", "CODMUNRE": "999", "AREA_RES": "9",
             "EDAD_MADRE": "99", "SEXO": "2"},
        ]
        for indice, cambios_fila in cambios.items():
            filas[int(indice)].update(cambios_fila)
        return pa.RecordBatch.from_pydict({campo: [fila[campo] for fila in filas] for campo in CAMPOS})

    def test_vichada_99_es_departamento_y_edad_9_es_valida(self):
        datos = transformar(self.bloque(), {"99": "Vichada", "05": "Antioquia"},
                            {"99001", "05001"})
        self.assertEqual(datos.loc[0, "DEPTO_RES_COD"], "99")
        self.assertEqual(datos.loc[0, "EDAD_MADRE_GRUPO"], "50–54")
        self.assertEqual(datos.loc[0, "DIVIPOLA_2025"], "Coincide con DIVIPOLA 2025")
        self.assertEqual(datos.loc[1, "EDAD_MADRE_GRUPO"], "Sin información")
        self.assertEqual(datos.loc[1, "AREA_RES_GRUPO"], "Sin información")
        self.assertEqual(datos.loc[1, "DIVIPOLA_2025"], "No coincide con DIVIPOLA 2025")
        self.assertEqual(len(datos), 2)

    def test_anio_y_codigo_desconocido_detienen_preparacion(self):
        with self.assertRaisesRegex(ValueError, "año del hecho"):
            transformar(self.bloque(**{"0": {"ANO": "2022"}}), {"99": "Vichada"}, {"99001"})
        with self.assertRaisesRegex(ValueError, "EDAD_MADRE"):
            transformar(self.bloque(**{"0": {"EDAD_MADRE": "10"}}),
                        {"99": "Vichada"}, {"99001"})


if __name__ == "__main__":
    unittest.main()
