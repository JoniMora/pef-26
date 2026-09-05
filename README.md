# Buscador Eficiente de Información

Motor de búsqueda local (full-text) sobre una colección masiva de documentos de texto plano. Implementación en **Python 3.11+**.

---

## Objetivo del Proyecto

Construir un motor de recuperación de información que, dada una consulta de uno o más términos, devuelva los `k` documentos más relevantes de un corpus de escala no trivial (corpus de prueba actual: **50.000 documentos sintéticos / 68,7 MB de texto**), y demostrar empíricamente la mejora de rendimiento entre una implementación secuencial ingenua y una versión optimizada.

El sistema se compone de cuatro etapas:

| Etapa | Responsabilidad |
| :--- | :--- |
| **Ingesta** | Lectura y decodificación de los documentos del corpus desde disco. |
| **Normalización** | Tokenización, *casefolding*, remoción de puntuación, filtrado de *stopwords* y *stemming*. |
| **Indexación / Búsqueda** | Resolución de los términos de la consulta contra la estructura de datos de acceso. |
| **Ranking** | Puntuación de los documentos candidatos (TF-IDF) y selección del *top-k*. |

El requisito central de la asignatura no es la funcionalidad —ambas versiones deben devolver **resultados idénticos**, lo que se verificará por test de equivalencia—, sino la **evidencia cuantificada de la mejora**. Cada optimización debe estar justificada por su complejidad algorítmica y validada con mediciones reproducibles de tiempo y memoria obtenidas mediante herramientas de perfilado formales.

El proyecto se versiona en cuatro incrementos medibles y comparables entre sí:

1. **Inicial** — búsqueda secuencial sobre el corpus crudo.
2. **Estructura Optimizada** — índice invertido con `dict` y `set`.
3. **Algoritmo Optimizado** — ranking parcial con *heap* y caching de consultas.
4. **Concurrente** — construcción del índice en paralelo mediante múltiples procesos.

---

## Línea Base (Baseline)

La primera implementación resuelve la consulta por **fuerza bruta**, sin ninguna estructura de indexación previa. Es intencionalmente ingenua: su función es establecer el punto de referencia contra el cual se miden todas las optimizaciones posteriores.

**Algoritmo:**

```
para cada archivo .txt del directorio:
    abrir el archivo y leer TODO su contenido en memoria (.read())
    convertir el contenido completo a minúsculas (.lower())
    si la query aparece como subcadena (.find() != -1):
        acumular el nombre del archivo en una lista
devolver la lista de coincidencias
```

Implementado en [`src/baseline.py`](src/baseline.py) (`busqueda_secuencial`). Sin índices, `dict` de caché, `set`, generadores ni concurrencia: la ineficiencia es deliberada.

> **Alcance actual.** La línea base resuelve **presencia por subcadena**, no relevancia: no tokeniza ni puntúa, y por lo tanto **no produce un ranking *top-k***. Las etapas de Normalización y Ranking descritas en el objetivo se incorporan en la versión optimizada. Esto tiene una consecuencia directa sobre el test de equivalencia: `.find()` sobre el texto crudo hace que `"algo"` matchee dentro de `"algoritmo"`, mientras que un índice invertido sobre tokens no lo haría. Para que la comparación sea válida, **ambas versiones deben acordar la misma semántica de coincidencia** antes de medir; se adoptará la de tokens y se ajustará la línea base en consecuencia.

**Análisis de complejidad:**

| Dimensión | Costo | Observación |
| :--- | :--- | :--- |
| Búsqueda por consulta | **O(n · m)** | `n` = documentos del corpus, `m` = tokens promedio por documento. |
| Comprobación de pertenencia | **O(m)** | Búsqueda de subcadena con `str.find()` sobre el contenido completo del documento. |
| Ordenamiento del ranking | — | No implementado en la línea base: devuelve todas las coincidencias sin puntuar ni ordenar. |
| E/S de disco | **O(n)** lecturas | El corpus completo se lee y decodifica **en cada consulta**. |
| Memoria | **O(m)** | Bajo consumo residente, a costa de re-procesar todo el corpus. |

**Costos dominantes identificados:**

