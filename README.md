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
| **Ranking** | Puntuación TF-IDF de los documentos candidatos y selección del *top-k*. |

El requisito central de la asignatura no es la funcionalidad —ambas versiones deben devolver **resultados idénticos**, lo que se verificará por test de equivalencia—, sino la **evidencia cuantificada de la mejora**. Cada optimización debe estar justificada por su complejidad algorítmica y validada con mediciones reproducibles de tiempo y memoria obtenidas mediante herramientas de perfilado formales.

El proyecto se versiona en cuatro incrementos medibles y comparables entre sí:

1. **Inicial** — búsqueda secuencial sobre el corpus crudo. ✅ [`src/baseline.py`](src/baseline.py)
2. **Estructura Optimizada** — índice invertido con `dict` y `set`. ✅ [`src/optimizado.py`](src/optimizado.py)
3. **Algoritmo Optimizado** — ranking parcial con *heap* y caching de consultas. ✅ [`src/optimizado.py`](src/optimizado.py)
4. **Concurrente** — construcción del índice en paralelo mediante múltiples procesos. ✅ [`src/concurrente.py`](src/concurrente.py)

> Los incrementos 2 y 3 conviven en un mismo script: el índice invertido y el ranking con *heap* + caché se miden por separado (tiempo de indexación vs. tiempo de consulta), no por archivo.
>
> El incremento 4 vive en un script propio: [`src/concurrente.py`](src/concurrente.py) importa el *pipeline* de normalización, consulta y ranking de `optimizado.py` y **solo** reemplaza `construir_indice()`. Así la comparación aísla el efecto del paralelismo: todo lo demás es literalmente el mismo código.

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

> **Alcance actual.** La línea base resuelve **presencia por subcadena**, no relevancia: no tokeniza ni puntúa, y por lo tanto **no produce un ranking *top-k***. Las etapas de Normalización y Ranking descritas en el objetivo se incorporan en la versión optimizada. Esto tiene una consecuencia directa sobre el test de equivalencia: `.find()` sobre el texto crudo hace que `"algo"` matchee dentro de `"algoritmo"`, mientras que un índice invertido sobre tokens no lo haría. Para que la comparación sea válida, **ambas versiones deben acordar la misma semántica de coincidencia**; se adopta la de tokens.
>
> **Estado de la equivalencia.** Sobre la consulta de referencia `"algoritmo"` ambas versiones coinciden exactamente: **47.797 documentos** en las dos. El corpus sintético hace que las dos semánticas converjan, porque su vocabulario de 40 palabras no contiene ningún término que sea subcadena de otro. La divergencia `"algo"` / `"algoritmo"` sigue siendo real y aparecerá en cuanto el corpus incluya prefijos compartidos: la unificación formal de la semántica y el test automatizado siguen pendientes.

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

### Normalización: *stemming* por reglas del español

Antes de indexar, cada token se reduce a una forma canónica para que las variantes de una misma palabra compartan entrada en el índice. El *stemmer* es propio —sin dependencias externas— y opera **invirtiendo la regla de pluralización del español** en lugar de recortar sufijos por longitud:

| Regla | Condición | Ejemplo |
| :--- | :--- | :--- |
| Invariables | termina en `-is` / `-us` | `corpus → corpus`, `analisis → analisis` |
| Alternancia z/c | `-ces` en palabras cortas | `luces → luz`, `veces → vez` |
| Plural sobre consonante | `-es` con consonante final válida (`d l n r z`) **precedida de vocal** | `redes → red`, `vectores → vector`, `funciones → funcion` |
| Plural sobre vocal | `-s` tras vocal | `datos → dato`, `clases → clase`, `indices → indice` |
| Adverbios | `-mente` en palabras largas | `rapidamente → rapida` |

La condición de **vocal previa** en la regla de `-es` es la que evita el error clásico de los *stemmers* ingenuos: `variables` termina en `-les`, igual que `papeles`, pero su raíz es `variab-`, un grupo consonántico que no puede cerrar una palabra en español. Al exigir vocal antes de la consonante final, `papeles → papel` (correcto) y `variables → variable` (correcto), en vez de `variab`.

**Versión anterior — defecto corregido.** El *stemmer* original recortaba sufijos por longitud (`if len(token) > 4`), lo que **separaba** singulares de plurales en lugar de unificarlos:

| Token | *Stemmer* anterior | Actual |
| :--- | :--- | :--- |
| `dato` / `datos` | `dato` / **`dat`** ❌ | `dato` / `dato` ✅ |
| `indice` / `indices` | `indice` / **`indic`** ❌ | `indice` / `indice` ✅ |
| `lista` / `listas` | `lista` / **`list`** ❌ | `lista` / `lista` ✅ |
| `clase` / `clases` | `clase` / **`clas`** ❌ | `clase` / `clase` ✅ |
| `corpus` | **`corpu`** ❌ | `corpus` ✅ |
| `analisis` | **`analisi`** ❌ | `analisis` ✅ |

La causa era el retorno temprano `len(token) <= 4`: protegía los singulares cortos mientras sus plurales, que sí superaban el umbral, quedaban truncados **por debajo** de la forma singular. Consecuencia funcional: una consulta por `"dato"` no devolvía los documentos que contenían `"datos"`.

