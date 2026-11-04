# Mantenimiento

Cómo contribuir, cómo correr en local los mismos controles que el CI y cómo resolver un fallo del pipeline.

## Cómo contribuir

1. **Crear una rama** desde `master` actualizado: `feature/<tema>`.
2. **Hacer commits en español**, con prefijo convencional (`feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `style`, `build`, `ci`, `chore`) y un cuerpo que explique por qué. Un cambio por commit.
3. **Correr `make controles`** antes de subir los cambios.
4. **Abrir un pull request** hacia `master`, con un título que describa el cambio y estas secciones: Resumen, Qué cambia, Verificación y Para revisar.
5. **Actualizar la documentación** en el mismo pull request. Si cambia un control, también la [matriz de controles](matriz-controles.md).
6. **Integrar con el check "Resultado final" en verde.**

## Ejecutar los controles en local

Con el entorno virtual activado, estos son los mismos comandos que corre el CI: [`ci.yml`](https://github.com/JoniMora/pef-26/blob/master/.github/workflows/ci.yml) solo llama a objetivos del [`Makefile`](https://github.com/JoniMora/pef-26/blob/master/Makefile), y `tests/test_ci.py` lo verifica.

```bash
make instalar      # herramientas del pipeline, en las versiones del CI
make lint          # Ruff: PEP 8, pyflakes, nombres, docstrings, complejidad y formato
make complejidad   # Lizard: funciones de hasta 50 líneas de código y complejidad 15; reporte en reportes/
make tipado        # mypy sobre core/, optimizado.py y api.py; reporte en reportes/
make lock          # regenera los requirements*.txt, con hashes, a partir de los .in
make seguridad     # Bandit, pip-audit sobre todos los locks y npm audit; reportes en reportes/
make secretos      # gitleaks sobre todo el historial; baja la versión fijada y verifica su hash
make tests         # tests con cobertura mínima del 80 %; reportes en htmlcov/ y reportes/
make rendimiento   # Performance Gate; reporte en reportes/
make benchmark     # tiempos contra BENCHMARK_BASE (por defecto, origin/master); reporte en reportes/
make profiling     # perfil por función y por línea; reportes en reportes/profiling/
make memoria       # pico de memoria de cada versión contra su límite; reporte en reportes/
make docs          # sitio con Sphinx, sin advertencias, y markdownlint
make enlaces       # enlaces externos; informa, pero no bloquea el CI
make diagrama      # regenera el diagrama de arquitectura; requiere Graphviz
make controles     # todos los anteriores, salvo instalar, lock, enlaces y diagrama
```

`make resultado-final` lo corre solo el CI: decide a partir de los resultados de los demás jobs, y sin ellos rechaza. SonarCloud también corre solo en el CI, porque necesita el token del proyecto.

> Los tests generan su propio corpus en un directorio temporal, así que no necesitan `data/corpus`. `ruff format .` (sin `--check`) aplica el formato en lugar de solo verificarlo.

## Pipeline de CI

Corre en cada pull request y en cada push a `master`. Los jobs de lint, complejidad, tipado, seguridad, secretos y documentación corren en paralelo, y los tests solo si pasan todos menos el de documentación, y las mediciones de rendimiento, que son las más costosas, solo si pasan los tests.

| Job | Qué hace |
| :--- | :--- |
| Lint (Ruff) | `make lint`. |
| Complejidad (Lizard) | `make complejidad`, y guarda la tabla de todas las funciones como artefacto. |
| Tipado (mypy) | `make tipado`, y guarda el reporte como artefacto. |
| Seguridad (Bandit, pip-audit y npm audit) | `make seguridad`, y guarda los reportes en JSON como artefacto. |
| Secretos (gitleaks) | `make secretos` sobre todo el historial, y guarda el reporte, con los valores ocultos, como artefacto. |
| Documentación (Sphinx y enlaces) | `make docs`, guarda el sitio como artefacto y `make enlaces`, que informa sin bloquear. |
| Tests, cobertura y Performance Gate | `make tests`, guarda la cobertura como artefacto, envía el análisis a SonarCloud, corre `make rendimiento` y guarda los reportes de las pruebas como artefacto. Los pull requests de Dependabot omiten SonarCloud, porque no reciben su token y no tocan el código que analiza. |
| Rendimiento (benchmark, profiling y memoria) | Solo si pasan los tests: `make benchmark`, `make profiling` y `make memoria`, y guarda los reportes como artefacto. |
| Resultado final | Rechaza el cambio si algún job anterior no terminó bien, y deja la tabla de controles en el resumen de la corrida. |
| Publicar la documentación | Solo en `master` y si "Resultado final" aprueba: publica el sitio en GitHub Pages. |

Los criterios de rechazo de cada control están en la [matriz de controles](matriz-controles.md).

## Resolver fallos del pipeline

Primero hay que ver qué falló: la tabla de "Resultado final" nombra los jobs que rechazaron, y con [GitHub CLI](https://cli.github.com/) se puede leer el log sin abrir el navegador.

```bash
gh run view <id-de-la-corrida> --log-failed
gh run download <id-de-la-corrida> -n cobertura
```

| Falla en | Se reproduce con | Qué hacer |
| :--- | :--- | :--- |
| `ruff check` | `make lint` | Corregir el hallazgo; `ruff check . --fix` resuelve los automáticos. Si es C901, extraer funciones hasta bajar de 10. |
| `ruff format --check` | `make lint` | Correr `ruff format .`. |
| Lizard | `make complejidad` | Dividir la función: en el mensaje, `NLOC` son las líneas de código y `CCN` la complejidad. Si mide tiempos, leer antes [cómo se dividió el arnés](#división-de-las-funciones-largas). |
| mypy | `make tipado` | Corregir el tipo. En `core/`, `optimizado.py` y `api.py`, toda función anota sus parámetros y su retorno. |
| Bandit | `make seguridad` | Corregir el código. Si es un falso positivo, marcarlo con `# nosec <regla>` y agregarlo a [Falsos positivos y excepciones](seguridad.md#falsos-positivos-y-excepciones). |
| pip-audit | `make seguridad` | Subir la versión en el `.in` que corresponda y correr `make lock`. Si viene de una dependencia transitiva, `make lock` no la sube sola: fijarla en el `.in`. Sin versión corregida, registrar una excepción con `--ignore-vuln` en el `Makefile`, con su motivo. |
| `npm audit` | `make seguridad` | Subir la versión en `package.json` o forzarla con `overrides`, regenerar el lock con `npm install --package-lock-only` y comprobar que `make docs` siga funcionando. |
| gitleaks | `make secretos` | Si es un secreto real, **revocarlo primero**: borrarlo del código no alcanza, porque sigue en el historial. Si es un falso positivo, agregar su huella a `.gitleaksignore` y a [Falsos positivos y excepciones](seguridad.md#falsos-positivos-y-excepciones). |
| `make instalar`, hashes | `make instalar` | Un hash que no coincide indica un archivo alterado o un lock viejo. Regenerar con `make lock`; si sigue fallando, investigar antes de instalar. |
| Tests | `make tests` | `pytest <archivo>::<test> -x` para aislar la falla. Si pasa en local, revisar si depende del orden o de la velocidad. |
| Cobertura | `make tests` | Ver qué líneas faltan en la salida o en `htmlcov/index.html`, que en el CI es el artefacto `cobertura`. |
| SonarCloud | Solo en el CI | Abrir el [panel](https://sonarcloud.io/dashboard?id=JoniMora_pef-26) y corregir lo que tiró el quality gate. Si el error es de autenticación, revisar el secreto `SONAR_TOKEN`. |
| Performance Gate | `make rendimiento` | Una regresión real se confirma con `CORPUS_DOCS=20000 pytest -m rendimiento --no-cov`. Perfilar con [estos comandos](rendimiento.md#cómo-reproducir-las-mediciones). |
| Benchmark | `make benchmark` | Mirar qué operación rechazó en el resumen de la corrida y abrir su perfil en el artefacto `rendimiento`. El control ya repitió la medición antes de rechazar, así que relanzar el job no es la primera respuesta: una regresión real vuelve a rechazar. En local, `make benchmark BENCHMARK_BASE=<rama>` repite la comparación. Si la mejora de otra parte justifica la regresión, hay que explicarlo en el pull request. Si la rama base no puede correr la suite, ver los [límites del control](rendimiento.md#benchmark). |
| Profiling | `make profiling` | El error dice qué versión falló. Suele ser un cambio en `medir_version()` o en los perfiladores de `src/perfilado.py`. |
| Memoria | `make memoria` | `memoria.json` lista las líneas que retienen más memoria. Corregir el aumento o, si tiene un motivo válido, subir `LIMITES_MB` en `scripts/control_rendimiento.py` y actualizar la [tabla de límites](rendimiento.md#memoria). |
| Sphinx | `make docs` | Corregir la advertencia que imprime. Un enlace interno roto aparece como `myst.xref_missing`; un docstring mal formado, con la ruta del módulo. |
| markdownlint | `make docs` | `npx markdownlint-cli2 --fix README.md "docs/**/*.md" "#docs/_build"` resuelve los automáticos. La configuración está en [`.markdownlint-cli2.jsonc`](https://github.com/JoniMora/pef-26/blob/master/.markdownlint-cli2.jsonc). |
| Enlaces externos | `make enlaces` | No bloquea. Revisar el artefacto `enlaces` y corregir el enlace si el problema no es una caída temporal del sitio. |
| `tests/test_ci.py` | `pytest tests/test_ci.py` | Sumar el job nuevo a los `needs` de "Resultado final", o mover el comando suelto a un objetivo del `Makefile`. |
| `tests/test_docs.py` | `pytest tests/test_docs.py` | Corregir el enlace al repositorio, o documentar el módulo o el objetivo nuevo. |
| `tests/test_dependencias.py` | `pytest tests/test_dependencias.py` | Casi siempre falta `make lock` después de editar un `.in`. |
| markdownlint, `Invalid regular expression flags` | `node --version` | `markdownlint-cli2` requiere Node.js 22 o superior. |
| Resultado final, sin otro job en rojo | `gh run view <id-de-la-corrida>` | Un job omitido o cancelado también rechaza: volver a correr la corrida. |

## Actualizar dependencias

Las versiones se editan en los `requirements*.in`, y `make lock` genera los `requirements*.txt` con `uv pip compile`: fijan también las dependencias transitivas, con sus hashes, para Linux, macOS y Windows. Los `.txt` no se editan a mano. En Node.js pasa lo mismo con `package.json` y `package-lock.json`.

Dependabot revisa cada semana Python, Node.js y las acciones de GitHub, y abre un pull request con el `.in` y su `.txt` ya regenerados. Pasa por los mismos controles que cualquier otro cambio, salvo SonarCloud. `make lock` conserva lo que ya está fijado: no sube versiones por su cuenta.

gitleaks es un binario, no un paquete de Python: para actualizarlo hay que cambiar `GITLEAKS_VERSION` en el `Makefile` y copiar a `scripts/gitleaks.sha256` los hashes de esa versión, desde el archivo `checksums` de su publicación en GitHub.

## Agregar un control

1. Definirlo en la [matriz de controles](matriz-controles.md): herramienta, comando, reporte y criterio de rechazo.
2. Agregar el objetivo en el [`Makefile`](https://github.com/JoniMora/pef-26/blob/master/Makefile) y su versión fijada en `requirements-dev.in`, y correr `make lock`.
3. Llamarlo desde [`ci.yml`](https://github.com/JoniMora/pef-26/blob/master/.github/workflows/ci.yml). Si es un job nuevo, sumarlo a los `needs` de "Resultado final".
4. Documentar en esta página cómo correrlo y cómo resolver sus fallos, y comprobar que rechaza provocando la falla.

## Documentación

El sitio se genera con Sphinx desde [`docs/`](https://github.com/JoniMora/pef-26/tree/master/docs): las secciones en Markdown, con MyST, y la referencia de funciones desde los docstrings, con `sphinx.ext.autodoc`. Al integrar en `master`, el CI lo publica en GitHub Pages.

```bash
make docs                              # genera el sitio en docs/_build/html
open docs/_build/html/index.html       # Linux: xdg-open

# Solo si se agrega un módulo nuevo a src/: crea su página en docs/api/
# (no pisa las existentes) y después hay que sumarla a docs/api/modules.rst
sphinx-apidoc -o docs/api src
```

## Formato y estilo (PEP 8)

[Ruff](https://docs.astral.sh/ruff/) cumple dos funciones, configuradas en [`pyproject.toml`](https://github.com/JoniMora/pef-26/blob/master/pyproject.toml):

| Comando | Qué controla |
| :--- | :--- |
| `ruff format` | Formato PEP 8: indentación, espacios, comillas dobles y largo de línea de 88 caracteres. |
| `ruff check` | Reglas `E` y `W` (PEP 8), `F` (pyflakes: imports y variables sin usar), `N` (nombres PEP 8) `D` (docstrings, convención PEP 257) y `C901` (complejidad). Los tests están exentos de docstrings. |

`target-version` es `py311`, la versión mínima que soporta el proyecto, y no la del CI. Así el formateador no introduce sintaxis exclusiva de versiones más nuevas: con `py314` había reescrito dos `except (A, B):` como `except A, B:` (PEP 758), que en Python 3.11–3.13 es un error de sintaxis. Con `py311`, `ruff check` rechaza esa forma.

**Nombres.** No quedan variables de una sola letra en el código ni en los tests. En el motor, `i` pasó a `numero_doc` en `generar_corpus_prueba()`, y `k` pasó a `top_k` en `rankear()`, el mismo nombre que ya usaba `Buscador.buscar()`. En `perfilado.py`, las variables de las comprensiones pasaron a nombres que dicen qué contienen (`medicion`, `tamano`, `version`, `cabecera`, `estadistica`…); se verificó que los 10 gráficos y el reporte salen idénticos byte a byte.

## Docstrings

Todas las funciones y clases de `src/` documentan qué hacen, sus parámetros y su retorno en **reStructuredText**, el formato que `sphinx.ext.autodoc` interpreta sin extensiones adicionales. Incluye las funciones internas del MapReduce de `concurrente.py` y las del arnés de medición:

```python
def buscar(indice, terminos):
    """
    Busca los documentos que contienen todos los términos de la consulta.

    :param indice: Índice invertido: término -> {doc_id: frecuencia}.
    :type indice: dict[str, dict[int, int]]
    :param terminos: Términos normalizados de la consulta.
    :type terminos: tuple[str, ...]
    :return: Identificadores de los documentos que contienen todos los
        términos. Vacío si la consulta no tiene términos o si alguno no
        figura en el índice.
    :rtype: set[int]
    """
```

## Tipado

mypy verifica `core/`, `optimizado.py` y `api.py`, con `disallow_untyped_defs`: toda función de esos módulos anota sus parámetros y su retorno. Es el código que resuelve las consultas; el arnés de medición y las herramientas de carga quedan afuera. De `indice_en_disco.py` se anotan las dos funciones que llama la API, para que los tipos lleguen sin cortarse hasta `Buscador`.

Las anotaciones no cambian la medición: comparadas contra el mismo código sin anotar, con el método de la [división de las funciones largas](#división-de-las-funciones-largas), sobre 5.000 documentos y con Python 3.14, no hay diferencias sistemáticas.

## Análisis estático con SonarCloud

SonarCloud analiza cada pull request desde el CI, junto con la cobertura que genera `pytest-cov`. Según [`sonar-project.properties`](https://github.com/JoniMora/pef-26/blob/master/sonar-project.properties), analiza `src/` como código y `tests/` como tests. `src/perfilado.py` se analiza como el resto, pero queda fuera de la cobertura porque es el arnés de medición y no el motor. Panel del proyecto: <https://sonarcloud.io/dashboard?id=JoniMora_pef-26>.

| Métrica | Resultado |
| :--- | :--- |
| Líneas de código analizadas | 2.052 |
| Quality gate | Aprobado |
| Fiabilidad, seguridad y mantenibilidad | A, A, A |
| Bugs / vulnerabilidades / *code smells* | 0 / 0 / 0 |
| Cobertura | 99,7 % |
| Código duplicado | 1,1 % (42 líneas) |

> Son las cifras del análisis del pull request que introdujo SonarCloud. El primer análisis completo de `master`, después del merge, confirmó 0 *code smells* en todo el código. Las 42 líneas duplicadas eran un bloque repetido en los `main()` de `optimizado.py` y `concurrente.py`, que se eliminó en la [refactorización](#refactorización).

Los hallazgos de seguridad aceptados están en [Falsos positivos y excepciones](seguridad.md#falsos-positivos-y-excepciones).

## Refactorización

| Hallazgo | Detectado por | Cambio |
| :--- | :--- | :--- |
| Bloque de 21 líneas duplicado en `main()` de `optimizado.py` y `concurrente.py`: crear el buscador, cronometrar la consulta e imprimir el resultado | SonarCloud | Pasa a `resolver_consulta()` en `optimizado.py`, que llaman los dos `main()`. |
| Complejidad ciclomática de 23 en `generar_reporte()` y de 15 en `main()` de `perfilado.py` | Ruff (C901) | `generar_reporte()` arma el HTML con una función privada por sección, y `main()` delega en una función por etapa. Bajan a 1 y 2. |
| El procesamiento de texto convivía con el índice y la búsqueda en `optimizado.py` | Revisión de cohesión | `normalize()`, `stem()`, `tokenizar()` y sus constantes pasan a [`src/core/procesamiento_texto.py`](https://github.com/JoniMora/pef-26/blob/master/src/core/procesamiento_texto.py), que importan `optimizado.py` y `concurrente.py`. |

`baseline.py` no usa el módulo de procesamiento de texto, y es a propósito: es la búsqueda ingenua contra la que se mide la mejora. Si tokenizara, cambiarían sus resultados (`"datos"` pasaría de 47.788 a 49.702 coincidencias, ver [Validación de equivalencia](pruebas.md#validación-de-equivalencia)) y dejarían de valer las mediciones.

Con este cambio, el código duplicado que mide SonarCloud pasa de 42 líneas (1,1 %) a 0.

Para que la complejidad no vuelva a crecer, Ruff aplica la regla **C901 con un máximo de 10 por función**, y Lizard limita además cada función a **50 líneas de código y complejidad 15**. Hoy el máximo de Ruff es 7, y la función más larga, `main()` de `perfilar_api.py`, tiene 48 líneas. Tampoco quedan funciones muertas ni imports sin usar: Ruff controla los imports en el CI (F401), y las 134 funciones y clases de `src/` tienen al menos una referencia.

**Verificación.** El motor está cubierto por los tests, que pasan sin cambios. `perfilado.py` es el arnés de medición y entonces no tenía tests, así que esa refactorización se verificó comparando salidas contra la versión anterior: el reporte HTML sale idéntico byte a byte en 7 variantes de resultados, los 10 gráficos también, y una corrida completa de `--todo` produce la misma salida y el mismo `perfilado.json`, salvo los tiempos medidos. La salida por consola de `optimizado.py` y `concurrente.py` también es idéntica.

### División de las funciones largas

Al activar Lizard, cinco funciones superaban las 50 líneas de código. Se dividieron sin cambiar lo que hacen:

| Función | Líneas | Complejidad (Lizard) | División |
| :--- | ---: | ---: | :--- |
| `responder_preguntas()` | 118 | 8 | Una función por pregunta, y una constante para la respuesta que no depende de las mediciones. |
| `comparativa()` | 61 | 23 | Avisar la sobrecarga, medir las rondas, medir la memoria y resumir cada versión. |
| `medir_version()` | 61 | 12 | Una función por forma de medir: sin índice, con índice, con `sorted()` y con el buscador. |
| `perfilar_scalene()` | 56 | 10 | Ubicar el ejecutable y correr una versión. |
| `main()` de `concurrente.py` | 53 | 6 | `_crear_parser()`, igual que en `perfilado.py`. |

Las cuatro primeras son del arnés de medición, y ahí un error no rompe nada visible: solo cambia lo que se mide. Por eso se trabajó en este orden:

1. **Primero los tests**, contra el código sin cambios ([`tests/test_perfilado.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_perfilado.py)). Las operaciones medidas se reemplazan por dobles que avanzan un reloj falso con un costo primo distinto, así el tiempo informado se descompone de una sola manera: si una operación entra o sale de una ventana cronometrada, el número cambia.
2. **Probar los tests con fallas provocadas.** De 47 fallas sobre el código original se escaparon 3, y eso obligó a reforzarlos. Después detectaron las 47, y las 52 sobre el código dividido.
3. **Dividir sin tocarlos.** Las funciones nuevas se llaman fuera de las ventanas cronometradas, y estas conservan las mismas instrucciones, comparadas con `dis`.

Dos detalles no se pueden simplificar sin cambiar lo que se mide:

- `normalizar_consulta()` se llama en todas las versiones con índice, aunque solo `estructura` use el resultado. Calienta el `lru_cache` de `normalize()` y `stem()` en el proceso que mide. El índice paralelo se construye en otros procesos, y sin esa llamada la primera consulta cronometrada pagaría esos fallos.
- El ranking de cProfile omite las funciones `_medir_*`. Acumulan casi todo el tiempo sin hacer trabajo propio, y le quitarían su lugar en el top 12 a funciones del motor. Siguen estando en el `.prof`.

**Corrida real.** Para saber cuánto varía una medición por sí sola, el código viejo se comparó contra una copia de sí mismo (A/A) y contra el nuevo (A/B), con las corridas alternadas. Sobre 50.000 documentos y 3 rondas:

| Versión | Consulta A/A | Consulta A/B | Indexación A/A | Indexación A/B | RSS A/A | RSS A/B |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| Implementación inicial | 0,24 % | −0,84 % | — | — | 2,80 % | −1,21 % |
| Estructura optimizada | 0,19 % | +0,14 % | 0,48 % | +1,22 % | 0,10 % | +0,15 % |
| Algoritmo optimizado | 0,44 % | +0,52 % | 0,13 % | −1,50 % | 0,17 % | −0,01 % |
| Concurrencia/paralelismo | 0,55 % | −0,04 % | 5,74 % | −0,49 % | 0,20 % | −0,61 % |
| Versión final | 1,93 % | −2,36 % | 8,17 % | −10,13 % | 1,09 % | +0,13 % |

- **Tiempos:** no hay una dirección. A/B supera a A/A en varias filas, por poco y hacia los dos lados: `estructura` y `algoritmo` construyen el mismo índice y se mueven en sentidos opuestos, y el −10,13 % de `final` no aparece en `concurrencia`, que construye igual. Una sola comparación A/A con 3 rondas subestima el ruido.
- **Memoria:** el pico de `tracemalloc` difiere como máximo un 0,10 %. Con 5.000 documentos y 6 rondas, el RSS sale entre 0,1 y 0,2 MB más alto en las cinco versiones, probablemente porque el script es más largo. Con 50.000 no se nota.
- **Resultados:** las cinco versiones devuelven 47.797 coincidencias, y 4.762 con 5.000 documentos.
- **Salidas:** con el mismo `perfilado.json`, el reporte HTML, los 10 gráficos y la tabla comparativa salen idénticos byte a byte. Una corrida real de todos los perfiladores deja un JSON con la misma forma. El top 12 de cProfile solo cambia en las últimas filas, que también varían entre corridas del mismo código.

Scalene termina con error en `algoritmo`, `concurrencia` y `final` con los dos códigos, en Python 3.14, así que esa falla no viene de esta división.