- **Trabajo redundante:** el corpus se lee, decodifica y tokeniza íntegramente en cada consulta. Ninguna computación se reutiliza entre invocaciones.
- **Escalado lineal:** el tiempo de respuesta crece proporcionalmente al tamaño del corpus, no al tamaño del resultado. Duplicar los documentos duplica la latencia.
- **Saturación de E/S:** con corpus superiores a la memoria disponible, el proceso queda limitado por el ancho de banda del disco, no por la CPU.

- **Dominancia de la E/S sobre el algoritmo.** Medido sobre el corpus de 50.000 documentos, el tiempo por consulta oscila entre **2.408 ms** y **14.040 ms** según el estado del *page cache* del sistema operativo: una dispersión de **5,8×** sobre código idéntico. Los 195 MB que el corpus ocupa en disco (68,7 MB de contenido, inflado por el bloque mínimo de 4 KB en 50.000 archivos) compiten con los 8 GB de RAM de la máquina de pruebas. Sin estabilizar el caché, cualquier comparación contra la versión optimizada mediría el disco, no el algoritmo.

Esta versión actúa como **oráculo de validación** de las versiones optimizadas, una vez unificada la semántica de coincidencia.

---

## Optimización y Estructuras de Datos

La optimización clave consiste en **invertir el costo**: se paga una única indexación *offline* de complejidad **O(N)** sobre el total de tokens del corpus, para que cada consulta *online* pase de **O(n · m)** a un costo proporcional al tamaño del resultado, no al del corpus.

### Índice invertido con `dict` (HashMap) — búsqueda O(1) promedio

La estructura central es un **índice invertido**: un mapeo de cada término a la lista de documentos donde aparece.

```python
inverted_index: dict[str, dict[int, int]]
# término -> { doc_id -> frecuencia_del_término }
```

**Justificación:** el `dict` de CPython es una tabla hash de direccionamiento abierto con *hashing* aleatorizado sobre `str`. Adicionalmente, CPython **cachea el hash de cada objeto `str` en su cabecera** (`ob_shash`), por lo que un término consultado repetidamente no vuelve a hashearse.

| Operación | `list` (baseline) | `dict` (optimizado) |
| :--- | :--- | :--- |
| Resolución de un término | O(n · m) | **O(1)** promedio, O(n) peor caso |
| Consulta de `t` términos | O(t · n · m) | **O(t)** promedio |

El peor caso O(n) por colisiones es irrelevante en la práctica: el vocabulario natural no es adversarial y el `SipHash` de CPython descarta la construcción de colisiones deliberadas.

### `set` para unicidad y álgebra de conjuntos

Los conjuntos resuelven dos problemas distintos con la misma estructura:

**1. Unicidad del vocabulario.** Durante la indexación, un `set` deduplica términos por documento y filtra *stopwords* en **O(1)** por token, frente a la comprobación **O(k)** de una `list`.

**2. Resolución de consultas booleanas.** Las *postings lists* se materializan como `set[int]` de identificadores de documento, permitiendo aplicar operaciones nativas —implementadas en C— para combinar términos:

```python
# AND: documentos que contienen todos los términos
candidatos = postings[t0] & postings[t1] & postings[t2]

# OR: documentos que contienen alguno
candidatos = postings[t0] | postings[t1]

# NOT: exclusión de un término
candidatos = postings[t0] - postings[t1]
```

La intersección de `set` en CPython **itera sobre el conjunto más pequeño** y consulta la pertenencia en el mayor, resultando en **O(min(|A|, |B|))** en lugar del producto cartesiano O(|A| · |B|) de una implementación con listas. Se ordenan los términos de la consulta por frecuencia documental ascendente antes de intersecar, de modo que el conjunto candidato se reduzca lo antes posible.

### `heapq` (Heap binario) para el ranking *top-k*

Ordenar completamente el conjunto de candidatos para devolver solo `k` resultados desperdicia trabajo. Se emplea un **min-heap de tamaño acotado `k`**: se recorren los candidatos y se descarta inmediatamente todo documento cuyo score no supere la raíz del heap.

```python
import heapq
top_k = heapq.nlargest(k, candidatos, key=lambda d: scores[d])
```

| Estrategia | Complejidad | Memoria auxiliar |
| :--- | :--- | :--- |
| `sorted()` completo | O(r · log r) | O(r) |
| **Heap acotado** | **O(r · log k)** | **O(k)** |

