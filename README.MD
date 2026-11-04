# Natalidad en Colombia con Python y R

Material reproducible para la charla **Python limpia, R analiza: un flujo reproducible
para el análisis de datos abiertos de natalidad en Colombia**, LatinR 2026. El
alcance aprobado comprende nacimientos registrados entre 2015 y 2023,
tendencias departamentales, edad de la madre y área de residencia. Las carpetas
de defunciones y fetales se conservan, pero no entran en este análisis.

## Reconstruir desde un clon

Se probaron **Python 3.12**, **R 4.6.2** y **Quarto 1.11.9** en Windows de 64 bits.
Rscript y Quarto deben estar en `PATH`. Las dependencias de Python y R están
fijadas en `requirements.txt` y `renv.lock`. Instalarlas por primera vez requiere
Internet. Los nueve CSV, los dos XLSX poblacionales y el GeoJSON están incluidos
en el repositorio. La ejecución posterior no descarga datos.

```text
git clone https://github.com/didcasva/LatinR_Python_R.git
cd LatinR_Python_R
```

En **Windows PowerShell**:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe ejecutar_todo.py
```

En **Linux o macOS**:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python ejecutar_todo.py
```

El comando ejecuta las etapas en orden, restaura los paquetes R de `renv.lock`
y produce `Reports/reporte_natalidad.html` y `Reports/reporte_natalidad.pdf`.
Los productos generados se excluyen de Git y se reconstruyen localmente. La
primera ejecución puede tardar varios minutos. En Windows no hace falta activar
el entorno virtual ni cambiar la política de PowerShell. Si `Rscript` o `quarto`
no se encuentran, agrega sus carpetas `bin` al `PATH` de la sesión.

Para repetir sólo las etapas posteriores a la centralización:

```text
python ejecutar_todo.py --omitir-centralizacion
```

Para ejecutar exclusivamente la etapa 0, se mantiene el comando original:

```text
python reproducir.py
```

## Etapas y productos

| Etapa | Implementación | Producto principal |
| --- | --- | --- |
| 0. Centralización | `Python/centralizar_nacimientos.py` | `Data_Processed/nacimientos_consolidados.parquet` y manifiesto |
| 1. Preparación | `Python/preparar_nacimientos.py`, `Python/preparar_poblacion.py` | Parquet preparado, auditoría y población departamental |
| 2. Análisis | `R/analizar_natalidad.R` | Cinco tablas CSV y cuatro figuras PNG en `Reports/output/` |
| 3. Informe | `Reports/reporte_natalidad.qmd` | HTML y PDF con Quarto |

La etapa 0 exige exactamente un CSV por año y verifica encabezados, filas,
esquema, procedencia y SHA-256. Guarda **todos los campos originales como texto**;
los vacíos originales siguen siendo `""` y las columnas inexistentes en un año
son `null`. Añade `ANIO_FUENTE` y `ARCHIVO_FUENTE`. Trabaja por bloques para
limitar el uso de memoria. El notebook `Notebooks/00_Unificar_CSV_2015_2023.ipynb`
explica y llama a la misma implementación. Sus dependencias opcionales están en
`requirements-notebook.txt`.

La etapa 1 conserva los 5.592.489 registros. Deriva grupos de edad y área,
indicador de residencia en Colombia y códigos de departamento y municipio.
Compara los municipios con `Municipios/DIVIPOLA_Municipios.xlsx`, cuya versión
es de **diciembre de 2025**. Las faltas de coincidencia quedan identificadas,
sin descartar registros de años anteriores. Algunos nombres en el XLSX tienen
caracteres dañados; el script corrige únicamente las etiquetas departamentales
afectadas para la presentación. El manifiesto de preparación guarda los
conteos por año, categoría y estado DIVIPOLA, además de huellas SHA-256.

