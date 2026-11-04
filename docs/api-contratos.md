# API y contratos

Entradas, salidas, errores y ejemplos de la API web y de las funciones públicas del motor. Con el servidor levantado, la documentación interactiva (Swagger) queda en `/docs`, con el esquema de cada respuesta. Cómo levantarlo está en [API web](instalacion.md#api-web).

## API web

### `GET /buscar`

Devuelve los documentos que contienen **todos** los términos de la consulta, ordenados por relevancia (TF-IDF).

| Parámetro | Tipo | Obligatorio | Restricción |
| :--- | :--- | :--- | :--- |
| `q` | texto | Sí | Al menos un carácter que no sea un espacio. |
| `top_k` | entero | No, por defecto 10 | Entre 1 y 100. |

| Campo de la respuesta | Tipo | Descripción |
| :--- | :--- | :--- |
| `consulta` | texto | La consulta, sin espacios de más. |
| `total` | entero | Documentos que contienen todos los términos. No depende de `top_k`. |
| `resultados` | lista | Los mejores documentos, de mayor a menor `score`. |
| `resultados[].documento` | texto | Nombre del archivo del corpus. |
| `resultados[].score` | decimal | Puntaje TF-IDF; mayor es más relevante. |

```bash
curl "http://127.0.0.1:8000/buscar?q=algoritmo&top_k=2"
```

```json
{
  "consulta": "algoritmo",
  "total": 2,
  "resultados": [
    { "documento": "doc_000002.txt", "score": 0.8109302162163288 },
    { "documento": "doc_000001.txt", "score": 0.4054651081081644 }
  ]
}
```

Una consulta sin coincidencias no es un error: responde 200 con `"total": 0` y `"resultados": []`.

### `POST /reindexar`

Reconstruye y vuelve a guardar el índice aunque el directorio del corpus no haya cambiado. Sirve para tomar cambios dentro de archivos existentes, que no alteran la fecha del directorio. No recibe parámetros.

| Campo de la respuesta | Tipo | Descripción |
| :--- | :--- | :--- |
| `documentos` | entero | Documentos indexados. |
| `terminos` | entero | Términos distintos en el índice. |
| `segundos` | decimal | Lo que tardó la reconstrucción. |

```bash
curl -X POST http://127.0.0.1:8000/reindexar
```

```json
{ "documentos": 3, "terminos": 8, "segundos": 0.002 }
```

### Errores

| Código | Cuándo | Cuerpo |
| ---: | :--- | :--- |
| 422 | `q` vacío o `top_k` fuera de rango. Lo valida FastAPI. | `{"detail": [{"type": "string_too_short", "loc": ["query", "q"], ...}]}` |
| 422 | `q` con solo espacios. | `{"detail": "La consulta no puede estar vacía"}` |
| 503 | No existe el directorio del corpus, en cualquiera de los dos endpoints. | `{"detail": "No existe el directorio del corpus: <ruta>"}` |

## Funciones del motor

Contratos de las funciones que usan la API y los scripts. La referencia completa, generada desde los docstrings, está en [Módulos](api/modules).

| Función | Entrada | Salida | Errores y casos borde |
| :--- | :--- | :--- | :--- |
| `baseline.busqueda_secuencial(directorio, query)` | Directorio y texto; no distingue mayúsculas. | `list[str]`: archivos que contienen el texto como subcadena. | `FileNotFoundError` si no existe el directorio. |
| `optimizado.construir_indice(corpus_dir)` | `Path` del corpus. | `(indice, archivos)`: `término -> {doc_id: frecuencia}` y la lista ordenada de rutas, cuya posición es el `doc_id`. | Sin directorio o sin documentos: `({}, [])`. Un archivo ilegible queda fuera del índice, pero conserva su `doc_id`. |
| `concurrente.construir_indice(corpus_dir, workers=None, ...)` | Corpus y cantidad de procesos. | La misma estructura y los mismos `doc_id` que la versión secuencial. | Sin directorio o sin documentos: `({}, [])`. Con un proceso o menos de 512 archivos, indexa en el proceso padre. |
| `optimizado.Buscador(indice, archivos).buscar(consulta, top_k=10)` | Texto tal como lo escribe el usuario y cantidad máxima de resultados. | `(total, resultados)`: `resultados` son pares `(doc_id, score)`, de mayor a menor. | Consulta vacía o solo con *stopwords*: `(0, [])`. |
| `optimizado.normalizar_consulta(consulta)` | Texto. | Tupla ordenada de términos únicos, normalizados. | Sin términos: `()`. |
| `optimizado.QueryCache(maxsize=1024)` | Cantidad máxima de entradas. | Caché LRU segura entre hilos, con `get`, `put` e `info`. | `get` devuelve `None` si la clave no está. |
| `core.procesamiento_texto.tokenizar(texto)` | Texto. | `list[str]`: términos normalizados, sin *stopwords* y con *stemming*. | Sin palabras: `[]`. |
| `core.lectura.contar_terminos(ruta, tamano_bloque=None)` | Archivo y bytes por lectura (64 KiB por defecto). | `Counter` con la frecuencia de cada término. | `OSError` si no se puede abrir. Los bytes que no son UTF-8 se ignoran. |
| `indice_en_disco.obtener_indice(corpus_dir, directorio, forzar=False)` | Corpus y directorio del índice. | `(indice, archivos, desde_disco)`. | `FileNotFoundError` si no existe el corpus. Un índice guardado de otro corpus, de otro formato o dañado se descarta y se reconstruye. |

Ejemplo de uso desde Python, con `src/` en el `sys.path`:

```python
from pathlib import Path

from optimizado import Buscador, construir_indice

indice, archivos = construir_indice(Path("data/corpus"))
buscador = Buscador(indice, archivos)

total, resultados = buscador.buscar("Algoritmos y datos", top_k=5)

for doc_id, score in resultados:
    print(archivos[doc_id].name, score)
```

## Línea de comandos

| Script | Parámetros | Salida |
| :--- | :--- | :--- |
| `src/baseline.py` | `--generar --num-docs N`, `--query TEXTO`, `--directorio RUTA` | Genera el corpus o imprime el tiempo y las coincidencias. |
| `src/optimizado.py` | `--query TEXTO`, `--top-k N`, `--directorio RUTA`, `--cache-size N` | Tiempo de indexación y de búsqueda, ranking y estado de la caché. |
| `src/concurrente.py` | Los de `optimizado.py`, más `--workers N` y `--comparar` | Lo mismo, y con `--comparar`, el *speedup* y si los índices son idénticos. |
| `src/servidor.py` | `--host` (127.0.0.1), `--port` (8000), `--env-file RUTA` | Levanta la API, con New Relic si hay licencia. |
| `src/generar_trafico.py` | `--duracion S` o `--solicitudes N`, `--concurrencia N`, `--mezcla A,B,C`, `--semilla N`, `--reindexar-cada S`, `--salida RUTA` | p50, p95, p99 y máximo por tipo de consulta. |
| `src/perfilar_api.py` | `--consultas N`, `--reindexar`, `--cprofile RUTA` | Hace el trabajo de la API en un solo proceso, para perfilarlo. |
| `src/perfilado.py` | `--comparativa`, `--escalabilidad`, `--cprofile`, `--line`, `--memoria`, `--scalene`, `--graficos`, `--reporte`, `--todo` | Tablas, gráficos y un reporte HTML en `profiles/`. |

Si no existe el directorio del corpus, `optimizado.py` y `concurrente.py` imprimen el error y terminan sin indexar.