Con `r = 100.000` candidatos y `k = 10`, `log₂(r) ≈ 17` frente a `log₂(k) ≈ 3.3`: una reducción teórica de ~5× en las comparaciones del ranking, y una cota de memoria constante e independiente del tamaño del resultado intermedio.

### Resumen comparativo

| Aspecto | Línea Base | Optimizado |
| :--- | :--- | :--- |
| Acceso a documentos | Escaneo lineal O(n · m) | Hash lookup O(1) promedio |
| Combinación de términos | Recorrido anidado | `set` intersection O(min(\|A\|,\|B\|)) |
| Ranking | `sorted()` O(r · log r) | Heap acotado O(r · log k) |
| Lecturas de disco | En cada consulta | Una única vez, en indexación |
| Costo de indexación | Ninguno | O(N) tokens, amortizado |

---

## Caching Inteligente

Las consultas de un motor de búsqueda siguen una **distribución de Zipf**: un subconjunto reducido de términos concentra la mayor parte del tráfico. Esto hace que la memoización de consultas frecuentes ofrezca una tasa de aciertos alta con una memoria acotada.

### Herramienta elegida

Se implementa una capa de caché en dos niveles:

**Nivel 1 — `functools.lru_cache`** sobre las funciones puras y de alta frecuencia del pipeline de normalización (`stem(token)`, `normalize(token)`). Se elige por ser parte de la biblioteca estándar y estar **implementada en C** (`_functools`), con un costo de acceso despreciable frente a un decorador escrito en Python. Es la herramienta correcta aquí porque estas funciones son deterministas y sin estado externo: nunca requieren invalidación.

**Nivel 2 — `QueryCache`, una clase LRU propia sobre `collections.OrderedDict`** para el resultado completo de las consultas (`consulta -> top-k documentos`).

**Justificación de no usar `lru_cache` en el nivel 2:** `functools.lru_cache` es deliberadamente rígido y carece de tres capacidades que este nivel exige:

1. **Invalidación selectiva:** solo expone `cache_clear()`, que descarta la caché completa. No permite expulsar las entradas afectadas por un documento modificado.
2. **Política temporal:** no soporta TTL.
3. **Observabilidad y control:** `cache_info()` no permite instrumentar la métrica de aciertos por consulta ni acotar la caché por memoria en lugar de por cantidad de entradas.

`OrderedDict` provee `move_to_end()` y `popitem(last=False)` en **O(1)**, exactamente las primitivas de una política LRU, sobre una estructura que sí podemos inspeccionar y purgar de forma granular.

### Normalización de la clave

Para maximizar la tasa de aciertos, la clave no es la cadena literal de la consulta sino su **forma canónica**:

```python
clave = (frozenset(terminos_normalizados), k, modo_booleano)
```

Con esto, `"Programación Eficiente"`, `"eficiente programación"` y `"  PROGRAMACION   eficiente "` colapsan en la misma entrada. El `frozenset` es hashable e insensible al orden, e implica que la caché es correcta bajo semántica booleana conmutativa (AND / OR).

### Política de invalidación

La caché de consultas se invalida por **versionado del índice** (*generation counter*), evitando el costo de rastrear dependencias inversas término→consulta:

| Evento | Acción |
| :--- | :--- |
| Reconstrucción total del índice | Incremento de `index_generation` → toda entrada con generación anterior se considera obsoleta y se descarta *lazily* en el acceso. |
| Alta / baja / modificación de documento | Invalidación selectiva de las entradas cuya clave interseca los términos del documento afectado; el `mtime` y el tamaño del archivo actúan como testigo de cambio. |
| Presión de memoria | Expulsión LRU al alcanzar `maxsize` (por defecto **1024** entradas, configurable vía `--cache-size`). |
| TTL vencido | Expiración por `monotonic()` para corpus dinámicos (`--cache-ttl`, deshabilitado por defecto en corpus estáticos). |

Esta política es **conservadora**: ante la duda, se invalida. Un fallo de caché cuesta una consulta indexada —del orden de microsegundos—, mientras que un acierto obsoleto devuelve un resultado incorrecto.

---

## Concurrencia y Paralelismo

