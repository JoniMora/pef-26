# Seguridad

Riesgos identificados, dependencias vulnerables, medidas correctivas y la política que decide cuándo un hallazgo bloquea un cambio. Las herramientas y los comandos de cada control están en la [matriz de controles](matriz-controles.md).

## Riesgos identificados

| Riesgo | Dónde | Estado | Medida |
| :--- | :--- | :--- | :--- |
| Leer archivos de fuera del índice con un manifiesto alterado (S2083) | `indice_en_disco.py` | Corregido | El manifiesto guarda los lotes por número, no por nombre de archivo. Un test reproduce el ataque. |
| Ejecutar código al cargar un índice guardado | `indice_en_disco.py` | Evitado | El índice se guarda en JSON. Cargar un pickle puede ejecutar código, aunque era 0,2 s más rápido ([comparación de formatos](diseno-tecnico.md#índice-en-disco-por-lotes)). |
| Exponer la licencia de New Relic | `servidor.py` | Mitigado | La licencia va en un `.env` que git ignora, nunca en el código ni en la salida del programa. Lo que se versiona es una plantilla sin claves. En GitHub están activos el *secret scanning* y la *push protection*, y gitleaks revisa todo el historial en cada pull request. Se buscó además el valor exacto de la licencia en todo el historial: nunca se commiteó. |
| Dependencias con vulnerabilidades conocidas | `requirements*.txt`, `package-lock.json` | Controlado | pip-audit y `npm audit` bloquean el CI, sobre todos los locks. Ver [Dependencias vulnerables](#dependencias-vulnerables). |
| Instalar un paquete alterado | `requirements*.txt`, `package-lock.json`, gitleaks | Mitigado | Las versiones y los hashes están fijados, también los de las dependencias transitivas: `make instalar` usa `--require-hashes`, `npm ci` respeta el lock y el binario de gitleaks se verifica contra `scripts/gitleaks.sha256`. |
| Agotar recursos con `POST /reindexar` | `api.py` | Aceptado | No tiene autenticación ni límite de uso, y cada recarga usa toda la CPU disponible y más que duplica la RAM ([medición](rendimiento.md#monitoreo-con-new-relic)). Se acepta porque la API es de uso local: `servidor.py` y uvicorn escuchan por defecto en `127.0.0.1`. |
| Consultas costosas en `GET /buscar` | `api.py` | Aceptado | `q` no tiene largo máximo y `top_k` se limita a 100. Mismo criterio: uso local. |
| Mostrar rutas del servidor en un error | `api.py` | Aceptado | La respuesta 503 incluye la ruta absoluta del corpus. Es información útil en uso local; hay que quitarla si la API se expone. |

> **Antes de exponer la API fuera de la máquina** hay que agregar autenticación, limitar `POST /reindexar` y el largo de `q`, y quitar la ruta del error 503.

## Dependencias vulnerables

| Paquete | Vulnerabilidades | Medida |
| :--- | :--- | :--- |
| Starlette anterior a 1.3.1, que llegaba a través de FastAPI 0.119 | CVE-2025-62727, CVE-2026-48710, CVE-2026-48817, CVE-2026-48818, CVE-2026-54282 y CVE-2026-54283 | Se fija `starlette==1.8.0` en [`requirements.txt`](https://github.com/JoniMora/pef-26/blob/master/requirements.txt), y pip-audit lo controla en el CI. |
| Pillow 12.3.0, en `requirements-informes` | 39 avisos, entre ellos desbordes de memoria al decodificar imágenes | Se sube a `pillow==13.0.0`, que los corrige. El generador del informe en PDF se probó con esa versión. |
| re2js anterior a 2.8.7, a través de `markdownlint-cli2` | GHSA-gg6h-894w-4m9c, severidad alta: denegación de servicio por tiempo cuadrático | Se fuerza re2js 2.9.1 con `overrides` en `package.json`, porque ninguna versión de `markdownlint-cli2` lo corrige todavía. |
| KaTeX anterior a 0.18.2, a través de `markdownlint-cli2` | GHSA-238p-pmpm-9mq7, severidad baja | Se fuerza KaTeX 0.19.1, por el mismo motivo. |

Pillow, re2js y KaTeX aparecieron al ampliar la auditoría a todos los locks: antes solo se revisaba `requirements-dev.txt`. Con estas correcciones, pip-audit y `npm audit` no encuentran vulnerabilidades conocidas en ninguno.

## Política de bloqueo

**Tolerancia cero con excepciones documentadas.** Cualquier hallazgo de Bandit, pip-audit, `npm audit` o gitleaks rechaza el cambio, sea cual sea su severidad.

- **Por qué no se filtra por severidad:** pip-audit no informa severidad, y bloquear todo es más estricto y fácil de verificar. Si aparece un falso positivo, se justifica; no se baja el umbral.
- **Cómo se registra una excepción:** con la marca de la propia herramienta (`# nosec <regla>` en Bandit, `--ignore-vuln <id>` en pip-audit, la huella del hallazgo en `.gitleaksignore` en gitleaks) y una fila en la tabla de abajo, en el mismo pull request. `npm audit` no admite excepciones: se actualiza el paquete o se fuerza una versión con `overrides`.
- **SonarCloud:** su quality gate se aplica al código nuevo y bloquea desde el CI.

## Falsos positivos y excepciones

| Herramienta | Regla o identificador | Dónde | Motivo |
| :--- | :--- | :--- | :--- |
| Bandit, SonarCloud | B311, S2245 (generador pseudoaleatorio) | `baseline.py`, `generar_trafico.py` y `perfilar_api.py` | Azar sin uso criptográfico: texto ficticio y selección de consultas de carga. |
| Bandit, SonarCloud | B404, B603, S8705 (subprocesos) | `perfilado.py` | Subprocesos con lista de argumentos, sin shell, que ejecutan herramientas de perfilado o el mismo arnés. El directorio lo elige quien corre el script. |
| SonarCloud | S8707 (ruta recibida por línea de comandos) | `baseline.py`, `servidor.cargar_variables()`, `generar_trafico.main()` y `perfilar_api.main()` | Herramientas locales: quien las ejecuta elige sus propias rutas (el directorio del corpus, `--env-file`, `--salida` y `--cprofile`), sin cruzar límites de permisos. |
| gitleaks | `generic-api-key` | `sonar-project.properties`, línea 3 | `sonar.projectKey` es el identificador público del proyecto en SonarCloud, no una clave. |

## Análisis y controles activos

| Qué se analiza | Herramienta | Dónde corre | Reporte |
| :--- | :--- | :--- | :--- |
| Patrones inseguros en el código | Bandit y SonarCloud | CI, en cada pull request | Salida del job, artefacto `seguridad` (`bandit.json`) y panel de SonarCloud |
| Vulnerabilidades conocidas en dependencias | pip-audit y `npm audit`, sobre todos los locks | CI, en cada pull request | Salida del job y artefacto `seguridad` (`pip-audit-*.json` y `npm-audit.json`) |
| Secretos en todo el historial | gitleaks | CI, en cada pull request | Salida del job y artefacto `secretos` (`gitleaks.json`), con los valores ocultos |
| Secretos al subir cambios | *Secret scanning* y *push protection* de GitHub | GitHub, en cada push | Panel de seguridad de GitHub |
| Versiones desactualizadas | Dependabot | GitHub, cada semana | Pull requests de actualización |

Bandit se configura en [`pyproject.toml`](https://github.com/JoniMora/pef-26/blob/master/pyproject.toml), que excluye los tests y los directorios que no son código del proyecto. Cómo correr cada control y resolver sus fallos está en [Mantenimiento](mantenimiento.md).
