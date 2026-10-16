"""
Generador de carga para la API del buscador.

Simula usuarios concurrentes que consultan ``GET /buscar`` y, si se pide,
recargan el índice con ``POST /reindexar`` cada tantos segundos. Sirve
para poblar los tableros de New Relic y para perfilar la API bajo carga.

Las consultas mezclan tres tipos:

- **repetida:** un conjunto chico de consultas que se repiten; después de
  la primera vez, las responde la caché.
- **variada:** combinaciones al azar de 1 a 3 términos del vocabulario del
  corpus, con distintos ``top_k``; casi siempre son fallos de caché.
- **inexistente:** términos que no están en el índice.

Mide la latencia desde el cliente y reporta p50, p95, p99, máximo y
throughput por tipo. Las recargas se reportan aparte: tardan segundos y,
mezcladas en el total, ocultarían el p99 de la búsqueda. Mientras una
recarga corre, las consultas siguen respondiendo con el índice anterior,
pero compiten con ella por la CPU.

Comandos (con la API levantada)::

    python src/generar_trafico.py --duracion 60 --concurrencia 50
    python src/generar_trafico.py --solicitudes 2000 --mezcla 60,30,10
    python src/generar_trafico.py --duracion 120 --reindexar-cada 30
"""

import argparse
import asyncio
import json
import random
import statistics
import time
from pathlib import Path

import httpx2

from baseline import VOCABULARIO


BASE_DIR = Path(__file__).resolve().parent.parent
TIPOS = ("repetida", "variada", "inexistente")
CONSULTAS_REPETIDAS = (
    "algoritmo",
    "python datos",
    "memoria",
    "indice consulta",
    "red servidor",
)
CONSULTAS_INEXISTENTES = ("zzzinexistente", "xyzzy", "qwertyuiop", "inexistente123")


def elegir_consulta(azar, mezcla):
    """
    Elige el tipo de consulta según la mezcla y arma sus parámetros.

    :param azar: Generador de números al azar.
    :type azar: random.Random
    :param mezcla: Peso de cada tipo: ``(repetida, variada, inexistente)``.
    :type mezcla: tuple[float, float, float]
    :return: Tupla ``(tipo, consulta, top_k)``.
    :rtype: tuple[str, str, int]
    """
    tipo = azar.choices(TIPOS, weights=mezcla)[0]

    if tipo == "repetida":
        return tipo, azar.choice(CONSULTAS_REPETIDAS), 10

    if tipo == "variada":
        terminos = azar.sample(VOCABULARIO, azar.randint(1, 3))
        return tipo, " ".join(terminos), azar.randint(1, 20)

    return tipo, azar.choice(CONSULTAS_INEXISTENTES), 10


async def _pedir(cliente, metodo, ruta, **opciones):
    """
    Hace un pedido y mide cuánto tarda.

    :param cliente: Cliente HTTP.
    :type cliente: httpx2.AsyncClient
    :param metodo: Método HTTP, por ejemplo ``"GET"``.
    :type metodo: str
    :param ruta: Ruta del endpoint, por ejemplo ``"/buscar"``.
    :type ruta: str
    :param opciones: Se pasan tal cual a ``cliente.request``.
    :return: Tupla ``(estado, milisegundos, respuesta)``; el estado es
        ``None`` si no hubo respuesta (por ejemplo, servidor caído).
    :rtype: tuple[int | None, float, httpx2.Response | None]
    """
    inicio = time.perf_counter()
    try:
        respuesta = await cliente.request(metodo, ruta, **opciones)
    except httpx2.HTTPError:
        return None, (time.perf_counter() - inicio) * 1000, None

    return respuesta.status_code, (time.perf_counter() - inicio) * 1000, respuesta


async def _consultar(cliente, carga):
    """
    Consulta sin parar hasta que se acaben las solicitudes o el tiempo.

    :param cliente: Cliente HTTP.
    :type cliente: httpx2.AsyncClient
    :param carga: Estado compartido de la corrida.
    :type carga: dict
    """
    while True:
        if carga["plan"] is not None:
            siguiente = next(carga["plan"], None)
            if siguiente is None:
                return
        elif time.perf_counter() >= carga["fin"]:
            return
        else:
            siguiente = elegir_consulta(carga["azar"], carga["mezcla"])

        tipo, consulta, top_k = siguiente
        estado, ms, respuesta = await _pedir(
            cliente, "GET", "/buscar", params={"q": consulta, "top_k": top_k}
        )
        total = respuesta.json().get("total") if estado == 200 else None
        carga["mediciones"].append(
            {"tipo": tipo, "estado": estado, "ms": ms, "total": total}
        )