Validado sobre 16 pares singular/plural (`dato`, `indice`, `lista`, `clase`, `red`, `vector`, `variable`, `funcion`, `metodo`, `papel`, `arbol`, `usuario`, `servidor`, `documento`, `luz`, `vez`): **16/16 unifican** y ninguna palabra invariable se altera. El efecto sobre el corpus es visible en el tamaño del vocabulario indexado, que baja de **40 a 39 términos** por la fusión de `dato` y `datos` en una sola entrada.

> Caso conocido: `tres → tre` (numeral de 4 letras terminado en `-es`). No colisiona con ningún otro término del vocabulario.

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

**2. Resolución de consultas booleanas.** Las *postings lists* se almacenan como `dict[int, int]` (`doc_id -> frecuencia`, necesario para el ranking) y se combinan a través de su vista `.keys()`, que implementa el protocolo de conjunto de CPython. Esto permite aplicar las operaciones nativas —implementadas en C— sin materializar un `set` intermedio por término:

```python
# AND: documentos que contienen todos los términos
candidatos = postings[t0] & postings[t1] & postings[t2]

# OR: documentos que contienen alguno
candidatos = postings[t0] | postings[t1]

# NOT: exclusión de un término
candidatos = postings[t0] - postings[t1]
```

La intersección de `set` en CPython **itera sobre el conjunto más pequeño** y consulta la pertenencia en el mayor, resultando en **O(min(|A|, |B|))** en lugar del producto cartesiano O(|A| · |B|) de una implementación con listas. Se ordenan los términos de la consulta por frecuencia documental ascendente (`postings.sort(key=len)`) antes de intersecar, de modo que el conjunto candidato se reduzca lo antes posible, y se corta el bucle apenas la intersección queda vacía.

Implementado en `buscar()`. La consulta se normaliza **una sola vez** en `Buscador.buscar()` y la tupla de términos se propaga a `buscar()` y `rankear()`; tokenizarla en cada etapa repetía el trabajo tres veces por consulta.

### `heapq` (Heap binario) para el ranking *top-k*

Ordenar completamente el conjunto de candidatos para devolver solo `k` resultados desperdicia trabajo. Se emplea un **min-heap de tamaño acotado `k`**: se recorren los candidatos y se descarta inmediatamente todo documento cuyo score no supere la raíz del heap.

```python
import heapq
top_k = heapq.nlargest(k, candidatos, key=lambda d: scores[d])
```

| Estrategia | Complejidad | Memoria del heap |
| :--- | :--- | :--- |
| `sorted()` completo | O(r · log r) | O(r) |
| **Heap acotado** | **O(r · log k)** | **O(k)** |

Con `r = 47.797` candidatos y `k = 10`, `log₂(r) ≈ 15,5` frente a `log₂(k) ≈ 3,3`: una reducción teórica de ~4,7× en las comparaciones del ranking.

**La cota O(k) es real, no nominal.** Una primera implementación materializaba un `dict scores` con los `r` candidatos antes de llamar a `nlargest`, de modo que el pico efectivo era O(r) y la cota O(k) aplicaba solo al *heap*. `rankear()` evalúa ahora el score **al vuelo** dentro de un generador, y `heapq.nlargest` mantiene únicamente `k` elementos vivos:

```python
def puntuados():
    for doc_id in candidatos:
        score = 0.0
        for postings, idf in pesos:
            score += postings.get(doc_id, 0) * idf
        yield (score, -doc_id)

return [
    (-doc_id_invertido, score)
    for score, doc_id_invertido in heapq.nlargest(k, puntuados())
]
```

Verificado con `tracemalloc` sobre un índice sintético de **200.000 candidatos**, midiendo solo la memoria auxiliar de `rankear()`:

| `k` | Pico auxiliar | Proporción respecto de `r` |
| ---: | ---: | :--- |
| 10 | **2.832 B** | 0,0014 % |
| 100 | **22.736 B** | 0,011 % |

El pico escala con `k` y es indiferente a `r`: multiplicar `k` por 10 multiplica la memoria por 8, mientras que `r` (200.000 documentos) no aparece en el consumo. El `dict scores` equivalente habría costado del orden de **10 MB**.

> **El `doc_id` se emite negado** (`-doc_id`) para que el desempate entre scores iguales sea determinista y favorezca al documento más antiguo, en lugar de depender del orden de iteración del `set`.

### Ponderación TF-IDF

El score no es la frecuencia cruda del término (TF), que favorece mecánicamente a los documentos largos, sino **TF-IDF**: la frecuencia del término en el documento ponderada por su rareza en el corpus.

```python
idf = math.log(total_docs / df)      # df = len(indice[termino])
score += tf * idf
```

El **IDF se calcula una sola vez por término**, fuera del bucle de candidatos: `df` es la longitud de la *postings list*, un `len()` en O(1) sobre el `dict` que ya está indexado. Un término presente en casi todo el corpus tiende a `log(1) = 0` y deja de aportar señal; uno raro domina el ranking. Es la propiedad que hace útil el ranking sobre lenguaje natural, donde la distribución de términos es fuertemente asimétrica.

Sobre el corpus sintético el efecto es deliberadamente pequeño —las 40 palabras del vocabulario están distribuidas de forma casi uniforme, así que todos los IDF son similares— pero el orden de los resultados no cambia respecto de TF cruda y los scores pasan a ser comparables entre consultas, que es lo que TF no permite.

### Resumen comparativo

