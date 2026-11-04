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
make seguridad     # Bandit sobre el código y pip-audit sobre las dependencias
make tests         # tests con cobertura mínima del 80 %; reporte en htmlcov/
make rendimiento   # Performance Gate
make docs          # sitio con Sphinx, sin advertencias, y markdownlint
make enlaces       # enlaces externos; informa, pero no bloquea el CI
make diagrama      # regenera el diagrama de arquitectura; requiere Graphviz
make controles     # lint, seguridad, tests, rendimiento y docs, en ese orden
```

`make resultado-final` lo corre solo el CI: decide a partir de los resultados de los demás jobs, y sin ellos rechaza. SonarCloud también corre solo en el CI, porque necesita el token del proyecto.

> Los tests generan su propio corpus en un directorio temporal, así que no necesitan `data/corpus`. `ruff format .` (sin `--check`) aplica el formato en lugar de solo verificarlo.

## Pipeline de CI

Corre en cada pull request y en cada push a `master`. Los jobs de lint, seguridad y documentación corren en paralelo, y los tests solo si los dos primeros pasan.

| Job | Qué hace |
| :--- | :--- |
| Lint (Ruff) | `make lint`. |
| Seguridad (Bandit y pip-audit) | `make seguridad`. |
| Documentación (Sphinx y enlaces) | `make docs`, guarda el sitio como artefacto y `make enlaces`, que informa sin bloquear. |
| Tests, cobertura y Performance Gate | `make tests`, guarda la cobertura como artefacto, envía el análisis a SonarCloud y corre `make rendimiento`. |
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
| Bandit | `make seguridad` | Corregir el código. Si es un falso positivo, marcarlo con `# nosec <regla>` y agregarlo a [Falsos positivos y excepciones](seguridad.md#falsos-positivos-y-excepciones). |
| pip-audit | `make seguridad` | Subir la versión en el `requirements` que corresponda. Sin versión corregida, registrar una excepción con `--ignore-vuln` en el `Makefile`, con su motivo. |
| Tests | `make tests` | `pytest <archivo>::<test> -x` para aislar la falla. Si pasa en local, revisar si depende del orden o de la velocidad. |
| Cobertura | `make tests` | Ver qué líneas faltan en la salida o en `htmlcov/index.html`, que en el CI es el artefacto `cobertura`. |
| SonarCloud | Solo en el CI | Abrir el [panel](https://sonarcloud.io/dashboard?id=JoniMora_pef-26) y corregir lo que tiró el quality gate. Si el error es de autenticación, revisar el secreto `SONAR_TOKEN`. |
| Performance Gate | `make rendimiento` | Una regresión real se confirma con `CORPUS_DOCS=20000 pytest -m rendimiento --no-cov`. Perfilar con [estos comandos](rendimiento.md#cómo-reproducir-las-mediciones). |
| Sphinx | `make docs` | Corregir la advertencia que imprime. Un enlace interno roto aparece como `myst.xref_missing`; un docstring mal formado, con la ruta del módulo. |
| markdownlint | `make docs` | `npx markdownlint-cli2 --fix README.md "docs/**/*.md" "#docs/_build"` resuelve los automáticos. La configuración está en [`.markdownlint-cli2.jsonc`](https://github.com/JoniMora/pef-26/blob/master/.markdownlint-cli2.jsonc). |
| Enlaces externos | `make enlaces` | No bloquea. Revisar el artefacto `enlaces` y corregir el enlace si el problema no es una caída temporal del sitio. |
| `tests/test_ci.py` | `pytest tests/test_ci.py` | Sumar el job nuevo a los `needs` de "Resultado final", o mover el comando suelto a un objetivo del `Makefile`. |
| `tests/test_docs.py` | `pytest tests/test_docs.py` | Corregir el enlace al repositorio, o documentar el módulo o el objetivo nuevo. |
| Resultado final, sin otro job en rojo | `gh run view <id-de-la-corrida>` | Un job omitido o cancelado también rechaza: volver a correr la corrida. |

## Agregar un control

1. Definirlo en la [matriz de controles](matriz-controles.md): herramienta, comando, reporte y criterio de rechazo.
2. Agregar el objetivo en el [`Makefile`](https://github.com/JoniMora/pef-26/blob/master/Makefile) y su versión fijada en [`requirements-dev.txt`](https://github.com/JoniMora/pef-26/blob/master/requirements-dev.txt).
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

Para que la complejidad no vuelva a crecer, Ruff aplica ahora la regla **C901 con un máximo de 10 por función**. La función más compleja del proyecto es `medir_version()`, con 10, justo en el límite. Tampoco quedan funciones muertas ni imports sin usar: Ruff controla los imports en el CI (F401), y las 82 funciones y clases de `src/` tienen al menos una referencia.

**Verificación.** El motor está cubierto por los tests, que pasan sin cambios. `perfilado.py` es el arnés de medición y no tiene tests, así que su refactorización se verificó comparando salidas contra la versión anterior: el reporte HTML sale idéntico byte a byte en 7 variantes de resultados, los 10 gráficos también, y una corrida completa de `--todo` produce la misma salida y el mismo `perfilado.json`, salvo los tiempos medidos. La salida por consola de `optimizado.py` y `concurrente.py` también es idéntica.