async def _reindexar(cliente, carga, cada, terminado):
    """
    Pide ``POST /reindexar`` cada ``cada`` segundos hasta que termine la carga.

    :param cliente: Cliente HTTP.
    :type cliente: httpx2.AsyncClient
    :param carga: Estado compartido de la corrida.
    :type carga: dict
    :param cada: Segundos entre recargas.
    :type cada: float
    :param terminado: Se marca cuando terminan las consultas.
    :type terminado: asyncio.Event
    """
    while True:
        try:
            await asyncio.wait_for(terminado.wait(), timeout=cada)
            return
        except TimeoutError:
            estado, ms, _ = await _pedir(cliente, "POST", "/reindexar")
            carga["mediciones"].append(
                {"tipo": "reindexar", "estado": estado, "ms": ms, "total": None}
            )


async def ejecutar_carga(
    cliente,
    solicitudes=None,
    duracion=None,
    concurrencia=10,
    mezcla=(60, 30, 10),
    semilla=None,
    reindexar_cada=None,
):
    """
    Corre la carga y devuelve una medición por pedido.

    Con ``solicitudes``, los pedidos se arman de antemano a partir de la
    semilla, así dos corridas con la misma semilla piden lo mismo. Con
    ``duracion``, los usuarios consultan hasta que se acaba el tiempo.

    :param cliente: Cliente HTTP apuntando a la API.
    :type cliente: httpx2.AsyncClient
    :param solicitudes: Cantidad total de consultas.
    :type solicitudes: int | None
    :param duracion: Segundos de carga, si no se fija ``solicitudes``.
    :type duracion: float | None
    :param concurrencia: Usuarios que consultan a la vez.
    :type concurrencia: int
    :param mezcla: Peso de cada tipo: ``(repetida, variada, inexistente)``.
    :type mezcla: tuple[float, float, float]
    :param semilla: Semilla para que la corrida sea reproducible.
    :type semilla: int | None
    :param reindexar_cada: Si se indica, pide una recarga cada tantos
        segundos.
    :type reindexar_cada: float | None
    :return: Una medición por pedido, con su tipo, estado, milisegundos
        y total de coincidencias.
    :rtype: list[dict]
    :raises ValueError: Si no se indica ni ``solicitudes`` ni ``duracion``.
    """
    if solicitudes is None and duracion is None:
        raise ValueError("hay que indicar solicitudes o duracion")

    azar = random.Random(semilla)  # nosec B311
    plan = None
    if solicitudes is not None:
        plan = iter([elegir_consulta(azar, mezcla) for _ in range(solicitudes)])

    carga = {
        "plan": plan,
        "fin": time.perf_counter() + (duracion or 0),
        "azar": azar,
        "mezcla": mezcla,
        "mediciones": [],
    }
    terminado = asyncio.Event()
    recargas = None
    if reindexar_cada:
        recargas = asyncio.create_task(
            _reindexar(cliente, carga, reindexar_cada, terminado)
        )

    await asyncio.gather(*(_consultar(cliente, carga) for _ in range(concurrencia)))
    terminado.set()
    if recargas:
        await recargas

    return carga["mediciones"]


def percentiles(valores):
    """
    Resume una lista de latencias.

    :param valores: Latencias en milisegundos.
    :type valores: list[float]
    :return: ``p50``, ``p95``, ``p99``, ``max`` y ``media``; vacío si no
        hay valores.
    :rtype: dict[str, float]
    """
    if not valores:
        return {}

    if len(valores) == 1:
        cortes = valores * 99
    else:
        cortes = statistics.quantiles(valores, n=100, method="inclusive")

    return {
        "p50": cortes[49],
        "p95": cortes[94],
        "p99": cortes[98],
        "max": max(valores),
        "media": statistics.fmean(valores),
    }