| Aspecto | Línea Base | Optimizado |
| :--- | :--- | :--- |
| Acceso a documentos | Escaneo lineal O(n · m) | Hash lookup O(1) promedio |
| Combinación de términos | Recorrido anidado | `set` intersection O(min(\|A\|,\|B\|)) |
| Ranking | `sorted()` O(r · log r) | Heap acotado O(r · log k) |
| Lecturas de disco | En cada consulta | Una única vez, en indexación |
| Costo de indexación | Ninguno | O(N) tokens, amortizado |
| Memoria auxiliar del ranking | — | **O(k)** — generador + heap acotado |
| Ponderación | Ninguna (presencia) | TF-IDF |
| Coincidencia | Subcadena cruda | Token normalizado con *stemming*|

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
clave = (normalizar_consulta(consulta), top_k)
# normalizar_consulta -> tuple(sorted(set(tokens)))
```

Con esto, `"Programación Eficiente"`, `"eficiente programación"` y `"  PROGRAMACION   eficiente "` colapsan en la misma entrada. La tupla ordenada de términos únicos es hashable e insensible al orden —igual que un `frozenset`, pero además determinista al imprimirla—, e implica que la caché es correcta bajo semántica booleana conmutativa. El `modo_booleano` no forma parte de la clave porque la implementación actual solo resuelve **AND**; debe incorporarse al agregar OR/NOT, o las dos semánticas colisionarían en la misma entrada.

**Eficacia medida del nivel 1.** Sobre la indexación completa del corpus, `normalize()` y `stem()` registran **8.771.763 aciertos contra 41 fallos** cada una (`cache_info()`), es decir un **99,9995 % de tasa de aciertos**: el vocabulario sintético tiene 40 términos, de modo que cada función se ejecuta realmente una vez por término y el resto son lecturas de tabla. En un corpus de lenguaje natural el vocabulario es mucho mayor y `maxsize=10000` pasaría a ser el parámetro determinante.

### Política de invalidación

La caché de consultas se invalida por **versionado del índice** (*generation counter*), evitando el costo de rastrear dependencias inversas término→consulta:

| Evento | Acción | Estado |
| :--- | :--- | :--- |
| Presión de memoria | Expulsión LRU al alcanzar `maxsize` (por defecto **1024** entradas, configurable vía `--cache-size`). | ✅ Implementado |
| Reconstrucción total del índice | El índice se construye en memoria al arrancar el proceso y muere con él: no hay estado que invalidar entre corridas. | ✅ Trivial por diseño |
| Alta / baja / modificación de documento | Invalidación selectiva de las entradas cuya clave interseca los términos del documento afectado; `mtime` y tamaño como testigo de cambio. | ⏳ Pendiente |
| TTL vencido | Expiración por `monotonic()` para corpus dinámicos (`--cache-ttl`). | ⏳ Pendiente |

Esta política es **conservadora**: ante la duda, se invalida. Un fallo de caché cuesta una consulta indexada —del orden de milisegundos—, mientras que un acierto obsoleto devuelve un resultado incorrecto.

> **Limitación del *harness* actual.** El CLI construye el índice, resuelve **una** consulta y termina, por lo que la caché de consultas siempre reporta `{'hits': 0, 'misses': 1}`. Su efecto solo se observa dentro de un mismo proceso: reutilizando el objeto `Buscador`, la consulta `"algoritmo"` baja de **9,06 ms** (fallo) a **0,0020 ms** (acierto) — un factor de **~4.600×**. Para que la caché sea demostrable desde la línea de comandos hace falta un modo interactivo o por lotes (`--queries archivo.txt`), pendiente junto con el *runner* de benchmarks.

---

## Concurrencia y Paralelismo

> ✅ **Incremento 4 — implementado** en [`src/concurrente.py`](src/concurrente.py) (`--workers`, `--comparar`).

El cuello de botella de la versión optimizada se desplaza de la consulta a la **construcción del índice**: 8,6 s frente a los ~9 ms de una consulta. Ese costo es perfectamente descomponible por documento, y medido en régimen estacionario se reparte así:

| Fase de la indexación | Tiempo (ms) | Proporción | ¿Paraleliza? |
| :--- | ---: | ---: | :--- |
| Lectura + decodificación de 50.000 archivos | 2.234 | 26,3 % | Sí, por solapamiento de E/S |
| Tokenización + *stopwords* + *stemming* | 4.616 | 54,4 % | Sí, es CPU pura |
| Conteo (`Counter`) + construcción de *postings* | 1.628 | 19,2 % | Sí en el *Map*; la fusión final no |
| **Total** | **8.478** | **100 %** | |

> **Techo realista.** El reparto real invierte la expectativa inicial: con el corpus residente en *page cache* la E/S es solo un cuarto del costo y la **CPU domina con ~74 %**. Aplicando la ley de Amdahl sobre esa fracción con 2 núcleos físicos, el techo es `1 / (0,263 + 0,737/2) ≈ 1,58×`. La medición confirma la cota: **1,84×** con `P = 4`, algo por encima del cálculo porque la E/S también se solapa entre procesos y el *Hyper-Threading* aporta un margen residual.

### Justificación de la técnica: procesos, no hilos

En el build utilizado (CPython 3.14.0, con **GIL activo** — verificado con `sys._is_gil_enabled()`) el **GIL** (*Global Interpreter Lock*) serializa la ejecución de bytecode: los hilos de `threading` no producen paralelismo real en cargas *CPU-bound*. Como la tokenización y el *stemming* son operaciones de CPU sobre estructuras Python, la técnica correcta es el **paralelismo por múltiples procesos**, donde cada intérprete posee su propio GIL y se aprovechan todos los núcleos físicos.

```python
from concurrent.futures import ProcessPoolExecutor
```

Se elige `concurrent.futures.ProcessPoolExecutor` sobre `multiprocessing.Pool` por su API de `Future`, su propagación limpia de excepciones desde los procesos hijos y su integración con `as_completed()` para el reporte de progreso incremental.

**No se usa `threading` en ninguna fase**, tampoco para la lectura. El diseño previo reservaba un `ThreadPoolExecutor` para la E/S, y se descartó: cada worker ya abre sus propios archivos, de modo que las lecturas se solapan entre procesos sin agregar una segunda capa de planificación. La medición respalda la decisión — la lectura es el 26 % del costo y la tokenización el 54 %, así que el trabajo que un pool de hilos podría ganar es minoritario y ya está cubierto.

### Arquitectura: MapReduce sobre particiones del corpus

```
                          ┌─ Worker 1 ─> parcial ─┐
   Corpus  ──> P · 4 lotes ├─ Worker 2 ─> parcial ─┤ as_completed ──> Índice global
   (n docs)    equitativos └─ Worker P ─> parcial ─┘   (_fusionar)

   50.000 docs  ──>  16 lotes de 3.125  ──>  4 procesos  ──>  1 dict
