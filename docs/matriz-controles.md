# Matriz de controles

Contrato de calidad del proyecto: qué se verifica, con qué, cómo se reproduce, qué reporte deja y cuándo se rechaza un cambio. El pipeline ([`.github/workflows/ci.yml`](https://github.com/JoniMora/pef-26/blob/master/.github/workflows/ci.yml)) implementa esta tabla, y un control nuevo se agrega primero acá.

Todos los controles corren en el CI. Los valores que dependen del entorno, como la tolerancia del benchmark y los límites de memoria, se fijaron con mediciones, no de antemano: el detalle está en [Rendimiento](rendimiento.md#controles-en-el-ci).

| Control | Herramienta | Comando | Reporte | Se rechaza si | Estado |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Pruebas | pytest | `make tests` | Salida del job | Falla al menos una prueba | Activo |
| Cobertura | pytest-cov | `make tests` | Artefacto `cobertura` (`coverage.xml` y `htmlcov/`) | Cobertura menor al 80 % (`fail_under`) | Activo |
| Análisis estático | Ruff, SonarCloud | `make lint` (Sonar solo corre en el CI) | Anotaciones en el pull request y panel de SonarCloud | Algún hallazgo de Ruff, un archivo sin formatear o el quality gate caído | Activo |
| Complejidad | Ruff C901, Lizard | `make lint`, `make complejidad` | Salida del job | Complejidad mayor a 10 (Ruff); más de 50 líneas de código o complejidad mayor a 15 (Lizard) | Activo |
| Tipado | mypy | `make tipado` | Salida del job | Algún error en `core/`, `optimizado.py` o `api.py`, con `disallow_untyped_defs` | Activo |
| Vulnerabilidades del código | Bandit, SonarCloud | `make seguridad` | Salida del job y artefacto `seguridad` (`bandit.json`) | Algún hallazgo sin excepción documentada | Activo |
| Vulnerabilidades de dependencias | pip-audit, `npm audit` | `make seguridad` | Salida del job y artefacto `seguridad` (`pip-audit-*.json` y `npm-audit.json`) | Alguna vulnerabilidad sin excepción documentada, en cualquier lock | Activo |
| Secretos | gitleaks | `make secretos` | Salida del job y artefacto `secretos` (`gitleaks.json`), con los valores ocultos | Algún hallazgo en todo el historial, sin excepción documentada | Activo |
| Dependencias | `uv pip compile` con hashes, `package-lock.json`, Dependabot | `make instalar`, `make lock`, `make tests` | Pull requests de Dependabot | La instalación no coincide con los hashes del lock, o una versión pedida en un `.in` no está en su lock (`tests/test_dependencias.py`) | Activo; Dependabot corre desde `master` |
| Documentación | Sphinx con MyST, markdownlint, `tests/test_docs.py` | `make docs`, `make tests` | Artefacto `github-pages` con el sitio | Una advertencia de Sphinx, incluido un enlace interno roto; un error de markdownlint; un enlace a un archivo del repositorio que no existe, o una sección, módulo u objetivo de `make` sin documentar | Activo |
| Enlaces externos | Sphinx `linkcheck` | `make enlaces` | Artefacto `enlaces` | No rechaza: informa, porque la caída de un sitio ajeno no debe frenar un cambio | Activo |
| Benchmark | pytest-benchmark | `make benchmark` | Resumen de la corrida y artefacto `rendimiento` (`benchmark.json` y las corridas en `benchmark/`) | Frente a la rama base, en el mismo job, alguna operación sube más de un 10 % en mínimo y mediana, o más de un 30 % en mínimo, mediana o media, y lo repite al confirmarlo | Activo |
| Profiling de CPU | cProfile, line_profiler | `make profiling` | Resumen de la corrida y artefacto `rendimiento` (`.prof`, reportes por línea y `ranking.json` en `profiling/`) | Un perfil no se puede generar o queda vacío | Activo |
| Memoria | tracemalloc | `make memoria` | Resumen de la corrida y artefacto `rendimiento` (`memoria.json`) | El pico de alguna versión supera su límite: el mayor pico medido, más un 10 % | Activo |

`make controles` corre en orden lint, complejidad, tipado, seguridad, secretos, tests, rendimiento, documentación, benchmark, profiling y memoria: los mismos comandos que el CI, salvo SonarCloud, que necesita el token del proyecto. Cómo correr cada uno y cómo resolver sus fallos está en [Mantenimiento](mantenimiento.md).

## Complejidad: por qué dos límites

Ruff y Lizard miden distinto: Lizard suma también las condiciones `and` y `or` y las listas por comprensión, así que da números más altos. `comparativa()` tenía 23 con Lizard y pasaba el máximo de 10 de Ruff. Lizard revisa `src/` y `scripts/`, salvo `scripts/generar_informe_newrelic.py`, cuyas funciones largas son el texto del informe, con complejidad 1.

## Resultado final

El job **Resultado final** es el único check obligatorio para integrar en `master`. Depende de todos los demás jobs y rechaza si alguno no terminó en `success`: un control omitido o cancelado no verificó nada, así que tampoco aprueba. [`tests/test_ci.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_ci.py) falla si un job nuevo no se suma a sus dependencias, si un paso ejecuta un comando sin pasar por `make` o si un control ignora sus fallos. La única excepción son los enlaces externos.

## Performance Gate

`make rendimiento` corre [`tests/test_rendimiento.py`](https://github.com/JoniMora/pef-26/blob/master/tests/test_rendimiento.py): la consulta optimizada debe tardar menos de 0,5 s y ganarle a la línea base. Es una red gruesa: en un corpus de 2.000 documentos la consulta tarda 0,41 ms, así que una regresión de 100 veces pasa los dos tests. Las regresiones finas las detecta el [benchmark](rendimiento.md#benchmark). Se conserva porque, a diferencia del benchmark, no se compara contra la rama base: varias regresiones chicas, cada una por debajo de la tolerancia, pueden acumularse, pero nunca hacer que el índice pierda contra el barrido secuencial.

## Política de bloqueo de seguridad

**Tolerancia cero con excepciones documentadas:** cualquier hallazgo de Bandit, pip-audit, `npm audit` o gitleaks rechaza el cambio, sea cual sea su severidad. La decisión por severidad, el motivo, cómo se registra una excepción y las excepciones vigentes están en [Seguridad](seguridad.md#política-de-bloqueo).