def resumir(mediciones, segundos):
    """
    Agrupa las mediciones en totales y por tipo.

    El total cuenta solo las consultas: las recargas tienen su propio grupo.
    Los percentiles se calculan sobre los pedidos que respondieron 200.

    :param mediciones: Las mediciones de :func:`ejecutar_carga`.
    :type mediciones: list[dict]
    :param segundos: Duración de la corrida, para el throughput.
    :type segundos: float
    :return: ``{"total": ..., "por_tipo": {tipo: ...}}``.
    :rtype: dict
    """

    def bloque(grupo):
        exitosas = [medicion["ms"] for medicion in grupo if medicion["estado"] == 200]
        return {
            "solicitudes": len(grupo),
            "errores": sum(1 for medicion in grupo if medicion["estado"] != 200),
            "por_segundo": len(grupo) / segundos if segundos else 0.0,
            **percentiles(exitosas),
        }

    tipos = sorted({medicion["tipo"] for medicion in mediciones})
    consultas = [medicion for medicion in mediciones if medicion["tipo"] != "reindexar"]

    return {
        "total": bloque(consultas),
        "por_tipo": {
            tipo: bloque([m for m in mediciones if m["tipo"] == tipo]) for tipo in tipos
        },
    }


def _imprimir(resumen, segundos):
    """
    Muestra el resumen como tabla.

    :param resumen: Resultado de :func:`resumir`.
    :type resumen: dict
    :param segundos: Duración de la corrida.
    :type segundos: float
    """
    print(f"\n{segundos:.1f} s · {resumen['total']['por_segundo']:.1f} consultas/s")
    print(
        f"{'tipo':12} {'pedidos':>8} {'errores':>8} "
        f"{'p50 ms':>9} {'p95 ms':>9} {'p99 ms':>9} {'max ms':>9}"
    )
    filas = [("total", resumen["total"]), *resumen["por_tipo"].items()]
    for nombre, datos in filas:
        print(
            f"{nombre:12} {datos['solicitudes']:>8} {datos['errores']:>8} "
            + " ".join(
                f"{datos.get(clave, 0):>9.2f}" for clave in ("p50", "p95", "p99", "max")
            )
        )


def main():
    """Corre la carga contra la API indicada y guarda el resumen en JSON."""
    parser = argparse.ArgumentParser(description="Generador de carga para la API")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--solicitudes", type=int, default=None)
    parser.add_argument("--duracion", type=float, default=None)
    parser.add_argument("--concurrencia", type=int, default=20)
    parser.add_argument(
        "--mezcla",
        default="60,30,10",
        help="peso de las consultas repetidas, variadas e inexistentes",
    )
    parser.add_argument("--reindexar-cada", type=float, default=None)
    parser.add_argument("--semilla", type=int, default=None)
    parser.add_argument(
        "--salida", type=Path, default=BASE_DIR / "profiles" / "trafico.json"
    )
    args = parser.parse_args()

    if args.solicitudes is None and args.duracion is None:
        args.duracion = 30.0

    mezcla = tuple(float(peso) for peso in args.mezcla.split(","))

    async def correr():
        async with httpx2.AsyncClient(
            base_url=args.url,
            timeout=httpx2.Timeout(120.0),
            limits=httpx2.Limits(max_connections=args.concurrencia),
        ) as cliente:
            return await ejecutar_carga(
                cliente,
                solicitudes=args.solicitudes,
                duracion=args.duracion,
                concurrencia=args.concurrencia,
                mezcla=mezcla,
                semilla=args.semilla,
                reindexar_cada=args.reindexar_cada,
            )

    inicio = time.perf_counter()
    mediciones = asyncio.run(correr())
    segundos = time.perf_counter() - inicio

    resumen = resumir(mediciones, segundos)
    resumen["segundos"] = segundos
    resumen["opciones"] = {
        clave: str(valor) if isinstance(valor, Path) else valor
        for clave, valor in vars(args).items()
    }

    _imprimir(resumen, segundos)

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(resumen, indent=2), encoding="utf-8")
    print(f"\nResumen guardado en {args.salida}")


if __name__ == "__main__":
    main()
