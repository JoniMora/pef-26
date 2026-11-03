"""
Controles de rendimiento del CI: benchmark, profiling y memoria.

Los tres miden sobre el mismo corpus sintético, generado con semilla fija, y
dejan sus reportes en ``reportes/``. Los criterios de rechazo y cómo se fijaron
la tolerancia y los límites están en ``docs/rendimiento.md``. Comandos (desde la
raíz del repositorio)::

    python scripts/control_rendimiento.py benchmark --base origin/master
    python scripts/control_rendimiento.py profiling
    python scripts/control_rendimiento.py memoria
"""

import argparse
import contextlib
import io
import json
import os
import random
import subprocess  # nosec B404
import sys
import tarfile
import tempfile
import tracemalloc
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]
SRC = RAIZ / "src"
REPORTES = RAIZ / "reportes"

sys.path.insert(0, str(SRC))

# Estos imports van después del sys.path.insert: el script se ejecuta
# directamente y necesita src/ en el path para encontrar los módulos.
import optimizado  # noqa: E402
import perfilado  # noqa: E402
from baseline import generar_corpus_prueba  # noqa: E402


DOCUMENTOS = 2000
SEMILLA = 2026

RONDAS = 3
TOLERANCIA = 0.25

LIMITES_MB = {
    "inicial": 100.0,
    "estructura": 100.0,
    "algoritmo": 100.0,
    "concurrencia": 100.0,
    "final": 100.0,
}

MB = 1024 * 1024


def generar_corpus(directorio):
    """
    Genera el corpus de los controles, siempre con los mismos documentos.

    :param directorio: Directorio donde se escriben los documentos.
    :type directorio: pathlib.Path
    """
    random.seed(SEMILLA)

    with contextlib.redirect_stdout(io.StringIO()):
        generar_corpus_prueba(DOCUMENTOS, str(directorio))


