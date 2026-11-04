# Natalidad en Colombia con Python y R

Proyecto para la charla relámpago **Python limpia, R analiza: un flujo reproducible
para el análisis de datos abiertos de natalidad en Colombia**, LatinR 2026.

El alcance aprobado es el análisis de nacimientos registrados entre 2015 y 2023:
tendencias por departamento, distribución por edad de la madre y diferencias
urbano-rurales. Python prepara los datos, Parquet permite intercambiarlos con R,
y R realizará el análisis, las visualizaciones y el reporte con Quarto.

**La etapa implementada actualmente es la centralización previa de los nueve CSV
de nacimientos.** Produce un Parquet verificable, sin aplicar todavía las reglas
de limpieza estadística ni generar resultados sustantivos de la charla.

## Inicio rápido

### Requisitos

- Python **3.12**, de 64 bits, con `venv` y `pip`.
- Git para clonar, o descargar y descomprimir el ZIP del repositorio.
- Conexión para instalar los paquetes de Python la primera vez. Los CSV originales
  ya están incluidos; la ejecución posterior no descarga datos.

R y Quarto se incorporarán en las siguientes etapas. No se necesitan para ejecutar
la centralización. Las instrucciones siguientes funcionan desde la raíz del proyecto.

```text
git clone https://github.com/didcasva/LatinR_Python_R.git
cd LatinR_Python_R
```

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe reproducir.py
```

No es necesario activar el entorno ni cambiar la política de ejecución de PowerShell.
Comprueba con `python --version` que el intérprete utilizado para crear el entorno
sea Python 3.12.

### Linux y macOS

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python reproducir.py
```

El proceso localiza los datos con relación al código, no mediante rutas particulares
del computador. También puede invocarse desde otra carpeta indicando la ruta del script.

## Qué hace la etapa 0

1. Exige exactamente un CSV por año de 2015 a 2023 en `Data_Raw/Nacimientos/`.
2. Calcula SHA-256 de cada archivo original y verifica su estructura con el lector
   CSV de Python, incluyendo registros entrecomillados que ocupan varias líneas.
3. Cuenta registros lógicos, valida el número de campos e inventaría las columnas.
4. Construye la unión de las columnas, manteniendo el orden en que aparecen por año.
5. Lee con pandas en bloques de 50.000 registros y escribe progresivamente un único
   Parquet comprimido con Zstandard mediante PyArrow.
6. Comprueba el esquema y los conteos por año y archivo al leer el Parquet.
7. Vuelve a verificar las huellas de los originales y publica los productos validados.

Si falta un año, hay archivos duplicados, encabezados ambiguos o registros con un
número incorrecto de campos, la ejecución termina con un error. Durante la inspección,
conversión y validación se trabaja en una carpeta temporal; un fallo en esas etapas
conserva los resultados definitivos de una ejecución anterior.

### Conservación de valores y trazabilidad

- Todos los campos originales se guardan como **texto**: se conservan códigos como
  `05`, `001`, `00`, `NA`, `9` o `99`, sin interpretarlos automáticamente como números
  o valores faltantes.
- Un campo vacío existente en el CSV se conserva como cadena vacía `""`.
- Una columna que no existía en un año se representa con `null` para ese año.
- Sólo se retiran espacios exteriores de los nombres de columnas. Si esto genera
  nombres repetidos, se detiene el proceso.
- Se agregan `ANIO_FUENTE` (entero de 16 bits) y `ARCHIVO_FUENTE` (texto).
- El campo original `ANO` se conserva: año del archivo y año del hecho no se
  sustituyen entre sí.
- Se conserva el orden de los registros de cada archivo y se procesan los años
  en orden ascendente. No se eliminan registros repetidos ni se imputan valores.
- Las líneas completamente vacías se omiten y quedan contabilizadas en el manifiesto.

La codificación se comprueba intentando decodificar todo el archivo como UTF-8.
Si falla, se utiliza **Latin-1**, el respaldo definido para estas fuentes. Esto no
pretende identificar cualquier codificación posible: el valor utilizado por archivo
queda registrado para revisión.

## Productos generados

Todos se guardan en `Data_Processed/`:

| Archivo | Contenido |
| --- | --- |
| `nacimientos_consolidados.parquet` | Registros originales unificados y procedencia. |
| `centralizacion_archivos.csv` | Conteos, columnas ausentes, codificación, tamaño y SHA-256 por fuente. |
| `centralizacion_columnas.csv` | Presencia de cada columna en cada año. |
| `centralizacion_manifiesto.json` | Reglas, fuentes, validaciones, entorno, huella del Parquet y métricas de ejecución. |

Son productos regenerables y están excluidos de Git. Los CSV de `Data_Raw/` se
conservan como fuentes originales. Repetir el comando regenera los cuatro productos.

El manifiesto se publica al final y registra la huella del Parquet. Una interrupción
durante el reemplazo de los productos puede dejar archivos de ejecuciones distintas:
la huella permite detectar esa situación y una nueva ejecución completa los regenera.

### Memoria y tiempo