La etapa 2 usa Arrow en R para agregar el Parquet antes de traer las tablas
pequeñas a memoria. Incluye conteos y tasas por año y departamento, distribución
de edad materna, área de residencia y auditoría DIVIPOLA. Los mapas comparan
2015 y 2023 con una escala común. R guarda las tablas y las figuras que Quarto
presenta en la etapa 3. `renv.lock` fija las versiones de los paquetes R.

## Definición de la tasa

El numerador es el número de nacimientos en los CSV cuyo `ANO` está entre 2015
y 2023, la madre reside en Colombia (`CODPRES = 170`) y tiene un departamento
de **residencia habitual** reconocido (`CODPTORE`). El denominador es la
población total proyectada de ese mismo departamento y año. La tasa se expresa
por 1.000 habitantes. La tasa nacional suma numeradores y denominadores de los
33 departamentos. Se incluyen los registros cuyo municipio no coincide con
DIVIPOLA 2025 siempre que el departamento sea conocido.

Es una **tasa bruta descriptiva de los microdatos incluidos**, no una tasa
global de fecundidad ni una cifra oficial ajustada. Los porcentajes de edad
materna y área usan el total anual de ese mismo conjunto; `Sin información`
permanece en el denominador. Los códigos `9` y `99` se interpretan por variable,
no como valores faltantes universales.

## Fuentes y trazabilidad

- Los nueve CSV de `Data_Raw/Nacimientos` y `Diccionario/diccionario_datos.csv`
  son las fuentes de nacimientos del proyecto. El documento
  `ddi-documentation-spanish-876.pdf` contiene metadatos adicionales.
- Los XLSX de `Poblacion/` provienen de las
  [proyecciones departamentales del DANE](https://www.dane.gov.co/index.php/estadisticas-por-tema/demografia-y-poblacion/proyecciones-de-poblacion).
  `DCD-area-proypoblacion-dep-2005-2017_VP.xlsx` cubre 2015–2017 y
  `PPED-AreaDep-2018-2050_VP.xlsx` cubre 2018–2023.
- `Municipios/departamentos_mgn2018.geojson` contiene los 33 departamentos del
  [MGN 2018 del DANE](https://geoportal.dane.gov.co/mparcgis/rest/services/MGN2018/Serv_CapaDepartamentosInt_2018/MapServer/0).
  Se obtuvo con `Python/obtener_geometria.py` y se simplificó a 0,005 grados
  para los mapas. El archivo queda en Git. Regenerarlo requiere acceso al
  servicio DANE y puede cambiar si éste se actualiza.
- [DANE sobre nacimientos y registros tardíos](https://www.dane.gov.co/index.php/estadisticas-por-tema/salud/nacimientos-y-defunciones/nacimientos).

Las huellas de los originales y del Parquet centralizado están en
`Data_Processed/centralizacion_manifiesto.json`. Las huellas del catálogo
DIVIPOLA y del Parquet preparado están en
`Data_Processed/preparacion_manifiesto.json`.

## Estructura relevante

```text
Data_Raw/Nacimientos/       CSV originales 2015–2023
Data_Processed/             Datos y auditorías generados, ignorados por Git
Diccionario/                Variables de nacimientos
Municipios/                 DIVIPOLA y GeoJSON departamental
Poblacion/                  Proyecciones oficiales del DANE
Python/                     Centralización y preparación
R/                          Análisis y visualizaciones
Reports/                    Quarto y sus resultados generados
Notebooks/                  Cuaderno de la etapa 0
tests/                      Comprobaciones con datos pequeños
ejecutar_todo.py            Comando para el flujo completo
reproducir.py               Comando existente para la etapa 0
```

Las pruebas de Python se ejecutan con `python -m unittest discover -s tests -v`.
También se comprueba que los agregados R sumen el mismo total por año,
departamento, edad, área y estado DIVIPOLA. HTML y PDF se renderizan en cada
ejecución completa. Las versiones de Python se actualizan deliberadamente con
`uv pip compile` a partir de los archivos `.in`; las de R mediante `renv`.
