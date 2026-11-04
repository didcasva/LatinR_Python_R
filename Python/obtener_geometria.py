"""Regenera el GeoJSON simplificado desde el servicio oficial MGN 2018 del DANE."""

from __future__ import annotations

import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import urlopen

from Python.centralizar_nacimientos import RAIZ, sha256_archivo
from Python.preparar_nacimientos import leer_divipola


SERVICIO = ("https://portalgis.dane.gov.co/mparcgis/rest/services/"
            "MGN2018/Serv_CapaDepartamentosInt_2018/MapServer/0/query")


def obtener(destino: Path | None = None) -> dict:
    destino = Path(destino or RAIZ / "Municipios" / "departamentos_mgn2018.geojson")
    nombres, _ = leer_divipola(RAIZ / "Municipios" / "DIVIPOLA_Municipios.xlsx")
    rasgos = []
    for codigo, nombre in sorted(nombres.items()):
        parametros = urlencode({"where": f"DPTO_CCDGO='{codigo}'", "outFields": "DPTO_CCDGO",
                              "returnGeometry": "true", "outSR": "4326", "maxAllowableOffset": "0.005",
                              "geometryPrecision": "4", "f": "geojson"})
        ultimo_error = None
        for intento in range(5):
            try:
                with urlopen(f"{SERVICIO}?{parametros}", timeout=45) as respuesta:
                    resultado = json.load(respuesta)
                seleccion = resultado.get("features", [])
                if (len(seleccion) != 1 or not seleccion[0].get("geometry")
                        or seleccion[0]["properties"].get("DPTO_CCDGO") != codigo):
                    raise ValueError(str(resultado.get("error", "geometría ausente")))
                rasgos.append({"type": "Feature", "properties": {"DEPTO_RES_COD": codigo,
                                                                      "DEPTO_RES_NOMBRE": nombre},
                               "geometry": seleccion[0]["geometry"]})
                print(f"Geometría {codigo}: {nombre}", flush=True)
                break
            except (OSError, ValueError) as error:
                ultimo_error = error
                time.sleep(1 + intento)
        else:
            raise RuntimeError(f"No se obtuvo el departamento {codigo}: {ultimo_error}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({"type": "FeatureCollection", "features": rasgos},
                                  ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return {"departamentos": len(rasgos), "bytes": destino.stat().st_size,
            "sha256": sha256_archivo(destino), "fuente": SERVICIO,
            "simplificacion_grados": 0.005, "precision_decimales": 4}


if __name__ == "__main__":
    print(obtener())