```

| Fase | Función | Operación | Complejidad |
| :--- | :--- | :--- | :--- |
| **Particionado** | `_lotes_equitativos()` | División de la lista de documentos en `P · 4` lotes contiguos de tamaño equitativo. | O(n) |
| **Map** (paralelo) | `_procesar_lote()` | Cada worker lee sus archivos, tokeniza y construye un índice invertido parcial. | O(N / P) |
| **Reduce** | `_fusionar()` | Volcado de cada parcial sobre el índice global, en orden de finalización. | O(V · P · 4), `V` = vocabulario |

La fase *Map* no comparte estado mutable entre procesos: cada worker opera sobre un subconjunto disjunto de archivos y devuelve una estructura independiente. Al no existir escritura concurrente, **no se requieren locks**, eliminando la contención y las condiciones de carrera por construcción.

El determinismo no depende del orden de llegada: los `doc_id` se asignan en el proceso padre sobre la lista ya ordenada, antes de despachar, de modo que `as_completed()` puede fusionar en cualquier orden y el índice resultante es **idéntico bit a bit** al secuencial (verificado con `--comparar`).

### Decisiones de implementación

- **Granularidad por lotes, no por documento.** La comunicación entre procesos exige serialización con `pickle`; despachar un archivo por tarea haría que el costo de IPC dominara sobre el trabajo útil. Se agrupan los documentos en `P · 4` lotes equitativos (`LOTES_POR_PROCESO = 4`). La medición justifica la escala: un lote de 1/16 del corpus cuesta **487 ms** de trabajo útil, tres órdenes de magnitud por encima del costo de despachar la tarea.
- **Más lotes que workers.** Con `K = 4` hay 16 tareas para 4 procesos, así el pool **reequilibra** cuando un lote resulta más pesado que otro. Con exactamente `P` lotes, el worker más lento fija el tiempo total.
- **`doc_id` asignado en el padre.** El worker recibe pares `(doc_id, ruta)` ya numerados sobre la lista ordenada. Es lo que permite fusionar por `as_completed()` —en orden de finalización, no de despacho— sin perder determinismo.
- **Fusión sin sumar frecuencias.** Como los lotes son disjuntos, ningún `doc_id` se repite entre parciales: `_fusionar()` hace `dict.update()` y adopta por referencia el primer diccionario de *postings* de cada término, sin copiarlo.
- **Payload de retorno compacto.** Los workers devuelven las *postings* con `doc_id` enteros y no cadenas de texto; las rutas viajan de ida como `str` y no como `Path`, que se serializa más caro.
- **Umbral de paralelismo.** Por debajo de `UMBRAL_PARALELO = 512` documentos —o con `P = 1`— se ejecuta el *Map* en el propio proceso: levantar el pool y serializar los parciales costaría más que el trabajo ahorrado.
- **`spawn` como método de arranque.** En macOS el método por defecto es `spawn`: cada proceso hijo reimporta el módulo principal, por lo que todo el código de arranque queda protegido bajo `if __name__ == "__main__":`. Sin esta guarda, el programa entra en recursión infinita de procesos.
- **Grado de paralelismo.** `P = os.cpu_count()` por defecto, ajustable con `--workers`. En la máquina de pruebas `os.cpu_count()` devuelve **4** (lógicos) sobre solo **2 núcleos físicos**; se midieron ambos valores y el resultado confirma la sospecha: pasar de `P = 2` a `P = 4` solo aporta un **11 %** adicional, porque el *Hyper-Threading* no agrega unidades de ejecución reales para una carga CPU-bound.

### Resultados de la paralelización

Mediana de 6 corridas por configuración sobre 50.000 documentos, **alternando** las versiones dentro de cada ronda y descartando 2 rondas de calentamiento:

| Configuración | Mediana (ms) | min / max | *Speedup* | Eficiencia |
| :--- | ---: | ---: | ---: | :--- |
| Secuencial (`optimizado.py`) | 8.607 | 8.477 / 8.667 | 1,00× | — |
| `--workers 2` | 5.189 | 5.104 / 5.269 | **1,66×** | 83 % sobre 2 núcleos físicos |
| `--workers 4` | 4.689 | 4.660 / 4.759 | **1,84×** | 92 % sobre físicos — 46 % sobre lógicos |

La varianza es inferior al 3 % en las tres configuraciones. El resultado valida la predicción del diseño: pasar de `P = 2` a `P = 4` mejora el *speedup* solo un **11 %** (1,66× → 1,84×), porque los 4 procesadores lógicos son 2 núcleos físicos con *Hyper-Threading* y la carga es CPU-bound.

**Conservación del trabajo.** Un lote aislado (1/16 del corpus) cuesta 487 ms; los 16 lotes suman 7.792 ms, el **92 %** del costo secuencial de 8.478 ms. El 8 % restante es el arranque del pool, la serialización de los parciales y la fusión: el paralelismo no crea trabajo nuevo de forma significativa.

**Advertencia metodológica: el *page cache* cambia el resultado por un factor de 3.**

| Régimen | Secuencial | `--workers 4` | *Speedup* observado |
| :--- | ---: | ---: | ---: |
| Frío (corpus fuera de *page cache*) | 27.608–34.151 ms | 5.051–7.229 ms | **≈5,6×** |
| Estacionario (corpus residente) | 8.607 ms | 4.689 ms | **1,84×** |

La primera tanda de mediciones se tomó en bloques —10 corridas secuenciales, después 10 paralelas— y arrojó un *speedup* de **5,63×** sobre una máquina de 2 núcleos físicos. Un resultado superlineal es la señal de que se está midiendo otra cosa: el bloque secuencial corrió con el corpus fuera de caché y el paralelo, ya caliente.

El mecanismo es la **latencia de E/S por archivo**, no la CPU. Leer los 50.000 archivos en frío, sin tokenizar nada, cuesta **18.193 ms** —0,36 ms por archivo— contra 2.234 ms en caliente. Un solo proceso paga esa latencia en serie; cuatro procesos emiten lecturas simultáneas y la ocultan. La aceleración en frío es real y es un beneficio genuino del diseño, pero **no es *speedup* de paralelización de CPU** y reportarla como tal sería engañoso. De ahí que el protocolo pase a alternar las versiones dentro de cada ronda.

**Hipótesis descartada.** Se sospechó del *garbage collector*: un proceso secuencial que acumula ~2 millones de entradas podría estar pagando barridos generacionales que los workers, con 1/16 de los datos, evitan. Se midió con `gc.disable()` y la diferencia es de **0,4 %** (8.478 ms contra 8.447 ms). El GC no participa del efecto.

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
- **Orden de las corridas:** las versiones se miden **alternadas** dentro de cada ronda (secuencial → `P = 4` → `P = 2` → repetir), nunca en bloques. Medirlas en bloque produjo un *speedup* aparente de 5,63× que era un artefacto del *page cache*; ver [Resultados de la paralelización](#resultados-de-la-paralelización).
- **Aislamiento:** las mediciones de tiempo se toman **sin** el perfilador activo, dado que `cProfile` introduce sobrecarga; el perfilador se usa para atribuir costo, no para cronometrar.
- **Métricas separadas:** se registran por separado el **tiempo de construcción del índice** (costo único) y el **tiempo de consulta** (costo recurrente).

### Resultados

Consulta de referencia: `"algoritmo"` sobre 50.000 documentos (47.797 coincidencias).

| Versión | Tiempo por consulta (ms) | Costo único de indexación (ms) | Pico de memoria (MB) | Observaciones |
| :--- | ---: | ---: | ---: | :--- |
| Inicial (Baseline) | **2.485** | — | 18,3 | Mediana de 10 corridas en régimen estacionario (min 2.408 / max 2.569, ±3 %). Con *page cache* frío: **10.795–14.040 ms**. Lectura completa del corpus en cada consulta; sin ranking. |
| Estructura + Algoritmo Optimizado | **9,06** | 8.607 | 177,7 | Mediana de 10 consultas con caché forzada a fallo. Índice invertido + intersección de `set` + ranking TF-IDF en O(k) con `heapq.nlargest`. |
| ↳ *con acierto de caché* | **0,0020** | — | — | Misma consulta repetida sobre el mismo proceso (`QueryCache`). |
| Concurrente (`P = 4`) | *sin cambio* | **4.689** | 323,6 | MapReduce con `ProcessPoolExecutor` sobre 16 lotes. Solo cambia la indexación: la consulta usa el mismo `Buscador`, de modo que su tiempo es el de la fila anterior por construcción. |

> **Corrección respecto de la medición previa.** El costo de indexación de la versión optimizada figuraba como **33.225 ms**. Ese valor corresponde al **régimen frío**, no al estacionario que el protocolo exige: remedido con el corpus residente en *page cache* son **8.607 ms**. La cifra vieja no era incorrecta como observación, pero estaba mal etiquetada, y comparar contra ella habría inflado el *speedup* del incremento 4 de 1,84× a 5,6×.

**Lectura de los resultados**

| Comparación | Factor |
| :--- | ---: |
| Consulta indexada vs. línea base | **274×** más rápida (2.485 → 9,06 ms) |
| Consulta cacheada vs. línea base | **≈1.264.000×** más rápida (2.485 → 0,0020 ms) |
| Costo de memoria | **9,7×** más (18,3 → 177,7 MB) |
| Indexación paralela vs. secuencial | **1,84×** más rápida (8.607 → 4.689 ms), a costa de **1,8×** de memoria (177,7 → 323,6 MB) |

El intercambio es explícito y es el punto central del trabajo: **se compra tiempo con memoria y con un costo único de arranque.** La indexación cuesta 8,6 s en régimen estacionario, y cada consulta ahorra 2.476 ms respecto de la línea base: el **punto de equilibrio está en ~4 consultas** (8.607 / 2.476). Con la indexación paralela baja a **~2** (4.689 / 2.476). Por debajo de eso la línea base gana; por encima, la diferencia crece sin cota. Para un motor de búsqueda —donde el índice se construye una vez y se consulta indefinidamente— el intercambio es favorable por varios órdenes de magnitud.

**Efecto del ranking en O(k).** Reescribir `rankear()` para puntuar al vuelo no solo acotó la memoria: también resultó **más rápido** que la versión con `dict scores`. La primera implementación en O(k) usaba un generador anidado por candidato (`sum(... for ... in pesos)`) y costaba 29,5 ms; desdoblarlo en un bucle explícito con atajo para el caso de un solo término lo llevó a 7,6 ms sobre el mismo índice.

| Implementación de `rankear` | Memoria auxiliar | Tiempo (1 término) | Tiempo (4 términos) |
| :--- | :--- | ---: | ---: |
| `dict scores` + `nlargest(key=...)` | O(r) | 11,86 ms | 24,43 ms |
| Generador anidado + `nlargest` | O(k) | 29,53 ms | 38,91 ms |
| **Bucle explícito + `nlargest`** | **O(k)** | **7,60 ms** | **22,07 ms** |

La lección es que la cota de memoria y la velocidad no estaban en conflicto: el costo de la versión intermedia no venía del *streaming* sino de crear ~48.000 objetos generador, uno por candidato.

**Escalado con la cantidad de términos** (consultas con fallo de caché, mediana de 10):

| Consulta | Términos | Coincidencias | Tiempo (ms) |
| :--- | ---: | ---: | ---: |
| `algoritmo` | 1 | 47.797 | 9,06 |
| `algoritmo estructura` | 2 | 45.892 | 17,45 |
| `algoritmo estructura datos python` | 4 | 44.107 | 28,51 |
| `xyzinexistente` | 1 | 0 | **0,003** |

El crecimiento es lineal en la cantidad de términos, no en el tamaño del corpus. El último caso es el más ilustrativo: un término ausente del índice se resuelve con un fallo de `dict` y retorno inmediato en **3 microsegundos**, mientras que la línea base necesita leer los 50.000 archivos —**2.485 ms**— para llegar a la misma conclusión. Es un factor de **~800.000×** sobre el peor caso relativo de la implementación ingenua.

**Cómo se obtuvieron los valores**

- **Tiempo (línea base):** `time.perf_counter()` alrededor de `busqueda_secuencial()`, 10 repeticiones tras estabilizar el *page cache*; se reporta la mediana.
- **Tiempo (optimizado):** índice construido una sola vez; luego 10 repeticiones por consulta reinicializando `QueryCache` antes de cada una para forzar el fallo y medir el costo real de resolución. La fila de acierto se mide sobre 1.000 repeticiones consecutivas sin reinicializar.
- **Memoria (línea base):** pico de *resident set size* vía `/usr/bin/time -l` (19.165.184 bytes = 18,3 MB). El bajo consumo es consistente con el análisis O(m): mantiene un solo documento en memoria por vez, a costa de releer todo el corpus.
- **Memoria (concurrente):** pico de RSS vía `/usr/bin/time -l` (339.337.216 bytes = **323,6 MB**). El sobrecosto de 1,8× no es el índice —que es el mismo objeto que en la versión secuencial— sino los **parciales en vuelo**: mientras el padre fusiona, conviven el índice global ya poblado y los índices parciales todavía no liberados, sumado al espacio propio de cada intérprete hijo. Es el precio de memoria del paralelismo y escala con `P`, no con el corpus.
- **Memoria (optimizado):** pico de RSS vía `/usr/bin/time -l` (186.318.848 bytes = 177,7 MB). De ese total, `tracemalloc` atribuye **132,2 MB al índice invertido en sí**; el resto corresponde al intérprete, a la lista de 50.000 objetos `Path` y a los picos transitorios de decodificación. La memoria auxiliar del ranking no participa de este pico: es O(k), del orden de los kilobytes.

> La consulta de 4 términos pasó de 42.787 a **44.107** coincidencias respecto de la medición anterior. No es ruido: al corregirse el *stemmer*, `datos` dejó de indexarse como `dat` y se fusionó con `dato` (df = 49.702), de modo que la intersección AND ahora incluye los documentos que solo contenían la forma singular.

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

### *Hotspots* de la versión optimizada

Perfilado de la fase de indexación (`cProfile` sobre un lote de 5.000 documentos, ordenado por tiempo propio):

```
   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
     5000    1.810    0.000    1.865    0.000 {method 'read' of '_io.TextIOWrapper'}
     5000    0.633    0.000    1.162    0.000 src/optimizado.py:102(tokenizar)
     5000    0.522    0.000    0.547    0.000 {built-in method _io.open}
     5000    0.318    0.000    0.318    0.000 {method 'findall' of 're.Pattern'}
   883159    0.159    0.000    0.159    0.000 {method 'append' of 'list'}