El cuello de botella medido en la versión optimizada se desplaza de la consulta a la **construcción del índice**: tokenizar y normalizar el corpus completo es un trabajo intensivo en CPU, perfectamente descomponible por documento.

### Justificación de la técnica: procesos, no hilos

En el build utilizado (CPython 3.14.0, con **GIL activo** — verificado con `sys._is_gil_enabled()`) el **GIL** (*Global Interpreter Lock*) serializa la ejecución de bytecode: los hilos de `threading` no producen paralelismo real en cargas *CPU-bound*. Como la tokenización y el *stemming* son operaciones de CPU sobre estructuras Python, la técnica correcta es el **paralelismo por múltiples procesos**, donde cada intérprete posee su propio GIL y se aprovechan todos los núcleos físicos.

```python
from concurrent.futures import ProcessPoolExecutor
```

Se elige `concurrent.futures.ProcessPoolExecutor` sobre `multiprocessing.Pool` por su API de `Future`, su propagación limpia de excepciones desde los procesos hijos y su integración con `as_completed()` para el reporte de progreso incremental.

`ThreadPoolExecutor` se reserva exclusivamente para la fase de **lectura de archivos**, que es *I/O-bound* y libera el GIL durante las llamadas al sistema.

### Arquitectura: MapReduce sobre particiones del corpus

```
                    ┌─── Worker 1 ──> índice parcial 1 ───┐
   Corpus  ──particiona──> Worker 2 ──> índice parcial 2 ──── merge ──> Índice global
   (n docs)         └─── Worker P ──> índice parcial P ───┘
```

| Fase | Operación | Complejidad |
| :--- | :--- | :--- |
| **Particionado** | División del corpus en `P` lotes contiguos de documentos. | O(n) |
| **Map** (paralelo) | Cada worker construye un índice invertido parcial sobre su lote. | O(N / P) |
| **Reduce** | Fusión de los `P` índices parciales en el índice global. | O(V · P), `V` = vocabulario |

La fase *Map* no comparte estado mutable entre procesos: cada worker opera sobre un subconjunto disjunto de archivos y devuelve una estructura independiente. Al no existir escritura concurrente, **no se requieren locks**, eliminando la contención y las condiciones de carrera por construcción.

### Decisiones de implementación

- **Granularidad por lotes, no por documento.** La comunicación entre procesos exige serialización con `pickle`; despachar un archivo por tarea haría que el costo de IPC dominara sobre el trabajo útil. Se agrupan los documentos en lotes (`chunksize` calculado como `ceil(n / (P · 4))`) para amortizar ese *overhead*.
- **Payload de retorno compacto.** Los workers devuelven las *postings* con `doc_id` enteros y no cadenas de texto, minimizando el volumen serializado en el canal de retorno.
- **`spawn` como método de arranque.** En macOS el método por defecto es `spawn`: cada proceso hijo reimporta el módulo principal, por lo que todo el código de arranque queda protegido bajo `if __name__ == "__main__":`. Sin esta guarda, el programa entra en recursión infinita de procesos.
- **Grado de paralelismo.** `P = os.cpu_count()` por defecto, ajustable con `--workers`. En la máquina de pruebas `os.cpu_count()` devuelve **4** (lógicos), pero solo hay **2 núcleos físicos**: al ser la indexación una carga CPU-bound, el *Hyper-Threading* aporta poco y el techo realista de *speedup* ronda **2×**, no 4×. Se medirán ambos valores de `P`. La escalabilidad está además acotada por la **ley de Amdahl**: la fase *Reduce* es inherentemente secuencial y fija el techo del *speedup* alcanzable.

---

## Perfilado y Comparativa de Rendimiento

Las métricas de esta sección **no se estiman ni se derivan teóricamente**: se obtienen exclusivamente mediante herramientas de perfilado formales, sobre el mismo corpus, la misma máquina y el mismo conjunto de consultas de prueba.

### Instrumental de medición

