# Matriz de controles

Contrato de calidad del proyecto: qué se verifica, con qué, cómo se reproduce, qué reporte deja y cuándo se rechaza un cambio. El pipeline ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) implementa esta tabla, y un control nuevo se agrega primero acá.

**Estado:** *Activo* corre hoy en el CI. *Bloque N* es el pull request del parcial 3 que lo activa: 2 documentación, 3 seguridad y dependencias, 4 tipado y complejidad, 5 rendimiento. Los valores "a medir" se fijan con una medición en ese bloque, no de antemano.

| Control | Herramienta | Comando | Reporte | Se rechaza si | Estado |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Pruebas | pytest | `make tests` | Salida del job | Falla al menos una prueba | Activo |
| Cobertura | pytest-cov | `make tests` | Artefacto `cobertura` (`coverage.xml` y `htmlcov/`) | Cobertura menor al 80 % (`fail_under`) | Activo |
| Análisis estático | Ruff, SonarCloud | `make lint` (Sonar solo corre en el CI) | Anotaciones en el pull request y panel de SonarCloud | Algún hallazgo de Ruff, un archivo sin formatear o el quality gate caído | Activo |
| Complejidad | Ruff C901, Lizard | `make lint`, `make complejidad` | Salida del job | Complejidad mayor a 10 (Ruff); más de 50 líneas de código o complejidad mayor a 15 (Lizard) | C901 activo; Lizard en bloque 4 |
| Tipado | mypy | `make tipado` | Salida del job | Algún error en `core/`, `optimizado.py` o `api.py`, con `disallow_untyped_defs` | Bloque 4 |
| Vulnerabilidades del código | Bandit, SonarCloud | `make seguridad` | Salida del job; JSON desde el bloque 3 | Algún hallazgo sin excepción documentada | Activo; reporte en bloque 3 |
| Vulnerabilidades de dependencias | pip-audit | `make seguridad` | Salida del job; JSON desde el bloque 3 | Alguna vulnerabilidad sin excepción documentada | Activo sobre `requirements-dev.txt`; todos los `requirements` en bloque 3 |
| Secretos | gitleaks | `make secretos` | Artefacto JSON | Algún hallazgo sin excepción documentada | Bloque 3 |
| Dependencias | Lock con hashes, Dependabot | `make instalar` | Pull requests de Dependabot | La instalación no coincide con los hashes del lock | Versiones directas fijadas; lock en bloque 3 |
| Documentación | Sphinx, linkcheck, markdownlint | `make docs` | Artefacto con el sitio | Una advertencia de Sphinx, un enlace interno roto o un error de markdownlint | Bloque 2 |
| Benchmark | pytest-benchmark | `make benchmark` | Artefacto JSON | Regresión mayor a la tolerancia (a medir) frente a la rama base, medida en el mismo job | Bloque 5; hoy `make rendimiento` (ver abajo) |
| Profiling de CPU | cProfile | `make profiling` | Artefacto `.prof` y ranking de funciones | El perfil no se puede generar | Bloque 5 |
| Memoria | tracemalloc | `make memoria` | Artefacto JSON | El pico supera el límite (a medir) | Bloque 5 |

`make controles` corre en orden lint, seguridad, tests y rendimiento: los mismos comandos que el CI, salvo SonarCloud, que necesita el token del proyecto.

## Resultado final

El job **Resultado final** es el único check obligatorio para integrar en `master`. Depende de todos los demás jobs y rechaza si alguno no terminó en `success`: un control omitido o cancelado no verificó nada, así que tampoco aprueba. [`tests/test_ci.py`](../tests/test_ci.py) falla si un job nuevo no se suma a sus dependencias o si un paso ejecuta un comando sin pasar por `make`.

## Performance Gate actual

`make rendimiento` corre [`tests/test_rendimiento.py`](../tests/test_rendimiento.py): la consulta optimizada debe tardar menos de 0,5 s y ganarle a la línea base. Sirve de red gruesa, pero no detecta regresiones finas: en un corpus de 2.000 documentos la consulta tarda 0,41 ms, así que una regresión de 100 veces pasa los dos tests. El benchmark del bloque 5 cubre ese caso; el test relativo contra la línea base se conserva porque no depende del hardware.

## Política de bloqueo de seguridad

**Tolerancia cero con excepciones documentadas.** Cualquier hallazgo de Bandit, pip-audit o gitleaks rechaza el cambio, sea cual sea su severidad.

- **Por qué no se filtra por severidad:** pip-audit no informa severidad, y bloquear todo es más estricto y fácil de verificar. Si aparece un falso positivo, se justifica; no se baja el umbral.
- **Cómo se registra una excepción:** con la marca de la propia herramienta (`# nosec <regla>` en Bandit, `--ignore-vuln <id>` en pip-audit) y una fila en la tabla de abajo, en el mismo pull request.
- **SonarCloud:** su quality gate se aplica al código nuevo y bloquea desde el CI.

| Herramienta | Regla o identificador | Dónde | Motivo |
| :--- | :--- | :--- | :--- |
| Bandit, SonarCloud | B311, S2245 | `baseline.py`, `generar_trafico.py` y `perfilar_api.py` | Azar sin uso criptográfico: texto ficticio y selección de consultas de carga. |
| SonarCloud | S8707 | `baseline.py`, `servidor.py`, `generar_trafico.py` y `perfilar_api.py` | Herramientas locales: quien las ejecuta elige sus propias rutas, sin cruzar límites de permisos. |
| Bandit, SonarCloud | B404, B603, S8705 | `perfilado.py` | Subprocesos con lista de argumentos, sin shell, que ejecutan herramientas de perfilado o el mismo arnés. |

El bloque 3 revisa esta tabla contra las marcas `# nosec` del código y le suma los hallazgos de pip-audit y gitleaks.
