# Instalación y ejecución

Comandos para instalar el proyecto, generar el corpus y ejecutar cada versión del buscador. Se corren desde la raíz del repositorio, con el entorno virtual activado.

## Requisitos previos

- **Python 3.11 o superior.** El CI usa 3.14, igual que las mediciones de [Rendimiento](rendimiento.md).
- **Node.js**, solo para `make docs`, que corre markdownlint con `npx`.
- **Graphviz**, solo para regenerar el diagrama de arquitectura con `make diagrama`.

```bash
git clone https://github.com/JoniMora/pef-26.git
cd pef-26

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
```

> Los scripts resuelven la ruta del corpus a partir de la ubicación del propio archivo (`<repo>/data/corpus`), no del directorio de trabajo.

## Dependencias

`baseline.py`, `optimizado.py` y `concurrente.py` usan solo la biblioteca estándar: para correrlos no hay que instalar nada. El resto depende de para qué se use:

| Archivo | Para qué | Instalación |
| :--- | :--- | :--- |
| [`requirements.txt`](https://github.com/JoniMora/pef-26/blob/master/requirements.txt) | Correr la API (FastAPI y uvicorn). Fija Starlette 1.8.0, que corrige [seis vulnerabilidades](seguridad.md#dependencias-vulnerables). | `pip install -r requirements.txt` |
| [`requirements-dev.txt`](https://github.com/JoniMora/pef-26/blob/master/requirements-dev.txt) | Los controles del CI: incluye `requirements.txt`, las herramientas de calidad y de documentación, `pip-audit` y `httpx2`. | `make instalar` |
| [`requirements-perfilado.txt`](https://github.com/JoniMora/pef-26/blob/master/requirements-perfilado.txt) | Las herramientas de medición, que no corren en el CI. | `pip install -r requirements-perfilado.txt` |
| [`requirements-apm.txt`](https://github.com/JoniMora/pef-26/blob/master/requirements-apm.txt) | El agente de New Relic, para monitorear la API con `src/servidor.py`. | `pip install -r requirements-apm.txt` |
| [`requirements-informes.txt`](https://github.com/JoniMora/pef-26/blob/master/requirements-informes.txt) | Generar el informe en PDF de New Relic. | `pip install -r requirements-informes.txt` |

## Configuración

Todo es opcional: sin estas variables, el proyecto usa los valores por defecto.

| Variable | Para qué | Por defecto |
| :--- | :--- | :--- |
| `BUSCADOR_CORPUS` | Directorio del corpus que usan la API y los scripts que la perfilan. | `data/corpus` |
| `BUSCADOR_INDICE` | Dónde se guarda el índice. No puede ir adentro del corpus. | `data/indice_corpus`, hermano del corpus |
| `NEW_RELIC_LICENSE_KEY` | Activa el agente en `src/servidor.py`. Va en un `.env`, que git ignora. | Sin definir: sin monitoreo |
| `NEW_RELIC_APP_NAME` | Nombre de la aplicación en New Relic. | `pef-26` |
| `NEW_RELIC_CONFIG_FILE` | Configuración del agente, por ejemplo una copia de [`newrelic.ini.example`](https://github.com/JoniMora/pef-26/blob/master/newrelic.ini.example). | Sin definir |
| `CORPUS_DOCS` | Tamaño del corpus que generan los tests. | `2000` |
| `LIMITE_CONSULTA_S` | Límite del Performance Gate, en segundos. | `0.5` |

## Preparación del corpus

El corpus es **sintético**: se genera localmente con `generar_corpus_prueba()`, no se descarga.

La generación vive únicamente en `src/baseline.py`; `src/optimizado.py` y `src/concurrente.py` solo consumen el corpus ya generado.

```bash
# Genera 50.000 documentos .txt en <repo>/data/corpus
python3 src/baseline.py --generar --num-docs 50000

# Verificación rápida del corpus generado
find data/corpus -name '*.txt' | wc -l
du -sh data/corpus
```

## Prueba de línea base

```bash
# Consulta sobre el corpus completo; imprime tiempo (ms) y coincidencias
python3 src/baseline.py --query "algoritmo"

# Sobre un corpus en otra ubicación
python3 src/baseline.py --query "algoritmo" --directorio /ruta/al/corpus
```

Salida esperada:

```text
Tiempo de ejecucion: 2558.302 ms
Documentos encontrados: 47797
```

## Prueba optimizada

```bash
# Índice invertido + intersección de set + ranking top-k con heap
python3 src/optimizado.py --query "algoritmo" --top-k 10

# Parámetros disponibles
python3 src/optimizado.py --query "algoritmo" \
    --top-k 10 \
    --directorio /ruta/al/corpus \
    --cache-size 1024
```

Salida esperada:

```text
Construyendo índice invertido...
Documentos indexados: 50000
Términos en el índice: 39
Tiempo de construcción del índice: 8537.13 ms

Tiempo de búsqueda: 9.5199 ms
Documentos encontrados: 47797 (se muestran los 10 mejores)

Resultados:
------------------------------------------------------------
1. doc_013616.txt (score=0.8561)
2. doc_014443.txt (score=0.8111)
3. doc_034857.txt (score=0.8111)
...

Información de caché:
{'hits': 0, 'misses': 1, 'size': 1}
```

> El `score` es TF-IDF, por eso es decimal y no entero. Los valores son bajos porque `algoritmo` aparece en 47.797 de 50.000 documentos: `log(50000/47797) ≈ 0,045` por ocurrencia.

> `Documentos encontrados` informa el **total de coincidencias**, no la cantidad de filas mostradas: es el valor que se compara contra la línea base. `top-k` solo acota la página impresa.
>
> La caché siempre reporta `misses: 1` porque el proceso resuelve una sola consulta y termina (ver la limitación del *harness* en [Caching Inteligente](diseno-tecnico.md#caching-inteligente)).

## Prueba concurrente

```bash
# Indexación MapReduce con ProcessPoolExecutor; P = os.cpu_count() por defecto
python3 src/concurrente.py --query "algoritmo" --top-k 10

# Grado de paralelismo explícito
python3 src/concurrente.py --query "algoritmo" --top-k 10 --workers 4

# Contrasta la indexación paralela contra la secuencial en una sola corrida
python3 src/concurrente.py --workers 4 --comparar
```

Salida esperada:

```text
Construyendo índice invertido con 4 procesos...
Documentos indexados: 50000
Términos en el índice: 39
Tiempo de construcción del índice: 4698.22 ms

Tiempo de búsqueda: 9.2928 ms
Documentos encontrados: 47797 (se muestran los 10 mejores)

Resultados:
------------------------------------------------------------
1. doc_013616.txt (score=0.8561)
2. doc_014443.txt (score=0.8111)
3. doc_034857.txt (score=0.8111)
...
```

Con `--comparar` se agrega el contraste contra la ruta secuencial:

```text
Índice secuencial: 8701.79 ms
Speedup: 1.86x
Índices idénticos: True
```

> `Índices idénticos: True` compara los dos diccionarios completos, no un resumen: términos, `doc_id` y frecuencias. Es la verificación de equivalencia del incremento 4.
>
> El `--comparar` construye el índice **dos veces** en el mismo proceso, así que su tiempo total es la suma de ambas rutas. Para cronometrar, usar las corridas por separado.

## API web

```bash
pip install -r requirements.txt
uvicorn api:app --app-dir src          # documentación interactiva en http://127.0.0.1:8000/docs

curl "http://127.0.0.1:8000/buscar?q=algoritmo&top_k=5"
curl -X POST http://127.0.0.1:8000/reindexar

# Otro corpus, u otro directorio para el índice guardado
BUSCADOR_CORPUS=/ruta/al/corpus BUSCADOR_INDICE=/ruta/al/indice uvicorn api:app --app-dir src
```

Para monitorear la API con New Relic, el lanzador `src/servidor.py` activa el agente solo si existe la variable `NEW_RELIC_LICENSE_KEY`. La licencia va en un `.env`, que git ignora, y nunca en el código:

```bash
pip install -r requirements-apm.txt
echo "NEW_RELIC_LICENSE_KEY=<licencia INGEST - LICENSE>" > .env

python src/servidor.py --env-file .env     # New Relic: activo (app pef-26)
python src/servidor.py                     # sin licencia: arranca igual, sin monitoreo

# Opcional: configuración del agente a partir de la plantilla (no lleva claves)
cp newrelic.ini.example newrelic.ini
NEW_RELIC_CONFIG_FILE=newrelic.ini python src/servidor.py --env-file .env
```

Para generar carga contra la API levantada (usa `httpx2`, de `requirements-dev.txt`):

```bash
# 60 s con 50 usuarios simultáneos: 60 % consultas repetidas, 30 % variadas, 10 % inexistentes
python src/generar_trafico.py --duracion 60 --concurrencia 50 --mezcla 60,30,10

# Cantidad fija y reproducible, con una recarga del índice cada 30 s
python src/generar_trafico.py --solicitudes 5000 --semilla 1 --reindexar-cada 30
```

> Imprime p50, p95, p99 y máximo por tipo de consulta, y guarda el resumen en `profiles/trafico.json`. Entre escenarios conviene reiniciar el servidor: la caché de consultas sobrevive entre corridas.

> La primera construcción del índice usa procesos con el método de arranque `spawn`, que vuelve a importar el script principal en cada proceso. Uvicorn ya lo tiene en cuenta, pero un script propio que use la API directamente (por ejemplo, con `TestClient`) tiene que tener la guarda `if __name__ == "__main__":`.

Los contratos de cada endpoint están en [API y contratos](api-contratos.md).