| Dimensión | Herramienta | Uso |
| :--- | :--- | :--- |
| CPU (determinista) | **`cProfile` + `pstats`** | Costo acumulado por función; identificación de *hotspots*. |
| CPU (visualización) | **`snakeviz`** | Inspección jerárquica del grafo de llamadas. |
| CPU (línea a línea) | **`line_profiler`** (`@profile`) | Costo por línea dentro de los *hotspots* detectados. |
| Tiempo de pared | **`timeit`** / `time.perf_counter()` | Latencia de consulta; mínimo de N repeticiones. |
| Memoria (asignaciones) | **`tracemalloc`** | Pico de memoria y atribución por línea de código. |
| Memoria (residente) | **`memory_profiler`** (`mprof`) | Evolución del RSS del proceso a lo largo del tiempo. |

### Protocolo de medición

- **Corpus:** idéntico en todas las corridas; se documentan cantidad de documentos y tamaño total en disco.
- **Repeticiones:** 10 corridas por versión; se reporta la **mediana** para descartar valores atípicos.
- **Caché de sistema operativo:** se descartan las corridas hasta alcanzar el régimen estacionario. Una única corrida de calentamiento resultó **insuficiente**: sobre este corpus hicieron falta **3 corridas** para que el *page cache* se estabilizara (13.570 → 14.040 → 10.795 ms, y recién a partir de la cuarta ~2.450 ms). Se reporta la mediana del régimen estacionario y se declara además el rango frío.
- **Aislamiento:** las mediciones de tiempo se toman **sin** el perfilador activo, dado que `cProfile` introduce sobrecarga; el perfilador se usa para atribuir costo, no para cronometrar.
- **Métricas separadas:** se registran por separado el **tiempo de construcción del índice** (costo único) y el **tiempo de consulta** (costo recurrente).

### Resultados

Consulta de referencia: `"algoritmo"` sobre 50.000 documentos (47.797 coincidencias).

| Versión | Tiempo de ejecución (ms) | Consumo de Memoria (MB) | Observaciones |
| :--- | ---: | ---: | :--- |
| Inicial (Baseline) | 2.485 | 18,3 | Mediana de 10 corridas en régimen estacionario (min 2.408 / max 2.569, ±3%). Con *page cache* frío: **10.795–14.040 ms**. Lectura completa del corpus en cada consulta; sin ranking. |
| Estructura Optimizada | | | *Pendiente de implementación.* |
| Algoritmo Optimizado | | | *Pendiente de implementación.* |
| Concurrente | | | *Pendiente de implementación.* |

**Cómo se obtuvieron los valores de la fila medida**

- **Tiempo:** `time.perf_counter()` alrededor de `busqueda_secuencial()`, 10 repeticiones tras estabilizar el *page cache*; se reporta la mediana.
- **Memoria:** pico de *resident set size* vía `/usr/bin/time -l` (19.165.184 bytes = 18,3 MB). El bajo consumo es consistente con el análisis O(m): la línea base mantiene un solo documento en memoria por vez, a costa de releer todo el corpus.

### *Hotspots* de la línea base

Salida de `cProfile` ordenada por tiempo acumulado (corrida instrumentada, 23,1 s por la sobrecarga del perfilador):

```
   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
        1    0.717    0.717   23.112   23.112 src/baseline.py:71(busqueda_secuencial)
    50000   16.008    0.000   16.434    0.000 {method 'read' of '_io.TextIOWrapper'}
    50000    4.307    0.000    4.408    0.000 {built-in method _io.open}
```

El perfil confirma cuantitativamente el diagnóstico de la sección Línea Base: **`read()` concentra el 69% del tiempo y `open()` el 19%** — en conjunto, el **88% del costo es E/S**, contra apenas 0,7 s (3%) de lógica de coincidencia propiamente dicha. La consecuencia es directa sobre la estrategia de optimización: **eliminar las 50.000 aperturas de archivo por consulta rinde más que cualquier mejora sobre el algoritmo de matching**, y es exactamente lo que provee el índice invertido al trasladar la lectura del corpus a una fase única de indexación.

Nótese además que la corrida instrumentada tarda **23,1 s frente a 2,5 s sin perfilador** (~9× de sobrecarga, atribuible a los 100.000 eventos de llamada que `cProfile` intercepta). Esto justifica la regla del protocolo: el perfilador sirve para **atribuir** costo, nunca para **cronometrar**.

**Entorno de pruebas**

