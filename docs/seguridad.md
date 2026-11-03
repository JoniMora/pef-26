# Seguridad

Riesgos identificados, dependencias vulnerables, medidas correctivas y la política que decide cuándo un hallazgo bloquea un cambio. Las herramientas y los comandos de cada control están en la [matriz de controles](matriz-controles.md).

## Riesgos identificados

| Riesgo | Dónde | Estado | Medida |
| :--- | :--- | :--- | :--- |
| Leer archivos de fuera del índice con un manifiesto alterado (S2083) | `indice_en_disco.py` | Corregido | El manifiesto guarda los lotes por número, no por nombre de archivo. Un test reproduce el ataque. |
| Ejecutar código al cargar un índice guardado | `indice_en_disco.py` | Evitado | El índice se guarda en JSON. Cargar un pickle puede ejecutar código, aunque era 0,2 s más rápido ([comparación de formatos](diseno-tecnico.md#índice-en-disco-por-lotes)). |
| Exponer la licencia de New Relic | `servidor.py` | Mitigado | La licencia va en un `.env` que git ignora, nunca en el código ni en la salida del programa. Lo que se versiona es una plantilla sin claves. En GitHub están activos el *secret scanning* y la *push protection*. Falta el control de secretos en el CI. |
| Dependencias con vulnerabilidades conocidas | `requirements*.txt` | Controlado | pip-audit bloquea el CI. Ver [Dependencias vulnerables](#dependencias-vulnerables). |
| Agotar recursos con `POST /reindexar` | `api.py` | Aceptado | No tiene autenticación ni límite de uso, y cada recarga usa toda la CPU disponible y más que duplica la RAM ([medición](rendimiento.md#monitoreo-con-new-relic)). Se acepta porque la API es de uso local: `servidor.py` y uvicorn escuchan por defecto en `127.0.0.1`. |
| Consultas costosas en `GET /buscar` | `api.py` | Aceptado | `q` no tiene largo máximo y `top_k` se limita a 100. Mismo criterio: uso local. |
| Mostrar rutas del servidor en un error | `api.py` | Aceptado | La respuesta 503 incluye la ruta absoluta del corpus. Es información útil en uso local; hay que quitarla si la API se expone. |

> **Antes de exponer la API fuera de la máquina** hay que agregar autenticación, limitar `POST /reindexar` y el largo de `q`, y quitar la ruta del error 503.

## Dependencias vulnerables

| Paquete | Vulnerabilidades | Medida |
| :--- | :--- | :--- |
| Starlette anterior a 1.3.1, que llegaba a través de FastAPI 0.119 | CVE-2025-62727, CVE-2026-48710, CVE-2026-48817, CVE-2026-48818, CVE-2026-54282 y CVE-2026-54283 | Se fija `starlette==1.8.0` en [`requirements.txt`](https://github.com/JoniMora/pef-26/blob/master/requirements.txt), y pip-audit lo controla en el CI. |

Hoy, pip-audit no encuentra vulnerabilidades conocidas en [`requirements-dev.txt`](https://github.com/JoniMora/pef-26/blob/master/requirements-dev.txt), que incluye `requirements.txt`. Los archivos de medición, monitoreo e informes todavía no se auditan en el CI; figura como pendiente en la [matriz de controles](matriz-controles.md).

## Política de bloqueo

**Tolerancia cero con excepciones documentadas.** Cualquier hallazgo de Bandit, pip-audit o gitleaks rechaza el cambio, sea cual sea su severidad.

- **Por qué no se filtra por severidad:** pip-audit no informa severidad, y bloquear todo es más estricto y fácil de verificar. Si aparece un falso positivo, se justifica; no se baja el umbral.
- **Cómo se registra una excepción:** con la marca de la propia herramienta (`# nosec <regla>` en Bandit, `--ignore-vuln <id>` en pip-audit) y una fila en la tabla de abajo, en el mismo pull request.
- **SonarCloud:** su quality gate se aplica al código nuevo y bloquea desde el CI.

## Falsos positivos y excepciones

| Herramienta | Regla o identificador | Dónde | Motivo |
| :--- | :--- | :--- | :--- |
| Bandit, SonarCloud | B311, S2245 (generador pseudoaleatorio) | `baseline.py`, `generar_trafico.py` y `perfilar_api.py` | Azar sin uso criptográfico: texto ficticio y selección de consultas de carga. |
| Bandit, SonarCloud | B404, B603, S8705 (subprocesos) | `perfilado.py` | Subprocesos con lista de argumentos, sin shell, que ejecutan herramientas de perfilado o el mismo arnés. El directorio lo elige quien corre el script. |
| SonarCloud | S8707 (ruta recibida por línea de comandos) | `baseline.py`, `servidor.cargar_variables()`, `generar_trafico.main()` y `perfilar_api.main()` | Herramientas locales: quien las ejecuta elige sus propias rutas (el directorio del corpus, `--env-file`, `--salida` y `--cprofile`), sin cruzar límites de permisos. |

## Análisis y controles activos

| Qué se analiza | Herramienta | Dónde corre |
| :--- | :--- | :--- |
| Patrones inseguros en el código | Bandit y SonarCloud | CI, en cada pull request |
| Vulnerabilidades conocidas en dependencias | pip-audit | CI, en cada pull request |
| Secretos | *Secret scanning* y *push protection* de GitHub | GitHub, en cada push |

Bandit se configura en [`pyproject.toml`](https://github.com/JoniMora/pef-26/blob/master/pyproject.toml), que excluye `tests/`, `.venv/` y `profiles/`. El detector de secretos en el CI, los reportes en JSON y las actualizaciones automáticas de dependencias figuran como pendientes en la [matriz de controles](matriz-controles.md).
