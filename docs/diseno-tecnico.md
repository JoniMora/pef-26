# Diseño técnico

Estructuras de datos, algoritmos y decisiones de implementación de cada versión, con la medición que justifica cada una. Las cifras completas están en [Rendimiento](rendimiento.md).

## Línea Base (Baseline)

La primera implementación resuelve la consulta por **fuerza bruta**, sin ninguna estructura de indexación previa. Es intencionalmente ingenua: su función es establecer el punto de referencia contra el cual se miden todas las optimizaciones posteriores.

**Algoritmo:**

```text
para cada archivo .txt del directorio:
    abrir el archivo y leer TODO su contenido en memoria (.read())
    convertir el contenido completo a minúsculas (.lower())
    si la query aparece como subcadena (.find() != -1):
        acumular el nombre del archivo en una lista
devolver la lista de coincidencias
```

Implementado en [`src/baseline.py`](https://github.com/JoniMora/pef-26/blob/master/src/baseline.py) (`busqueda_secuencial`). Sin índices, `dict` de caché, `set`, generadores ni concurrencia: la ineficiencia es deliberada.

> **Alcance actual.** La línea base resuelve **presencia por subcadena**, no relevancia: no tokeniza ni puntúa, y por lo tanto **no produce un ranking *top-k***. Las etapas de Normalización y Ranking descritas en el objetivo se incorporan en la versión optimizada. Esto tiene una consecuencia directa sobre el test de equivalencia: `.find()` sobre el texto crudo hace que `"algo"` matchee dentro de `"algoritmo"`, mientras que un índice invertido sobre tokens no lo haría. Para que la comparación sea válida, **ambas versiones deben acordar la misma semántica de coincidencia**; se adopta la de tokens.
>
> **Estado de la equivalencia.** Sobre la consulta de referencia `"algoritmo"` ambas versiones coinciden exactamente: **47.797 documentos** en las dos. El corpus sintético hace que las dos semánticas converjan, porque su vocabulario de 40 palabras no contiene ningún término que sea subcadena de otro. La divergencia `"algo"` / `"algoritmo"` sigue siendo real y aparecerá en cuanto el corpus incluya prefijos compartidos: la unificación formal de la semántica sigue pendiente. El test automatizado ya existe: [`tests/test_equivalencia.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_equivalencia.py) verifica que las dos versiones devuelvan los mismos documentos (ver [Validación de equivalencia](pruebas.md#validación-de-equivalencia)).

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
    for score, doc_id_invertido in heapq.nlargest(top_k, puntuados())
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
idf = math.log(total_docs / df)  # df = len(indice[termino])
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
| Coincidencia | Subcadena cruda | Token normalizado con *stemming* |

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
| Reconstrucción total del índice | En la línea de comandos, el índice se construye al arrancar y muere con el proceso. En la API, cada reconstrucción crea un `Buscador` nuevo, con su caché vacía. | ✅ Implementado |
| Alta / baja / modificación de documento | Invalidación selectiva de las entradas cuya clave interseca los términos del documento afectado; `mtime` y tamaño como testigo de cambio. | ⏳ Pendiente |
| TTL vencido | Expiración por `monotonic()` para corpus dinámicos (`--cache-ttl`). | ⏳ Pendiente |

Esta política es **conservadora**: ante la duda, se invalida. Un fallo de caché cuesta una consulta indexada —del orden de milisegundos—, mientras que un acierto obsoleto devuelve un resultado incorrecto.

> **Limitación del *harness* actual.** El CLI construye el índice, resuelve **una** consulta y termina, por lo que la caché de consultas siempre reporta `{'hits': 0, 'misses': 1}`. Su efecto solo se observa dentro de un mismo proceso: reutilizando el objeto `Buscador`, la consulta `"algoritmo"` baja de **9,06 ms** (fallo) a **0,0020 ms** (acierto) — un factor de **~4.600×**. Para que la caché sea demostrable desde la línea de comandos hace falta un modo interactivo o por lotes (`--queries archivo.txt`), pendiente.

## Concurrencia y Paralelismo

> ✅ **Incremento 4 — implementado** en [`src/concurrente.py`](https://github.com/JoniMora/pef-26/blob/master/src/concurrente.py) (`--workers`, `--comparar`).

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

```text
                          ┌─ Worker 1 ─> parcial ─┐
   Corpus  ──> P · 4 lotes ├─ Worker 2 ─> parcial ─┤ as_completed ──> Índice global
   (n docs)    equitativos └─ Worker P ─> parcial ─┘   (fusionar)

   50.000 docs  ──>  16 lotes de 3.125  ──>  4 procesos  ──>  1 dict
```

| Fase | Función | Operación | Complejidad |
| :--- | :--- | :--- | :--- |
| **Particionado** | `_lotes_equitativos()` | División de la lista de documentos en `P · 4` lotes contiguos de tamaño equitativo. | O(n) |
| **Map** (paralelo) | `_procesar_lote()` | Cada worker lee sus archivos, tokeniza y construye un índice invertido parcial. | O(N / P) |
| **Reduce** | `fusionar()` | Volcado de cada parcial sobre el índice global, en orden de finalización. | O(V · P · 4), `V` = vocabulario |

La fase *Map* no comparte estado mutable entre procesos: cada worker opera sobre un subconjunto disjunto de archivos y devuelve una estructura independiente. Al no existir escritura concurrente, **no se requieren locks**, eliminando la contención y las condiciones de carrera por construcción.

El determinismo no depende del orden de llegada: los `doc_id` se asignan en el proceso padre sobre la lista ya ordenada, antes de despachar, de modo que `as_completed()` puede fusionar en cualquier orden y el índice resultante es **idéntico bit a bit** al secuencial (verificado con `--comparar`).

### Decisiones de implementación

- **Granularidad por lotes, no por documento.** La comunicación entre procesos exige serialización con `pickle`; despachar un archivo por tarea haría que el costo de IPC dominara sobre el trabajo útil. Se agrupan los documentos en `P · 4` lotes equitativos (`LOTES_POR_PROCESO = 4`). La medición justifica la escala: un lote de 1/16 del corpus cuesta **487 ms** de trabajo útil, tres órdenes de magnitud por encima del costo de despachar la tarea.
- **Más lotes que workers.** Con `K = 4` hay 16 tareas para 4 procesos, así el pool **reequilibra** cuando un lote resulta más pesado que otro. Con exactamente `P` lotes, el worker más lento fija el tiempo total.
- **`doc_id` asignado en el padre.** El worker recibe pares `(doc_id, ruta)` ya numerados sobre la lista ordenada. Es lo que permite fusionar por `as_completed()` —en orden de finalización, no de despacho— sin perder determinismo.
- **Fusión sin sumar frecuencias.** Como los lotes son disjuntos, ningún `doc_id` se repite entre parciales: `fusionar()` hace `dict.update()` y adopta por referencia el primer diccionario de *postings* de cada término, sin copiarlo.
- **Payload de retorno compacto.** Los workers devuelven las *postings* con `doc_id` enteros y no cadenas de texto; las rutas viajan de ida como `str` y no como `Path`, que se serializa más caro.
- **Umbral de paralelismo.** Por debajo de `UMBRAL_PARALELO = 512` documentos —o con `P = 1`— se ejecuta el *Map* en el propio proceso: levantar el pool y serializar los parciales costaría más que el trabajo ahorrado.
- **`spawn` como método de arranque.** En macOS el método por defecto es `spawn`: cada proceso hijo reimporta el módulo principal, por lo que todo el código de arranque queda protegido bajo `if __name__ == "__main__":`. Sin esta guarda, el programa entra en recursión infinita de procesos.
- **Grado de paralelismo.** `P = os.cpu_count()` por defecto, ajustable con `--workers`. En la máquina de pruebas `os.cpu_count()` devuelve **4** (lógicos) sobre solo **2 núcleos físicos**; se midieron ambos valores y el resultado confirma la sospecha: pasar de `P = 2` a `P = 4` solo aporta un **11 %** adicional, porque el *Hyper-Threading* no agrega unidades de ejecución reales para una carga CPU-bound.

Los resultados de esta decisión están en [Resultados de la paralelización](rendimiento.md#resultados-de-la-paralelización).

## Lectura por bloques

La línea base sigue leyendo cada archivo entero con `read()`, a propósito: es la versión ingenua contra la que se compara. La versión optimizada y la concurrente leen ahora con [`src/core/lectura.py`](https://github.com/JoniMora/pef-26/blob/master/src/core/lectura.py), de a **bloques de 64 KiB**, y cuentan los términos a medida que leen. Así la memoria queda acotada por el bloque y no por el tamaño del archivo.

Un bloque puede cortar dos cosas, y las dos se resuelven:

- **Un carácter de varios bytes** (`á`, `ñ`): el decodificador incremental de UTF-8 lo completa con el bloque siguiente.
- **Una palabra:** cada bloque se procesa hasta su último espacio, y lo que queda se antepone al bloque siguiente.

Con un archivo de 21 MB, el pico de memoria baja de **279 MB a 1,1 MB**, con el mismo conteo de términos y un tiempo similar (5,5 s y 5,0 s). Sobre el corpus completo, el índice que resulta es idéntico al de antes: 39 términos y 1.865.501 *postings*.

> La primera versión de este punto pasaba `buffering=1 MiB` a `open()`, pero seguía leyendo cada archivo entero con `read()`. Un buffer cambia cómo se hacen las lecturas al sistema operativo, no cuánto texto se carga en memoria.

## Índice en disco por lotes

Construir el índice de 50.000 documentos lleva varios segundos. [`src/indice_en_disco.py`](https://github.com/JoniMora/pef-26/blob/master/src/indice_en_disco.py) lo guarda en disco para no repetirlo cada vez que arranca la API, y aprovecha el MapReduce de la versión concurrente: **cada lote se escribe en su propio archivo apenas termina**, mientras los demás se siguen procesando.

```text
data/indice_corpus/
├── manifiesto.json    corpus, firma (fecha del directorio y cantidad de documentos) y lotes
├── lote_000.json      término -> [doc_ids, frecuencias]
└── ...                un archivo por lote (16 con 4 procesos)
```

El manifiesto se escribe al final y de forma atómica, y guarda los lotes por número, no por nombre de archivo: SonarCloud detectó (regla S2083) que, con nombres, un manifiesto alterado podía hacer leer archivos de fuera del índice, y un test lo reproduce. Al cargar, se descarta el índice guardado si es de otro corpus o de otro formato, si el corpus cambió o si algún lote está dañado, y en ese caso se reconstruye. Por defecto se guarda en un directorio hermano del corpus (`data/indice_corpus`, que git ignora), configurable con `BUSCADOR_INDICE`. No puede ir adentro del corpus, porque escribir ahí cambiaría su fecha.

El índice guardado lo usa la API. `optimizado.py` y `concurrente.py` siguen construyendo el índice en cada corrida, a propósito: se usan para medir cuánto cuesta la indexación.

El formato se eligió midiendo los 16 lotes del corpus completo:

| Formato | Escribir | Cargar y fusionar | Tamaño |
| :--- | ---: | ---: | ---: |
| **JSON** (elegido) | 0,32 s | 0,69 s | 14,6 MB |
| pickle | 0,13 s | 0,49 s | 9,3 MB |
| SQLite | 2,24 s | 2,02 s | 38,5 MB |

JSON carga 0,2 s más lento que pickle, pero leerlo no puede ejecutar código (cargar un pickle sí puede) y se puede inspeccionar a mano.

## Decisiones de la API

- **El índice se prepara una vez y se reutiliza.** La clase `ServicioDeBusqueda` lo carga o lo construye en la primera consulta. Un `Lock` evita que dos consultas simultáneas lo construyan a la vez.
- **Saber si el corpus cambió cuesta una sola consulta al disco.** La primera versión revisaba nombre, fecha y tamaño de cada archivo en cada pedido: 100.000 `stat()` con el corpus completo, que costaban 1,6 s por consulta. Ahora mira solo la fecha de modificación del directorio, que cambia cuando se agregan, borran o renombran archivos. Si cambia el contenido de un archivo existente, la fecha no se entera: para eso está `POST /reindexar`.
- **La caché de consultas es segura entre hilos.** FastAPI atiende consultas en paralelo, y un test con 8 hilos mostró que sin un bloqueo un hilo podía desalojar una consulta mientras otro la estaba leyendo (`KeyError`, que en la API es un error 500). `QueryCache` ahora usa un `Lock`.

## Defectos corregidos

Los tres defectos de diseño algorítmico detectados en la revisión fueron corregidos y verificados:

| Defecto | Diagnóstico | Corrección | Verificación |
| :--- | :--- | :--- | :--- |
| **Falsa complejidad espacial O(k)** | `rankear()` materializaba un `dict scores` de tamaño O(r) antes de `heapq.nlargest`. La cota O(k) aplicaba al *heap*, no a la consulta. | Los scores se evalúan al vuelo en un generador; `nlargest` mantiene solo `k` elementos. | `tracemalloc` con r = 200.000: **2.832 B** para k = 10, **22.736 B** para k = 100. Escala con `k`, no con `r`. |
| **Contradicción de ponderación** | El código sumaba TF cruda mientras la arquitectura declaraba TF-IDF, favoreciendo a los documentos largos. | `score += tf * idf` con `idf = math.log(total_docs / df)`; el IDF se precalcula una vez por término. | Orden del *top-10* sin cambios sobre el corpus sintético (IDF casi uniforme), scores ahora comparables entre consultas. |
| ***Stemmer* roto** | Recortaba sufijos por longitud y **separaba** singular de plural: `dato` / `dat`, `indice` / `indic`, `corpus` / `corpu`. | Reglas que invierten la pluralización del español, con la condición de vocal previa en `-es`. | **16/16** pares singular/plural unifican; invariables intactas. Vocabulario del corpus: 40 → **39** términos. |

Los tres cambios se aplicaron sin alterar el resultado de la consulta de referencia: `"algoritmo"` sigue devolviendo **47.797** coincidencias, idénticas a la línea base.

## Defectos abiertos

| Defecto | Evidencia | Impacto |
| :--- | :--- | :--- |
| El *stemmer* no cubre la alternancia z/c en palabras largas | `matrices → matrice`, no `matriz` | Pérdida de fusión, no corrupción: la regla `-ces → z` se restringe a palabras de hasta 5 letras porque `indices → indiz` sería peor. Desambiguar exige un lexicón. |
| `tres → tre` | Numeral de 4 letras terminado en `-es` | Nulo sobre este corpus: no colisiona con ningún término del vocabulario. |
| La caché de consultas no es observable desde el CLI | `{'hits': 0, 'misses': 1}` en toda corrida | Requiere modo interactivo o por lotes. Ver [Caching Inteligente](#caching-inteligente). |
| Sin invalidación selectiva ni TTL | `QueryCache` solo implementa expulsión LRU | Irrelevante con índice en memoria y corpus estático; necesario para corpus dinámico. |
| El corpus se genera sin semilla fija | Dos equipos con `--num-docs 50000` obtuvieron 47.797 y 47.753 coincidencias para la misma consulta | No afecta las comparaciones de **tiempo** —mismo generador, tamaño y distribución— pero impide comparar resultados documento a documento entre máquinas. Se resuelve con un `--seed` que alimente `random.seed()`. |