| Parámetro | Valor |
| :--- | :--- |
| CPU (modelo / núcleos) | Intel Core i5-7267U @ 3,10 GHz — 2 físicos / 4 lógicos |
| Memoria RAM | 8 GB |
| Almacenamiento | SSD |
| Sistema Operativo | macOS 13.7.8 (x86_64) |
| Versión de Python | CPython 3.14.0 (GIL activo) |
| Documentos del corpus | 50.000 archivos `.txt` |
| Tamaño total del corpus | 68,7 MB de contenido — 195 MB ocupados en disco |

---

## Instrucciones de Ejecución

### Requisitos previos

```bash
# Clonar el repositorio y posicionarse en la raíz del proyecto
git clone https://github.com/JoniMora/pef-26.git
cd pef-26

# Crear y activar el entorno virtual
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Instalar las herramientas de perfilado
# (la línea base NO tiene dependencias: usa solo la biblioteca estándar)
pip install snakeviz line_profiler memory_profiler
```

> Los comandos se ejecutan desde cualquier directorio: `src/baseline.py` resuelve la ruta del corpus a partir de la ubicación del script (`<repo>/data/corpus`), no del directorio de trabajo.

### Preparación del corpus

El corpus es **sintético**: se genera localmente con `generar_corpus_prueba()`, no se descarga.

```bash
# Genera 50.000 documentos .txt en <repo>/data/corpus
python3 src/baseline.py --generar --num-docs 50000

# Verificación rápida del corpus generado
find data/corpus -name '*.txt' | wc -l
du -sh data/corpus
```

### Prueba de línea base

```bash
# Consulta sobre el corpus completo; imprime tiempo (ms) y coincidencias
python3 src/baseline.py --query "algoritmo"

# Sobre un corpus en otra ubicación
python3 src/baseline.py --query "algoritmo" --directorio /ruta/al/corpus
```

Salida esperada:

```
Tiempo de ejecucion: 2558.302 ms
Documentos encontrados: 47797
```

### Prueba optimizada

> **Pendiente de implementación.** Los comandos de esta sección quedan definidos como contrato de la interfaz a construir en los incrementos 2 a 4.

```bash
# Versión optimizada, secuencial (índice invertido + heap + caché)
python3 src/optimizado.py --query "algoritmo" --top-k 10

# Versión optimizada con construcción concurrente del índice
python3 src/optimizado.py --query "algoritmo" --top-k 10 --concurrent --workers 4
```

### Comparativa automatizada

> **Pendiente de implementación.** Hasta entonces, la comparativa se reproduce a mano repitiendo la consulta y tomando la mediana en régimen estacionario:

```bash
# 10 corridas de la línea base; descartar las primeras hasta estabilizar el page cache
for i in $(seq 1 10); do python3 src/baseline.py --query "algoritmo"; done
```

El *runner* automatizado ejecutará las cuatro versiones sobre el mismo corpus y set de consultas:

```bash
python3 -m benchmarks.run_all \
    --queries ./benchmarks/queries.txt \
    --repeat 10 \
    --output ./benchmarks/results.md
```

### Perfilado

```bash
# Perfilado de CPU: genera el archivo de estadísticas y lo visualiza
python3 -m cProfile -o ./profiles/baseline.prof src/baseline.py --query "algoritmo"
snakeviz ./profiles/baseline.prof

# Top de funciones por tiempo acumulado, sin salir de la terminal
python3 -c "import pstats; pstats.Stats('./profiles/baseline.prof').sort_stats('cumtime').print_stats(15)"

# Perfilado línea a línea (requiere decorar busqueda_secuencial con @profile)
kernprof -l -v src/baseline.py --query "algoritmo"

# Pico de memoria residente (RSS)
/usr/bin/time -l python3 src/baseline.py --query "algoritmo"     # macOS
/usr/bin/time -v python3 src/baseline.py --query "algoritmo"     # Linux

# Evolución del RSS en el tiempo
mprof run python3 src/baseline.py --query "algoritmo"
mprof plot
```

### Validación de equivalencia

> **Pendiente de implementación.** Requiere unificar previamente la semántica de coincidencia entre ambas versiones (ver la nota de alcance en [Línea Base](#línea-base-baseline)): la línea base matchea por subcadena y el índice invertido lo hará por token.

```bash
# Verificará que la versión optimizada devuelve exactamente los mismos
# resultados que la línea base para todas las consultas del set de pruebas
pytest tests/test_equivalence.py -v
```
