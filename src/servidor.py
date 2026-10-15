"""
Lanzador de la API, con monitoreo de New Relic opcional.

Si la variable de entorno ``NEW_RELIC_LICENSE_KEY`` está definida,
inicializa el agente de New Relic **antes** de importar la API, que es lo
que necesita para instrumentar FastAPI. Si no, la API arranca igual, sin
monitoreo. La licencia nunca se escribe en el código ni se imprime.

Comandos (desde la raíz del repositorio)::

    python src/servidor.py                       # sin New Relic
    python src/servidor.py --env-file .env       # toma la licencia de .env
    python src/servidor.py --port 8080

El agente se instala aparte, con ``pip install -r requirements-apm.txt``.
Variables opcionales: ``NEW_RELIC_APP_NAME`` (por defecto ``pef-26``) y
``NEW_RELIC_CONFIG_FILE`` (por ejemplo, una copia de
``newrelic.ini.example``).
"""

import argparse
import os
from pathlib import Path

import uvicorn


SRC_DIR = Path(__file__).resolve().parent
NOMBRE_APP = "pef-26"


def cargar_variables(archivo, entorno=None):
    """
    Carga variables ``NOMBRE=valor`` de un archivo, como un ``.env``.

    No pisa las variables que ya estén definidas en el entorno. Ignora las
    líneas vacías y los comentarios, y quita las comillas del valor.

    :param archivo: Archivo a leer.
    :type archivo: str | pathlib.Path
    :param entorno: Dónde cargarlas; por defecto, ``os.environ``.
    :type entorno: dict[str, str] | None
    :return: Los nombres de las variables que se cargaron.
    :rtype: list[str]
    """
    entorno = os.environ if entorno is None else entorno
    cargadas = []

    for linea in Path(archivo).read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue

        nombre, valor = linea.split("=", 1)
        nombre = nombre.strip()
        if nombre in entorno:
            continue

        entorno[nombre] = valor.strip().strip("'\"")
        cargadas.append(nombre)

    return cargadas


def iniciar_monitoreo(entorno=None):
    """
    Inicializa el agente de New Relic si hay una licencia en el entorno.

    Tiene que llamarse antes de importar la API.

    :param entorno: Variables de entorno; por defecto, ``os.environ``.
    :type entorno: dict[str, str] | None
    :return: Si el agente quedó activo.
    :rtype: bool
    :raises SystemExit: Si hay licencia pero el agente no está instalado.
    """
    entorno = os.environ if entorno is None else entorno

    if not entorno.get("NEW_RELIC_LICENSE_KEY"):
        return False

    try:
        import newrelic.agent
    except ImportError:
        raise SystemExit(
            "NEW_RELIC_LICENSE_KEY está definida pero el agente no está "
            "instalado: pip install -r requirements-apm.txt"
        ) from None

    entorno.setdefault("NEW_RELIC_APP_NAME", NOMBRE_APP)
    newrelic.agent.initialize(entorno.get("NEW_RELIC_CONFIG_FILE"))

    return True


def main():
    """
    Levanta la API con uvicorn, con New Relic si hay licencia.

    La construcción del índice usa procesos con el método de arranque
    ``spawn``, que vuelve a importar este script en cada proceso hijo: por
    eso el servidor solo arranca bajo ``if __name__ == "__main__"``.
    """
    parser = argparse.ArgumentParser(description="Levanta la API del buscador")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="archivo con variables NOMBRE=valor, por ejemplo .env",
    )
    args = parser.parse_args()

    if args.env_file:
        cargar_variables(args.env_file)

    if iniciar_monitoreo():
        print(f"New Relic: activo (app {os.environ['NEW_RELIC_APP_NAME']})")
    else:
        print("New Relic: desactivado (no hay NEW_RELIC_LICENSE_KEY)")

    uvicorn.run("api:app", app_dir=str(SRC_DIR), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