```

El diagnóstico es el mismo que en la línea base —**`read()` + `open()` concentran el 61 % del tiempo**— pero con una diferencia decisiva: **ahora ese costo se paga una sola vez**, no en cada consulta. Es exactamente la inversión de costo que motivaba el índice invertido.

La lógica propia (`tokenizar`, 1,16 s acumulados) es el único candidato real a paralelización por CPU, y las dos funciones memoizadas ya no aparecen en el perfil: con 8,77 millones de aciertos de `lru_cache` contra 41 fallos, su costo neto es el de una consulta de tabla hash. Reescribir el *stemmer* no movió este perfil: las reglas nuevas son más numerosas pero se ejecutan 41 veces en total, una por término distinto. Medido aisladamente y sin perfilador, tokenizar el corpus completo cuesta **4,6 s**, contra **2,2 s de E/S** con el corpus residente en *page cache* (18,2 s en frío). El diagnóstico inicial de este perfil —que la E/S era la porción mayor y acotaría el paralelismo— se invierte en régimen estacionario: **la CPU es el 74 % del costo**, y por eso la paralelización por procesos rinde lo que rinde. Ver [Concurrencia y Paralelismo](#concurrencia-y-paralelismo).

### Defectos corregidos

Los tres defectos de diseño algorítmico detectados en la revisión fueron corregidos y verificados:

| Defecto | Diagnóstico | Corrección | Verificación |
| :--- | :--- | :--- | :--- |
| **Falsa complejidad espacial O(k)** | `rankear()` materializaba un `dict scores` de tamaño O(r) antes de `heapq.nlargest`. La cota O(k) aplicaba al *heap*, no a la consulta. | Los scores se evalúan al vuelo en un generador; `nlargest` mantiene solo `k` elementos. | `tracemalloc` con r = 200.000: **2.832 B** para k = 10, **22.736 B** para k = 100. Escala con `k`, no con `r`. |
| **Contradicción de ponderación** | El código sumaba TF cruda mientras la arquitectura declaraba TF-IDF, favoreciendo a los documentos largos. | `score += tf * idf` con `idf = math.log(total_docs / df)`; el IDF se precalcula una vez por término. | Orden del *top-10* sin cambios sobre el corpus sintético (IDF casi uniforme), scores ahora comparables entre consultas. |
| **_Stemmer_ roto** | Recortaba sufijos por longitud y **separaba** singular de plural: `dato` / `dat`, `indice` / `indic`, `corpus` / `corpu`. | Reglas que invierten la pluralización del español, con la condición de vocal previa en `-es`. | **16/16** pares singular/plural unifican; invariables intactas. Vocabulario del corpus: 40 → **39** términos. |

Los tres cambios se aplicaron sin alterar el resultado de la consulta de referencia: `"algoritmo"` sigue devolviendo **47.797** coincidencias, idénticas a la línea base.

### Defectos abiertos

| Defecto | Evidencia | Impacto |
| :--- | :--- | :--- |
| El *stemmer* no cubre la alternancia z/c en palabras largas | `matrices → matrice`, no `matriz` | Pérdida de fusión, no corrupción: la regla `-ces → z` se restringe a palabras de hasta 5 letras porque `indices → indiz` sería peor. Desambiguar exige un lexicón. |
| `tres → tre` | Numeral de 4 letras terminado en `-es` | Nulo sobre este corpus: no colisiona con ningún término del vocabulario. |
| La caché de consultas no es observable desde el CLI | `{'hits': 0, 'misses': 1}` en toda corrida | Requiere modo interactivo o por lotes. Ver [Caching Inteligente](#caching-inteligente). |
| Sin invalidación selectiva ni TTL | `QueryCache` solo implementa expulsión LRU | Irrelevante con índice en memoria y corpus estático; necesario para corpus dinámico. |

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

> Los comandos se ejecutan desde cualquier directorio: los tres scripts resuelven la ruta del corpus a partir de la ubicación del propio archivo (`<repo>/data/corpus`), no del directorio de trabajo.

### Preparación del corpus

El corpus es **sintético**: se genera localmente con `generar_corpus_prueba()`, no se descarga.

La generación vive únicamente en `src/baseline.py`; `src/optimizado.py` y `src/concurrente.py` solo consumen el corpus ya generado.

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

```
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
> La caché siempre reporta `misses: 1` porque el proceso resuelve una sola consulta y termina (ver la limitación del *harness* en [Caching Inteligente](#caching-inteligente)).

### Prueba concurrente

```bash
# Indexación MapReduce con ProcessPoolExecutor; P = os.cpu_count() por defecto
python3 src/concurrente.py --query "algoritmo" --top-k 10

# Grado de paralelismo explícito
python3 src/concurrente.py --query "algoritmo" --top-k 10 --workers 4

# Contrasta la indexación paralela contra la secuencial en una sola corrida
python3 src/concurrente.py --workers 4 --comparar
```

Salida esperada:

```
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

```
Índice secuencial: 8701.79 ms
Speedup: 1.86x
Índices idénticos: True
```

> `Índices idénticos: True` compara los dos diccionarios completos, no un resumen: términos, `doc_id` y frecuencias. Es la verificación de equivalencia del incremento 4.
>
> El `--comparar` construye el índice **dos veces** en el mismo proceso, así que su tiempo total es la suma de ambas rutas. Para cronometrar, usar las corridas por separado.

### Comparativa automatizada

> **Parcialmente implementada.** `src/concurrente.py --comparar` ya contrasta la indexación paralela contra la secuencial en una corrida —tiempo, *speedup* e identidad del índice—, pero construye ambos índices en el mismo proceso y no promedia repeticiones. El *runner* que barra las cuatro versiones sobre un set de consultas sigue pendiente. Hasta entonces, la comparativa se reproduce a mano tomando la mediana en régimen estacionario:

```bash
# 10 corridas de la línea base; descartar las primeras hasta estabilizar el page cache
for i in $(seq 1 10); do python3 src/baseline.py --query "algoritmo"; done

# 10 corridas de la versión optimizada
# (cada corrida reconstruye el índice: separar los dos tiempos que imprime)
for i in $(seq 1 10); do python3 src/optimizado.py --query "algoritmo" --top-k 10; done

# Indexación secuencial vs. paralela: ALTERNADAS dentro de cada ronda, nunca
# en bloques —medirlas en bloque contamina el resultado con el page cache—.
# Se descartan las 2 primeras rondas y se toma la mediana del resto.
for i in $(seq 1 8); do
    python3 src/optimizado.py             | grep construcción
    python3 src/concurrente.py --workers 4 | grep construcción
    python3 src/concurrente.py --workers 2 | grep construcción
done
```

Para medir el tiempo de consulta sin repetir la indexación —que es como se obtuvieron las cifras de la tabla— hay que reutilizar el índice dentro de un mismo proceso:

```bash
python3 - <<'EOF'
import sys, time, statistics
sys.path.insert(0, "src")
from pathlib import Path
import optimizado as o

indice, archivos = o.construir_indice(Path("data/corpus"))
buscador = o.Buscador(indice, archivos)

tiempos = []
for _ in range(10):
    buscador.cache = o.QueryCache(1024)          # forzar fallo de caché
    inicio = time.perf_counter()
    total, resultados = buscador.buscar("algoritmo", 10)
    tiempos.append((time.perf_counter() - inicio) * 1000)

print("mediana:", round(statistics.median(tiempos), 3), "ms —", total, "coincidencias")
EOF
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
python3 -m cProfile -o ./profiles/optimizado.prof src/optimizado.py --query "algoritmo"
snakeviz ./profiles/baseline.prof

# Top de funciones por tiempo acumulado, sin salir de la terminal
python3 -c "import pstats; pstats.Stats('./profiles/baseline.prof').sort_stats('cumtime').print_stats(15)"

# Perfilado línea a línea (requiere decorar busqueda_secuencial con @profile)
kernprof -l -v src/baseline.py --query "algoritmo"

# Pico de memoria residente (RSS)
/usr/bin/time -l python3 src/baseline.py --query "algoritmo"     # macOS
/usr/bin/time -l python3 src/optimizado.py --query "algoritmo"   # macOS
/usr/bin/time -v python3 src/baseline.py --query "algoritmo"     # Linux

# Memoria atribuible al índice invertido, aislada del resto del proceso
python3 -c "
import sys, tracemalloc; sys.path.insert(0,'src')
from pathlib import Path; import optimizado as o
tracemalloc.start()
indice, archivos = o.construir_indice(Path('data/corpus'))
actual, pico = tracemalloc.get_traced_memory()
print(f'indice={actual/1e6:.1f} MB  pico={pico/1e6:.1f} MB')
"

# Evolución del RSS en el tiempo
mprof run python3 src/baseline.py --query "algoritmo"
mprof plot
```

### Validación de equivalencia

> **Test automatizado pendiente.** La equivalencia se verifica hoy a mano, comparando el total de coincidencias que informa cada versión:

```bash
python3 src/baseline.py    --query "algoritmo"                # Documentos encontrados: 47797
python3 src/optimizado.py  --query "algoritmo" --top-k 10     # Documentos encontrados: 47797 (...)
python3 src/concurrente.py --query "algoritmo" --top-k 10     # Documentos encontrados: 47797 (...)
```

La equivalencia **concurrente ↔ optimizado** no depende de esta comparación por totales: `--comparar` verifica la igualdad estructural de los dos índices completos (`indice == indice_secuencial` → `True`), que es una condición estrictamente más fuerte y cubre términos, `doc_id` y frecuencias. La coincidencia está garantizada por diseño —los `doc_id` se asignan en el padre antes de despachar— y se comprueba en cada corrida con `--comparar`.

**Resultado sobre el corpus actual:**

| Consulta | Línea base | Optimizado | ¿Coinciden? |
| :--- | ---: | ---: | :--- |
| `algoritmo` | 47.797 | 47.797 | ✅ |
| `dato` | 49.702 | 49.702 | ✅ |
| `datos` | 47.788 | 49.702 | ❌ **divergencia esperada** |

La divergencia en `"datos"` **no es un defecto**: es la consecuencia visible del *stemming*. La línea base busca la subcadena literal `datos` y encuentra 47.788 documentos; la versión optimizada reduce `datos → dato` y devuelve los 49.702 que contienen cualquiera de las dos formas. Es exactamente el comportamiento que se busca en un motor de recuperación, y la línea base no puede reproducirlo por construcción.

El caso `"dato"` es el complementario e ilustra por qué la comparación cruda es engañosa: ahí **coinciden por accidente**, porque `.find("dato")` matchea también dentro de `datos` y llega al mismo conjunto que el *stemmer*, por un camino distinto.

De esto se sigue el criterio para el test automatizado: la equivalencia solo puede exigirse sobre consultas cuyos términos sean **invariantes bajo *stemming*** (como `algoritmo`), o bien tokenizando también la línea base con el mismo *pipeline*. Comparar las dos semánticas tal cual están produce falsos negativos.

```bash
# Verificará que la versión optimizada devuelve exactamente los mismos
# resultados que la línea base para todas las consultas del set de pruebas
pytest tests/test_equivalence.py -v
```
