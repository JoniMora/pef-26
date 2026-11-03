# Pruebas

## Estrategia

La suite usa **pytest** y corre en el CI en cada pull request. Genera su propio corpus sintético de 2.000 documentos con semilla fija, en un directorio temporal, así que no necesita `data/corpus`.

| Nivel | Qué cubre | Criterio |
| :--- | :--- | :--- |
| Unitarias | Procesamiento de texto, lectura por bloques, índice, caché y ranking. | Resultado exacto, incluidos los casos borde. |
| Integración | La API con `TestClient`, el índice en disco, la línea de comandos y el generador de carga, sin abrir puertos. | Respuestas y errores documentados. |
| Equivalencia | Que todas las versiones devuelvan los mismos resultados. | Los mismos documentos, no solo la misma cantidad. |
| Rendimiento | La consulta optimizada contra un límite fijo y contra la línea base. | Corre aparte y sin cobertura, porque el *tracing* distorsiona los tiempos. |
| Pipeline | Las reglas del CI, el veredicto de "Resultado final" y los enlaces de la documentación. | Fallan si un cambio deja de cumplir la [matriz de controles](matriz-controles.md). |

`src/perfilado.py` queda fuera de la cobertura: es el arnés de medición, lanza subprocesos y Scalene, y no forma parte del motor. Su refactorización se verificó comparando salidas ([Refactorización](mantenimiento.md#refactorización)).

## Cómo correrlas

```bash
make tests                                # todas, con cobertura mínima del 80 %
make rendimiento                          # Performance Gate
pytest tests/test_api.py -v               # un archivo
CORPUS_DOCS=20000 pytest -m rendimiento --no-cov   # con más volumen
```

## Casos de prueba

| Archivo | Tests | Qué verifica |
| :--- | ---: | :--- |
| [`test_procesamiento_texto.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_procesamiento_texto.py) | 28 | Normalización, tokenización y el *stemmer*: los 16 pares singular/plural documentados en [Normalización](diseno-tecnico.md#normalización-stemming-por-reglas-del-español) y 10 casos borde (invariables, alternancia z/c, `-mente`). |
| [`test_lectura.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_lectura.py) | 21 | Leer por bloques de 1 a 10.000 bytes da los mismos términos que leer el archivo entero, incluidas palabras más largas que el bloque, caracteres partidos entre bloques y archivos vacíos. El índice secuencial y el concurrente salen iguales con bloques de 5 bytes. |
| [`test_optimizado.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_optimizado.py) | 13 | Consulta canónica, índice (incluidos archivos ilegibles y **archivos vacíos de 0 bytes**), caché LRU, la caché con 8 hilos concurrentes, intersección de *postings* y ranking. |
| [`test_concurrente.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_concurrente.py) | 7 | Particionado en lotes, fusión de índices parciales, igualdad entre el índice paralelo y el secuencial, y archivos vacíos. |
| [`test_equivalencia.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_equivalencia.py) | 3 | La línea base y la versión optimizada devuelven **los mismos documentos** para tres consultas cuyo término no cambia con el *stemming*. |
| [`test_indice_en_disco.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_indice_en_disco.py) | 10 | Guardar y cargar da el mismo índice, el pool escribe un archivo por lote, un índice de otro corpus, de un corpus modificado o con un lote dañado se descarta, y un manifiesto alterado no hace leer archivos de fuera del índice. |
| [`test_api.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_api.py) | 9 | Las respuestas y los errores de los endpoints, la reutilización del índice, la reconstrucción cuando cambia el corpus, la carga desde disco al reiniciar y el esquema de Swagger. |
| [`test_cli.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_cli.py) | 10 | Las líneas de comandos de los tres buscadores. |
| [`test_servidor.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_servidor.py) | 8 | Con un agente falso que nunca se conecta: sin licencia no inicia el agente; con licencia lo inicia con el nombre por defecto o el configurado, y define el nombre antes de importarlo; avisa si falta instalarlo; el `.env` se lee sin pisar el entorno, y `main()` levanta uvicorn. |
| [`test_generar_trafico.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_generar_trafico.py) | 9 | Contra la app en el mismo proceso, sin abrir puertos: la cantidad pedida de búsquedas, la mezcla y la semilla reproducibles, las recargas periódicas, los percentiles, y que un servidor caído cuenta como error. |
| [`test_perfilar_api.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_perfilar_api.py) | 4 | La cantidad y la mezcla de búsquedas, que la semilla repite la secuencia, que la recarga reconstruye el índice y que se guarda un perfil legible por `pstats`. |
| [`test_rendimiento.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_rendimiento.py) | 2 | *Performance Gate*: la consulta optimizada responde en menos de 0,5 s y le gana a la línea base. |
| [`test_ci.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_ci.py) | 15 | Todo job se suma a "Resultado final", ningún paso ejecuta un comando sin pasar por `make` y ningún control ignora sus fallos. |
| [`test_resultado_final.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_resultado_final.py) | 9 | "Resultado final" rechaza si un job falló, se canceló o se omitió, y también si no recibe resultados. |
| [`test_docs.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_docs.py) | 24 | Están las 9 secciones de la documentación, los enlaces al repositorio apuntan a archivos que existen y todo módulo y objetivo de `make` está documentado. |

## Validación de equivalencia

> ✅ **Automatizada** en [`tests/`](https://github.com/JoniMora/pef-26/tree/master/tests), sobre un corpus sintético de 2.000 documentos generado con semilla fija (no necesita `data/corpus`):
>
> | Test | Qué verifica |
> | :--- | :--- |
> | `test_equivalencia.py` | La línea base y la versión optimizada devuelven los mismos documentos —no solo la misma cantidad— para `"algoritmo"`, `"indice"` y `"python"`. |
> | `test_concurrente.py::test_indice_paralelo_igual_al_secuencial` | El índice paralelo es idéntico al secuencial: términos, `doc_id` y frecuencias. |

Sobre el corpus completo se verifica a mano, comparando el total de coincidencias que informa cada versión:

```bash
python3 src/baseline.py    --query "algoritmo"                # Documentos encontrados: 47797
python3 src/optimizado.py  --query "algoritmo" --top-k 10     # Documentos encontrados: 47797 (...)
python3 src/concurrente.py --query "algoritmo" --top-k 10     # Documentos encontrados: 47797 (...)
```

`src/perfilado.py` la verifica además sobre **las cinco versiones a la vez**: registra el total de coincidencias de cada una y las cinco devuelven 47.797 sobre el corpus actual, incluida la etapa intermedia con `sorted()`. Es el testigo de que las optimizaciones cambiaron el costo y no el resultado.

La equivalencia **concurrente ↔ optimizado** no depende de esta comparación por totales: `--comparar` verifica la igualdad estructural de los dos índices completos (`indice == indice_secuencial` → `True`), que es una condición estrictamente más fuerte y cubre términos, `doc_id` y frecuencias. La coincidencia está garantizada por diseño —los `doc_id` se asignan en el padre antes de despachar— y se comprueba en cada corrida con `--comparar`.

**Resultado sobre el corpus actual:**

| Consulta | Línea base | Optimizado | ¿Coinciden? |
| :--- | ---: | ---: | :--- |
| `algoritmo` | 47.797 | 47.797 | ✅ |
| `dato` | 49.702 | 49.702 | ✅ |
| `datos` | 47.788 | 49.702 | ❌ **divergencia esperada** |

La divergencia en `"datos"` **no es un defecto**: es la consecuencia visible del *stemming*. La línea base busca la subcadena literal `datos` y encuentra 47.788 documentos; la versión optimizada reduce `datos → dato` y devuelve los 49.702 que contienen cualquiera de las dos formas. Es exactamente el comportamiento que se busca en un motor de recuperación, y la línea base no puede reproducirlo por construcción.

El caso `"dato"` es el complementario e ilustra por qué la comparación cruda es engañosa: ahí **coinciden por accidente**, porque `.find("dato")` matchea también dentro de `datos` y llega al mismo conjunto que el *stemmer*, por un camino distinto.

De esto se sigue el criterio del test automatizado: la equivalencia solo puede exigirse sobre consultas cuyos términos sean **invariantes bajo *stemming***, como `algoritmo`, o bien tokenizando también la línea base con el mismo *pipeline*. Comparar las dos semánticas tal cual están produce falsos negativos.

```bash
pytest tests/test_equivalencia.py -v
```

## Resultados

Última corrida de `make tests` y `make rendimiento`, con Python 3.14:

| Métrica | Resultado |
| :--- | ---: |
| Tests | **170** pasan, ninguno falla |
| Tests de rendimiento | **2** pasan |
| Cobertura | **99,56 %** (mínimo exigido: 80 %) |

El CI vuelve a correr todo en cada pull request. El reporte de cobertura de cada corrida queda como artefacto `cobertura` en GitHub Actions. Además, SonarCloud controla la cobertura del código nuevo.

"Resultado final" se probó en GitHub Actions con 6 corridas en rojo provocadas a propósito en una rama descartable: Ruff, Bandit, pip-audit, un test roto, cobertura por debajo del umbral y una corrida cancelada. Rechazó en las seis, y el log de cada falla provocada mostró el error esperado.
