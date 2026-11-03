# Descripción funcional

## Problema

Buscar un término en una colección grande de documentos recorriéndolos uno por uno obliga a leer todo el corpus en cada consulta. Con 50.000 documentos, una búsqueda secuencial tarda unos 2,5 s, y el 88 % de ese tiempo es lectura de disco ([Hotspots de la línea base](rendimiento.md#hotspots-de-la-línea-base)).

El sistema es un motor de búsqueda local (*full-text*) sobre documentos de texto plano. Dada una consulta de uno o más términos, devuelve los `k` documentos más relevantes de un corpus de escala no trivial (corpus de prueba actual: **50.000 documentos sintéticos / 68,7 MB de texto**).

El objetivo del proyecto no es solo que funcione: también debe demostrar con mediciones reproducibles cuánto mejora una implementación optimizada frente a una secuencial ingenua, justificando cada optimización por su complejidad algorítmica. Todas las versiones deben devolver **los mismos resultados**.

## Etapas del sistema

| Etapa | Responsabilidad |
| :--- | :--- |
| **Ingesta** | Lectura y decodificación de los documentos del corpus desde disco. |
| **Normalización** | Tokenización, *casefolding*, remoción de puntuación, filtrado de *stopwords* y *stemming*. |
| **Indexación / Búsqueda** | Resolución de los términos de la consulta contra la estructura de datos de acceso. |
| **Ranking** | Puntuación TF-IDF de los documentos candidatos y selección del *top-k*. |

## Versiones

El proyecto se versiona en incrementos medibles y comparables entre sí:

| Versión | Qué agrega | Dónde |
| :--- | :--- | :--- |
| **Inicial** | Búsqueda secuencial sobre el corpus crudo. Es la línea base contra la que se mide todo lo demás. | [`src/baseline.py`](https://github.com/JoniMora/pef-26/blob/master/src/baseline.py) |
| **Estructura optimizada** | Índice invertido con `dict` y `set`. | [`src/optimizado.py`](https://github.com/JoniMora/pef-26/blob/master/src/optimizado.py) |
| **Algoritmo optimizado** | Ranking parcial con *heap* y caché de consultas. | [`src/optimizado.py`](https://github.com/JoniMora/pef-26/blob/master/src/optimizado.py) |
| **Concurrente** | Construcción del índice en paralelo con varios procesos. | [`src/concurrente.py`](https://github.com/JoniMora/pef-26/blob/master/src/concurrente.py) |
| **API web** | El motor como servicio HTTP, con el índice guardado en disco. | [`src/api.py`](https://github.com/JoniMora/pef-26/blob/master/src/api.py) |

La estructura y el algoritmo conviven en un mismo script: el índice invertido y el ranking con *heap* y caché se miden por separado (tiempo de indexación contra tiempo de consulta), no por archivo. La versión concurrente importa el *pipeline* de normalización, consulta y ranking de `optimizado.py` y **solo** reemplaza `construir_indice()`, así la comparación aísla el efecto del paralelismo. El perfilado y la medición son transversales a todas las versiones y viven en `src/perfilado.py`.

## Alcance

**Incluye:**

- Generar un corpus sintético y buscar en él desde la línea de comandos o por HTTP.
- Consultas de uno o más términos en español, combinados con AND.
- Indexar en un proceso o en varios, y guardar el índice en disco para reutilizarlo.
- Medir y perfilar cada versión, y monitorear la API con New Relic de forma opcional.

**No incluye:**

- Consultas con OR o NOT: la implementación solo resuelve AND.
- Otros formatos: solo se indexan archivos `.txt` en UTF-8.
- Invalidación selectiva de la caché ni TTL. Son innecesarios con un corpus estático, y figuran como [defectos abiertos](diseno-tecnico.md#defectos-abiertos).
- Autenticación ni límites de uso en la API: está pensada para uso local ([Seguridad](seguridad.md#riesgos-identificados)).
- Despliegue distribuido: el índice vive en la memoria de un solo proceso.

## Requisitos funcionales

| ID | Requisito | Se verifica en |
| :--- | :--- | :--- |
| RF1 | Generar un corpus sintético de tamaño configurable. | [`test_cli.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_cli.py) |
| RF2 | Devolver los documentos que contienen todos los términos de la consulta. | [`test_optimizado.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_optimizado.py), [`test_api.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_api.py) |
| RF3 | Unificar variantes de una palabra: mayúsculas, puntuación, *stopwords* y plurales del español. | [`test_procesamiento_texto.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_procesamiento_texto.py) |
| RF4 | Ordenar los resultados por TF-IDF, con desempate determinista, y devolver solo los `k` mejores. | [`test_optimizado.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_optimizado.py) |
| RF5 | Informar el total de coincidencias por separado del tamaño de la página. | [`test_api.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_api.py), [`test_cli.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_cli.py) |
| RF6 | Reutilizar el resultado de una consulta equivalente, sin importar el orden de los términos. | [`test_optimizado.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_optimizado.py) |
| RF7 | Exponer la búsqueda y la reconstrucción del índice por HTTP, con errores documentados. | [`test_api.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_api.py) |
| RF8 | Guardar el índice en disco, cargarlo al arrancar y descartarlo si el corpus cambió o está dañado. | [`test_indice_en_disco.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_indice_en_disco.py) |
| RF9 | Activar el monitoreo con New Relic solo si hay licencia; sin ella, la API arranca igual. | [`test_servidor.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_servidor.py) |

## Requisitos no funcionales

| ID | Requisito | Se verifica en |
| :--- | :--- | :--- |
| RNF1 | La línea base y la versión optimizada devuelven los mismos documentos para consultas invariantes bajo *stemming*. | [`test_equivalencia.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_equivalencia.py) |
| RNF2 | El índice paralelo es idéntico al secuencial. | [`test_concurrente.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_concurrente.py) |
| RNF3 | Una consulta optimizada responde en menos de 0,5 s y le gana a la línea base. | [`test_rendimiento.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_rendimiento.py) |
| RNF4 | La memoria de lectura depende del tamaño del bloque, no del archivo. | [`test_lectura.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_lectura.py), [Lectura por bloques](diseno-tecnico.md#lectura-por-bloques) |
| RNF5 | La caché de consultas es segura entre hilos. | [`test_optimizado.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_optimizado.py) |
| RNF6 | Toda mejora se respalda con mediciones reproducibles. | [Rendimiento](rendimiento.md) |
| RNF7 | El motor no tiene dependencias externas: usa solo la biblioteca estándar. | [Arquitectura](arquitectura.md#dependencias-externas) |
| RNF8 | Soporta Python 3.11 o superior. | `target-version` de Ruff en [`pyproject.toml`](https://github.com/JoniMora/pef-26/blob/master/pyproject.toml) |
| RNF9 | Ningún cambio se integra si incumple los controles de calidad. | [Matriz de controles](matriz-controles.md) |
