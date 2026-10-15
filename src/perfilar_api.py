"""
Reproduce en un solo proceso el trabajo de la API, para perfilarlo.

La API atiende cada búsqueda en un hilo del pool de FastAPI, y cProfile
solo mide el hilo desde el que se activa. Este script hace el mismo
trabajo que ``GET /buscar`` y ``POST /reindexar``, con la misma mezcla de
consultas que :mod:`generar_trafico`, pero sin HTTP ni hilos: así
cProfile y Scalene ven todo el tiempo de búsqueda. Usa el mismo servicio
que la API (:class:`api.ServicioDeBusqueda`), que carga el índice guardado
o lo construye si no existe. Queda afuera lo que agrega el framework:
HTTP, la validación de FastAPI y la serialización de la respuesta.

Comandos (desde la raíz del repositorio)::

    python src/perfilar_api.py --consultas 3000
    python src/perfilar_api.py --reindexar --cprofile profiles/cprofile-api.prof
    scalene run -o profiles/scalene-api.json src/perfilar_api.py --- --consultas 3000

Scalene no acompaña a los procesos hijos que crea la reconstrucción del
índice: con Scalene no se usa ``--reindexar``, y el índice tiene que estar
guardado de antes (la primera corrida sin perfilador lo guarda).
"""

import argparse
import cProfile
import os
import random
import time
from pathlib import Path

from api import ServicioDeBusqueda
from generar_trafico import TIPOS, elegir_consulta
from optimizado import DEFAULT_CORPUS


def simular_carga(
    servicio, consultas, mezcla=(60, 30, 10), semilla=None, reindexar=False
):
    """
    Resuelve las búsquedas como ``GET /buscar`` y, si se pide, reindexa.

    :param servicio: El servicio de búsqueda, el mismo que usa la API.
    :type servicio: api.ServicioDeBusqueda
    :param consultas: Cantidad de búsquedas.
    :type consultas: int
    :param mezcla: Peso de cada tipo: ``(repetida, variada, inexistente)``.
    :type mezcla: tuple[float, float, float]
    :param semilla: Semilla para repetir la misma secuencia de consultas.
    :type semilla: int | None
    :param reindexar: Si al final se reconstruye el índice una vez, como
        ``POST /reindexar``.
    :type reindexar: bool
    :return: Cuántas búsquedas hubo de cada tipo.
    :rtype: dict[str, int]
    """
    azar = random.Random(semilla)  # nosec B311
    por_tipo = dict.fromkeys(TIPOS, 0)

    for _ in range(consultas):
        tipo, consulta, top_k = elegir_consulta(azar, mezcla)
        servicio.obtener_buscador().buscar(consulta, top_k)
        por_tipo[tipo] += 1

    if reindexar:
        servicio.reindexar()

    return por_tipo


def main():
    """Simula la carga, opcionalmente con cProfile, e imprime un resumen."""
    parser = argparse.ArgumentParser(
        description="Simula en un proceso el trabajo de la API, para perfilarlo"
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=os.environ.get("BUSCADOR_CORPUS") or DEFAULT_CORPUS,
    )
    parser.add_argument(
        "--indice",
        type=Path,
        default=os.environ.get("BUSCADOR_INDICE"),
        help="dónde está guardado el índice; por defecto, el mismo que usa la API",
    )
    parser.add_argument("--consultas", type=int, default=3000)
    parser.add_argument("--semilla", type=int, default=1)
    parser.add_argument(
        "--reindexar",
        action="store_true",
        help="reconstruir el índice una vez al final, como POST /reindexar",
    )
    parser.add_argument(
        "--cprofile",
        type=Path,
        default=None,
        help="guardar el perfil de cProfile (.prof), para verlo con snakeviz",
    )
    args = parser.parse_args()

    servicio = ServicioDeBusqueda(args.corpus, args.indice)
    perfil = cProfile.Profile() if args.cprofile else None
    inicio = time.perf_counter()

    if perfil:
        perfil.enable()
    por_tipo = simular_carga(
        servicio, args.consultas, semilla=args.semilla, reindexar=args.reindexar
    )
    if perfil:
        perfil.disable()
        args.cprofile.parent.mkdir(parents=True, exist_ok=True)
        perfil.dump_stats(args.cprofile)

    segundos = time.perf_counter() - inicio
    detalle = ", ".join(f"{tipo}: {cantidad}" for tipo, cantidad in por_tipo.items())
    print(f"{args.consultas} búsquedas en {segundos:.1f} s ({detalle})")
    if args.reindexar:
        print("Con una recarga del índice al final")
    if args.cprofile:
        print(f"Perfil de cProfile en {args.cprofile}")


# La guarda es obligatoria: la reconstrucción del índice crea procesos con
# el método de arranque spawn, que vuelve a importar este script.
if __name__ == "__main__":
    main()