def guardar_reporte(nombre, datos):
    """
    Guarda un reporte en JSON en ``reportes/``.

    :param nombre: Nombre del archivo.
    :type nombre: str
    :param datos: Contenido del reporte.
    :type datos: dict
    """
    REPORTES.mkdir(exist_ok=True)
    (REPORTES / nombre).write_text(
        json.dumps(datos, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def agregar_al_resumen(texto):
    """
    Imprime un texto y, en el CI, lo suma al resumen de la corrida.

    :param texto: Texto en Markdown.
    :type texto: str
    """
    print(texto)

    destino = os.environ.get("GITHUB_STEP_SUMMARY")

    if destino:
        with Path(destino).open("a", encoding="utf-8") as archivo:
            archivo.write(texto + "\n")


# ============================================================
# BENCHMARK
# ============================================================


def extraer_src(referencia, destino):
    """
    Extrae el ``src/`` de un commit, sin tocar el árbol de trabajo.

    :param referencia: Commit o rama.
    :type referencia: str
    :param destino: Directorio donde se extrae.
    :type destino: pathlib.Path
    :return: El ``src/`` extraído.
    :rtype: pathlib.Path
    :raises subprocess.CalledProcessError: Si la referencia no existe.
    """
    archivo = subprocess.run(  # nosec B603 B607
        ["git", "archive", referencia, "src"],
        cwd=RAIZ,
        capture_output=True,
        check=True,
    ).stdout

    with tarfile.open(fileobj=io.BytesIO(archivo)) as tar:
        tar.extractall(destino, filter="data")

    return destino / "src"


def correr_benchmarks(src, corpus, salida):
    """
    Corre la suite de ``benchmarks/`` contra un ``src/``.

    Siempre es la suite de la rama actual: la rama base puede no tenerla, y las
    dos mediciones tienen que hacer lo mismo.

    :param src: Directorio con el código a medir.
    :type src: pathlib.Path
    :param corpus: Directorio del corpus.
    :type corpus: pathlib.Path
    :param salida: Dónde guardar el JSON de pytest-benchmark.
    :type salida: pathlib.Path
    :return: Por benchmark, su menor tiempo en segundos.
    :rtype: dict[str, float]
    """
    proceso = subprocess.run(  # nosec B603
        [
            sys.executable,
            "-m",
            "pytest",
            "benchmarks",
            "--benchmark-only",
            f"--benchmark-json={salida}",
            "-o",
            f"pythonpath={src}",
            "-p",
            "no:cacheprovider",
            "-q",
        ],
        cwd=RAIZ,
        env={
            **os.environ,
            "BENCHMARK_SRC": str(src),
            "BENCHMARK_CORPUS": str(corpus),
            # Mismo orden de sets y dicts de texto en todas las corridas.
            "PYTHONHASHSEED": "0",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    if proceso.returncode != 0:
        sys.exit(f"El benchmark falló contra {src}:\n{proceso.stdout[-2000:]}")

    resultados = json.loads(salida.read_text(encoding="utf-8"))

    return {
        benchmark["name"]: benchmark["stats"]["min"]
        for benchmark in resultados["benchmarks"]
    }


def medir_alternado(src_base, src_actual, corpus, destino, rondas=RONDAS):
    """
    Mide los dos lados alternados y conserva el mejor tiempo de cada benchmark.

    Alternar reparte la deriva de la máquina entre los dos lados. El mínimo es
    la estimación más estable en un runner compartido: el ruido solo suma tiempo.

    :param src_base: Código de la rama base.
    :type src_base: pathlib.Path
    :param src_actual: Código de la rama actual.
    :type src_actual: pathlib.Path
    :param corpus: Directorio del corpus.
    :type corpus: pathlib.Path
    :param destino: Dónde guardar los JSON de cada corrida.
    :type destino: pathlib.Path
    :param rondas: Veces que se mide cada lado.
    :type rondas: int
    :return: Tupla ``(base, actual)``: por benchmark, su mejor tiempo en segundos.
    :rtype: tuple[dict[str, float], dict[str, float]]
    """
    lados = {"base": (src_base, {}), "actual": (src_actual, {})}

    for ronda in range(rondas):
        orden = ("base", "actual") if ronda % 2 == 0 else ("actual", "base")

        for lado in orden:
            src, mejores = lados[lado]
            salida = destino / f"{lado}-{ronda + 1}.json"

            for nombre, tiempo in correr_benchmarks(src, corpus, salida).items():
                mejores[nombre] = min(tiempo, mejores.get(nombre, tiempo))

            print(f"  ronda {ronda + 1}/{rondas}: {lado}", flush=True)

    return lados["base"][1], lados["actual"][1]


def comparar(base, actual, tolerancia):
    """
    Compara los tiempos de los dos lados.

    :param base: Por benchmark, su tiempo en la rama base.
    :type base: dict[str, float]
    :param actual: Por benchmark, su tiempo en la rama actual.
    :type actual: dict[str, float]
    :param tolerancia: Aumento relativo que se acepta; 0,25 es un 25 %.
    :type tolerancia: float
    :return: Una fila por benchmark, con la razón actual/base y si es una
        regresión.
    :rtype: list[dict]
    """
    return [
        {
            "benchmark": nombre,
            "base_ms": base[nombre] * 1000,
            "actual_ms": actual[nombre] * 1000,
            "razon": actual[nombre] / base[nombre],
            "regresion": actual[nombre] / base[nombre] > 1 + tolerancia,
        }
        for nombre in sorted(actual)
    ]


def tabla_benchmark(filas, tolerancia):
    """
    Arma la tabla de resultados del benchmark en Markdown.

    :param filas: Resultado de :func:`comparar`.
    :type filas: list[dict]
    :param tolerancia: Aumento relativo que se acepta.
    :type tolerancia: float
    :return: El veredicto y un benchmark por fila.
    :rtype: str
    """
    rechazado = any(fila["regresion"] for fila in filas)
    veredicto = "Rechazado" if rechazado else "Aprobado"

    return "\n".join(
        [
            f"## Benchmark contra la rama base: {veredicto}",
            "",
            f"Tolerancia: {tolerancia:.0%}.",
            "",
            "| Benchmark | Base (ms) | Actual (ms) | Razón | Resultado |",
            "| --- | ---: | ---: | ---: | --- |",
            *(
                f"| {fila['benchmark']} | {fila['base_ms']:.4f} "
                f"| {fila['actual_ms']:.4f} | {fila['razon']:.3f} "
                f"| {'Regresión' if fila['regresion'] else 'Dentro de la tolerancia'} |"
                for fila in filas
            ),
        ]
    )


def control_benchmark(referencia):
    """
    Compara los benchmarks contra una rama base y rechaza si hay una regresión.

    :param referencia: Commit o rama contra la que se compara.
    :type referencia: str
    """
    destino = REPORTES / "benchmark"
    destino.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temporal:
        src_base = extraer_src(referencia, Path(temporal))
        corpus = Path(temporal) / "corpus"
        generar_corpus(corpus)

        base, actual = medir_alternado(src_base, SRC, corpus, destino)

    filas = comparar(base, actual, TOLERANCIA)
    guardar_reporte(
        "benchmark.json",
        {
            "base": referencia,
            "tolerancia": TOLERANCIA,
            "rondas": RONDAS,
            "benchmarks": filas,
        },
    )
    agregar_al_resumen(tabla_benchmark(filas, TOLERANCIA))

    if any(fila["regresion"] for fila in filas):
        sys.exit("El benchmark detectó una regresión frente a la rama base.")


# ============================================================
# PROFILING
# ============================================================


def control_profiling():
    """Perfila cada versión por función y por línea, y guarda los reportes."""
    destino = REPORTES / "profiling"
    destino.mkdir(parents=True, exist_ok=True)
    perfilado.DIR_PERFILES = destino

    with tempfile.TemporaryDirectory() as corpus:
        generar_corpus(Path(corpus))

        funciones = perfilado.perfilar_cprofile(Path(corpus), perfilado.VERSIONES)
        lineas = perfilado.perfilar_line(Path(corpus), perfilado.VERSIONES)

    guardar_reporte(
        "profiling/ranking.json",
        {
            "cprofile": funciones,
            "line_profiler": {
                version: {
                    clave: dato for clave, dato in datos.items() if clave != "texto"
                }
                for version, datos in lineas.items()
            },
        },
    )

    agregar_al_resumen(tabla_ranking("algoritmo", funciones["algoritmo"]["top"]))

    if not all(datos["top"] for datos in funciones.values()):
        sys.exit("El perfil de alguna versión quedó vacío.")


def tabla_ranking(version, filas):
    """
    Arma el ranking de funciones de una versión en Markdown.

    :param version: Versión perfilada.
    :type version: str
    :param filas: Ranking de cProfile.
    :type filas: list[dict]
    :return: Una función por fila.
    :rtype: str
    """
    return "\n".join(
        [
            f"## Funciones con más tiempo acumulado: {version}",
            "",
            "| Función | Llamadas | Propio (s) | Acumulado (s) |",
            "| --- | ---: | ---: | ---: |",
            *(
                f"| `{fila['funcion']}` | {fila['llamadas']} "
                f"| {fila['tottime']:.3f} | {fila['cumtime']:.3f} |"
                for fila in filas
            ),
        ]
    )


# ============================================================
# MEMORIA
# ============================================================


def medir_picos(corpus):
    """
    Mide el pico de memoria de cada versión, en un proceso limpio.

    :param corpus: Directorio del corpus.
    :type corpus: pathlib.Path
    :return: Por versión, su pico de ``tracemalloc`` y su RSS, en MB.
    :rtype: dict[str, dict[str, float]]
    """
    picos = {}

    for version in perfilado.VERSIONES:
        medicion = perfilado._medir_en_subproceso(
            version, corpus, 1, con_tracemalloc=True
        )
        picos[version] = {
            "tracemalloc_mb": medicion["tracemalloc_mb"],
            "rss_mb": medicion["rss_mb"],
        }

    return picos


def asignaciones_relevantes(corpus, cantidad=10):
    """
    Lista las líneas que retienen más memoria al indexar y consultar.

    :param corpus: Directorio del corpus.
    :type corpus: pathlib.Path
    :param cantidad: Cantidad de líneas.
    :type cantidad: int
    :return: Por línea, la memoria retenida en MB y la cantidad de bloques.
    :rtype: list[dict]
    """
    tracemalloc.start()

    indice, archivos = optimizado.construir_indice(corpus)
    optimizado.Buscador(indice, archivos).buscar(perfilado.CONSULTA)
    instantanea = tracemalloc.take_snapshot()

    tracemalloc.stop()

    return [
        {
            "linea": f"{Path(estadistica.traceback[0].filename).name}:"
            f"{estadistica.traceback[0].lineno}",
            "mb": estadistica.size / MB,
            "bloques": estadistica.count,
        }
        for estadistica in instantanea.statistics("lineno")[:cantidad]
    ]


def versiones_excedidas(picos, limites):
    """
    Lista las versiones que superan su límite de memoria.

    :param picos: Resultado de :func:`medir_picos`.
    :type picos: dict[str, dict[str, float]]
    :param limites: Límite en MB por versión.
    :type limites: dict[str, float]
    :return: Las versiones cuyo pico de ``tracemalloc`` supera el límite.
    :rtype: list[str]
    """
    return [
        version
        for version, pico in picos.items()
        if pico["tracemalloc_mb"] > limites[version]
    ]


def tabla_memoria(picos, limites):
    """
    Arma la tabla de resultados de memoria en Markdown.

    :param picos: Resultado de :func:`medir_picos`.
    :type picos: dict[str, dict[str, float]]
    :param limites: Límite en MB por versión.
    :type limites: dict[str, float]
    :return: El veredicto y una versión por fila.
    :rtype: str
    """
    excedidas = versiones_excedidas(picos, limites)
    veredicto = "Rechazado" if excedidas else "Aprobado"

    return "\n".join(
        [
            f"## Memoria: {veredicto}",
            "",
            "| Versión | Pico de tracemalloc (MB) | Límite (MB) | RSS (MB) |",
            "| --- | ---: | ---: | ---: |",
            *(
                f"| {version} | {pico['tracemalloc_mb']:.3f} "
                f"| {limites[version]:.3f} | {pico['rss_mb']:.1f} |"
                for version, pico in picos.items()
            ),
        ]
    )


def control_memoria():
    """Mide el pico de cada versión y rechaza si alguna supera su límite."""
    with tempfile.TemporaryDirectory() as temporal:
        corpus = Path(temporal)
        generar_corpus(corpus)

        picos = medir_picos(corpus)
        asignaciones = asignaciones_relevantes(corpus)

    guardar_reporte(
        "memoria.json",
        {"limites_mb": LIMITES_MB, "picos": picos, "asignaciones": asignaciones},
    )
    agregar_al_resumen(tabla_memoria(picos, LIMITES_MB))

    excedidas = versiones_excedidas(picos, LIMITES_MB)

    if excedidas:
        sys.exit(f"Versiones sobre su límite de memoria: {', '.join(excedidas)}")


def main():
    """Corre el control pedido por línea de comandos."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    controles = parser.add_subparsers(dest="control", required=True)

    benchmark = controles.add_parser("benchmark", help="Compara contra la rama base")
    benchmark.add_argument("--base", required=True, help="Commit o rama de referencia")
    controles.add_parser("profiling", help="Perfila por función y por línea")
    controles.add_parser("memoria", help="Controla el pico de memoria")

    args = parser.parse_args()

    if args.control == "benchmark":
        control_benchmark(args.base)
    elif args.control == "profiling":
        control_profiling()
    else:
        control_memoria()


if __name__ == "__main__":
    main()