Se registra el tiempo de inspección, conversión y validación, junto con la mayor
memoria RSS **observada** del proceso, muestreada cada 0,1 segundos. Esta medición
incluye el intérprete y las bibliotecas; dentro de un notebook incluye también su
proceso de kernel. No representa el pico exacto del sistema ni una comparación
de rendimiento entre Python y R.

Para reducir el tamaño de cada bloque:

```text
python reproducir.py --filas-por-bloque 10000
```

También se aceptan `--entrada` y `--salida` para rutas alternativas. La salida debe
estar separada de las fuentes y no puede estar dentro del `Data_Raw` del proyecto.
Consulta `python reproducir.py --help` para ver las opciones.

## Notebook para la charla

`Notebooks/00_Unificar_CSV_2015_2023.ipynb` explica y ejecuta la misma implementación
del comando, evitando mantener dos versiones distintas de la lógica.

Para utilizarlo, instala las dependencias opcionales en el mismo entorno:

```text
python -m pip install -r requirements-notebook.txt
```

En Windows utiliza `.\.venv\Scripts\python.exe` y en Linux/macOS `.venv/bin/python`
en lugar de `python` si el entorno no está activado. Abre el notebook con un editor
compatible y selecciona ese intérprete como kernel. El notebook localiza la raíz
desde la carpeta del proyecto o desde `Notebooks/`; no requiere modificar rutas.

## Estructura del repositorio

```text
Data_Raw/
  Nacimientos/                 # Única fuente de esta ejecución
  Defuciones/                  # Fuera del alcance de la charla aprobada
  Fetales/                     # Fuera del alcance de la charla aprobada
Data_Processed/                # Productos regenerables
Diccionario/                   # Catálogo de variables de nacimientos
Municipios/                    # Referencia DIVIPOLA
Python/
  centralizar_nacimientos.py   # Implementación compartida
Notebooks/
  00_Unificar_CSV_2015_2023.ipynb
R/                             # Próxima etapa: análisis
Reports/                       # Próxima etapa: reporte Quarto
tests/                         # Pruebas con datos pequeños, sin alterar originales
reproducir.py                  # Comando de la etapa 0
requirements.in               # Dependencias directas
requirements.txt              # Versiones fijadas, incluidas las transitivas
requirements-notebook.in      # Dependencias opcionales del notebook
requirements-notebook.txt     # Versiones fijadas del entorno de notebook
.python-version               # Versión menor de Python usada por el proyecto
```

## Comprobaciones para quien desarrolla

Las pruebas comprueban conservación de ceros iniciales, cadenas vacías y códigos;
columnas ausentes; diferentes codificaciones; campos con saltos de línea; inventarios
ambiguos; CSV mal formados; protección de fuentes y fallos de escritura. No dependen
del volumen de los datos reales.

También se prueba el comando desde otra carpeta, en una copia sin `.git` y con
espacios en la ruta. Si se instalaron las dependencias de notebook, se ejecutan
todas sus celdas en otra copia aislada con nueve CSV pequeños. En el entorno básico,
esa prueba opcional se informa como omitida.

```text
python -m unittest discover -s tests -v
```

Los valores del Parquet y los conteos deben ser iguales para las mismas fuentes y
reglas. La fecha, el tiempo y la memoria del manifiesto varían entre ejecuciones.
El tamaño de bloque puede cambiar la organización física y la huella del Parquet
sin cambiar sus valores.

Las versiones instalables están fijadas en los archivos `.txt`. Para actualizarlas
deliberadamente, un mantenedor puede usar `uv` y volver a ejecutar las comprobaciones:

```text
uv pip compile requirements.in --universal --python-version 3.12 --no-header --annotation-style line -o requirements.txt
uv pip compile requirements-notebook.in --universal --python-version 3.12 --no-header --annotation-style line -o requirements-notebook.txt
```

## Siguientes etapas dentro del alcance aprobado

1. Documentar los códigos de valores faltantes por variable y año, y preparar las
   variables de análisis sin confundir categorías con magnitudes numéricas.
2. Validar códigos DIVIPOLA y distinguir residencia habitual de la madre del lugar
   de ocurrencia del nacimiento.
3. Analizar nacimientos por año y departamento, grupos de edad materna y área de
   residencia con R; documentar numeradores y denominadores de cada indicador.
4. Incorporar geometrías departamentales documentadas para los mapas y, si se
   presentan tasas poblacionales, las poblaciones de referencia del DANE.
5. Generar el reporte con Quarto y fijar las dependencias de R con `renv` al
   implementar esa etapa.

## Referencias

- [DANE: nacimientos y defunciones](https://www.dane.gov.co/index.php/estadisticas-por-tema/salud/nacimientos-y-defunciones).
- [pandas: procesamiento de datos grandes](https://pandas.pydata.org/docs/user_guide/scale.html).
- [PyArrow: escritura progresiva de Parquet](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetWriter.html).
- [Arrow para R](https://arrow.apache.org/docs/r/).

Las fuentes exactas utilizadas quedan identificadas por nombre y SHA-256 en el
manifiesto. El diccionario, el documento DDI y la propuesta aprobada se conservan
en el repositorio como referencias del proyecto.
