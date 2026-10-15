"""
Perfilado y medición del Buscador Eficiente de Información.

Orquestador de las cinco herramientas exigidas por la consigna
(``cProfile``, ``line_profiler``, ``memory_profiler``, ``Scalene`` y
``py-spy``) más el banco de pruebas que produce la tabla comparativa
obligatoria.

Cada versión se mide en un **proceso limpio** —el orquestador se
invoca a sí mismo con ``--medir``— para que el pico de RSS sea
atribuible y no arrastre la memoria de las versiones anteriores.
Las versiones se miden **alternadas** dentro de cada ronda: medirlas
en bloque contamina el resultado con el estado del page cache.

Las cinco versiones de la tabla se mapean sobre los tres scripts:

- ``inicial``: ``baseline.py``, búsqueda secuencial O(n·m).
- ``estructura``: índice invertido + ``set``, ranking con ``sorted()`` completo.
- ``algoritmo``: ``optimizado.py``, heap top-k + ``QueryCache``.
- ``concurrencia``: ``concurrente.py``, indexación MapReduce multiproceso.
- ``final``: concurrencia + caché de consultas caliente.

Comandos (requieren el venv con las herramientas instaladas)::

    .venv/bin/python src/perfilado.py --todo
    .venv/bin/python src/perfilado.py --comparativa
    .venv/bin/python src/perfilado.py --escalabilidad
    .venv/bin/python src/perfilado.py --cprofile --line --memoria
    .venv/bin/python src/perfilado.py --scalene --pyspy
    .venv/bin/python src/perfilado.py --graficos --reporte
"""

import argparse
import html
import json
import math
import os
import platform
import statistics
import subprocess  # nosec B404
import sys
import time
import tracemalloc
from pathlib import Path


try:
    import resource  # Unix (macOS, Linux)
except ImportError:
    resource = None  # Windows

# Con la salida redirigida a un archivo, Python usa la codificación
# local (cp1252 en Windows en español) y cualquier símbolo fuera de
# ese juego —los ✓ y ⚠ del progreso— aborta la corrida entera con
# UnicodeEncodeError. Forzar UTF-8 lo evita; `replace` es la red por
# si el destino tampoco lo soporta.
for _flujo in (sys.stdout, sys.stderr):
    if hasattr(_flujo, "reconfigure"):
        try:
            _flujo.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Estos imports van después del sys.path.insert: el script se ejecuta
# directamente y necesita src/ en el path para encontrar los módulos.
import baseline  # noqa: E402
import concurrente  # noqa: E402
import optimizado  # noqa: E402
from core import procesamiento_texto  # noqa: E402


# ============================================================
# CONFIGURACIÓN
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = Path(__file__).resolve().parent
DIR_PERFILES = BASE_DIR / "profiles"
DIR_DATOS = BASE_DIR / "data"
CORPUS_PRINCIPAL = DIR_DATOS / "corpus"

CONSULTA = "algoritmo"
TOP_K = 10

# El corpus de 50.000 ya existe en data/corpus; los demás se generan.
TAMANOS = (5000, 50000)

VERSIONES = ("inicial", "estructura", "algoritmo", "concurrencia", "final")

ETIQUETAS = {
    "inicial": "Implementación inicial",
    "estructura": "Estructura optimizada",
    "algoritmo": "Algoritmo optimizado",
    "concurrencia": "Concurrencia/paralelismo",
    "final": "Versión final",
}

OBSERVACIONES = {
    "inicial": "Baseline — escaneo secuencial O(n·m), relee el corpus en cada consulta",
    "estructura": (
        "Mejora de búsqueda — índice invertido + set, ranking con sorted() O(r·log r)"
    ),
    "algoritmo": "Mejor escalabilidad — heap top-k O(r·log k) + caché LRU de consultas",
    "concurrencia": "Evaluar overhead — indexación MapReduce sobre ProcessPoolExecutor",
    "final": "Resultado final — indexación paralela + caché caliente",
}

# Versiones que construyen índice (las que pagan el costo único).
CON_INDICE = ("estructura", "algoritmo", "concurrencia", "final")


def corpus_de(tamano):
    """
    Directorio del corpus para un tamaño dado.

    El de 50.000 documentos es ``data/corpus``; los demás viven en
    ``data/corpus_<tamaño>``.

    :param tamano: Cantidad de documentos del corpus.
    :type tamano: int
    :return: Ruta del directorio, exista o no.
    :rtype: pathlib.Path
    """
    if tamano == 50000:
        return CORPUS_PRINCIPAL
    return DIR_DATOS / f"corpus_{tamano}"


def _carga_del_sistema():
    """
    Carga promedio del último minuto, o None si el SO no la expone.

    Windows no tiene `getloadavg`; ahí la guarda simplemente no aplica.

    :return: Carga promedio del último minuto, o ``None`` si el sistema operativo no la
        expone.
    :rtype: float | None
    """
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return None


def _rss_mb():
    """
    Pico de RSS del proceso actual, en MB.

    En Unix se usa `ru_maxrss`, que viene en bytes en macOS y en
    kilobytes en Linux. Windows no tiene el módulo `resource`: ahí se
    recurre a `psutil`, cuyo `peak_wset` es el equivalente exacto.

    :return: Pico de RSS en MB, o ``None`` si no hay forma de leerlo (Windows sin
        ``psutil``).
    :rtype: float | None
    """
    if resource is not None:
        pico = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return pico / (1024 * 1024) if sys.platform == "darwin" else pico / 1024

    try:
        import psutil
    except ImportError:
        return None

    memoria = psutil.Process().memory_info()

    # peak_wset solo existe en Windows; rss es el piso razonable.
    return getattr(memoria, "peak_wset", memoria.rss) / (1024 * 1024)


# ============================================================
# RANKING PREVIO A LA OPTIMIZACIÓN ALGORÍTMICA
# ============================================================


def _rankear_sorted(indice, terminos, candidatos, top_k, total_docs):
    """
    Ranking de la etapa "estructura optimizada", previa al heap.

    En esa etapa ya hay índice invertido y set, pero todavía no hay
    heap ni caché. Materializa un dict de scores de tamaño O(r) y
    ordena la lista completa en O(r · log r). Es la implementación que
    `rankear()` reemplazó, y se conserva aquí para que la tabla
    comparativa pueda medir el efecto aislado del heap.

    :param indice: Índice invertido: término -> {doc_id: frecuencia}.
    :type indice: dict[str, dict[int, int]]
    :param terminos: Términos normalizados de la consulta.
    :type terminos: tuple[str, ...]
    :param candidatos: Documentos que contienen todos los términos.
    :type candidatos: set[int]
    :param top_k: Cantidad máxima de documentos a devolver.
    :type top_k: int
    :param total_docs: Cantidad de documentos del corpus, para el IDF.
    :type total_docs: int
    :return: Pares ``(doc_id, score)`` de mayor a menor score; los empates, por doc_id
        creciente.
    :rtype: list[tuple[int, float]]
    """
    if not candidatos or top_k <= 0:
        return []

    scores = {}

    for doc_id in candidatos:
        score = 0.0

        for termino in terminos:
            postings = indice[termino]
            idf = math.log(total_docs / len(postings))
            score += postings.get(doc_id, 0) * idf

        scores[doc_id] = score

    ordenados = sorted(scores.items(), key=lambda par: (-par[1], par[0]))

    return ordenados[:top_k]


# ============================================================
# MEDICIÓN DE UNA VERSIÓN (se ejecuta en un proceso limpio)
# ============================================================


def medir_version(version, corpus_dir, repeticiones, con_tracemalloc=False):
    """
    Mide una versión y devuelve sus métricas.

    `con_tracemalloc` está apagado por defecto **a propósito**:
    `tracemalloc` es un perfilador y encarece entre dos y tres veces
    el código que instrumenta, además de sumar sus propias tablas al
    RSS. Cronometrar con él activo inflaba todos los tiempos de la
    tabla comparativa. La atribución de memoria se hace en una
    pasada aparte, que no se cronometra.

    :param version: Versión a medir, una de ``VERSIONES``.
    :type version: str
    :param corpus_dir: Directorio del corpus.
    :type corpus_dir: pathlib.Path
    :param repeticiones: Cantidad de consultas que se cronometran.
    :type repeticiones: int
    :param con_tracemalloc: Si se mide además el pico de memoria con ``tracemalloc``.
    :type con_tracemalloc: bool
    :return: Métricas de la versión: tiempo de indexación, tiempo de consulta (mediana,
        mínimo y máximo), RSS, pico de ``tracemalloc`` y total de coincidencias.
    :rtype: dict
    """
    if con_tracemalloc:
        tracemalloc.start()

    indexacion_ms = None
    tiempos = []

    if version == "inicial":
        # Sin índice: cada consulta relee el corpus completo.
        for _ in range(repeticiones):
            inicio = time.perf_counter()
            resultados = baseline.busqueda_secuencial(str(corpus_dir), CONSULTA)
            tiempos.append((time.perf_counter() - inicio) * 1000)

        coincidencias = len(resultados)

        # Generador, no lista: materializar 50.000 Path solo para
        # contarlos agregaba decenas de MB al pico que se reporta.
        documentos = sum(1 for _ in corpus_dir.glob("*.txt"))

    else:
        constructor = (
            concurrente.construir_indice
            if version in ("concurrencia", "final")
            else optimizado.construir_indice
        )

        inicio = time.perf_counter()
        indice, archivos = constructor(corpus_dir)
        indexacion_ms = (time.perf_counter() - inicio) * 1000

        documentos = len(archivos)

        terminos = optimizado.normalizar_consulta(CONSULTA)

        if version == "estructura":
            for _ in range(repeticiones):
                inicio = time.perf_counter()
                candidatos = optimizado.buscar(indice, terminos)
                resultados = _rankear_sorted(
                    indice, terminos, candidatos, TOP_K, len(archivos)
                )
                tiempos.append((time.perf_counter() - inicio) * 1000)

            coincidencias = len(candidatos)

        else:
            buscador = optimizado.Buscador(indice, archivos)

            if version == "final":
                # Caché caliente: la primera consulta la puebla y no se mide.
                buscador.buscar(CONSULTA, TOP_K)

            for _ in range(repeticiones):
                if version != "final":
                    # Caché forzada a fallo: mide el costo real de resolver.
                    buscador.cache = optimizado.QueryCache(1024)

                inicio = time.perf_counter()
                coincidencias, resultados = buscador.buscar(CONSULTA, TOP_K)
                tiempos.append((time.perf_counter() - inicio) * 1000)

    if con_tracemalloc:
        _, pico_tracemalloc = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        tracemalloc_mb = pico_tracemalloc / (1024 * 1024)
    else:
        tracemalloc_mb = None

    return {
        "version": version,
        "corpus": str(corpus_dir),
        "documentos": documentos,
        "indexacion_ms": indexacion_ms,
        "consulta_ms": statistics.median(tiempos),
        "consulta_min_ms": min(tiempos),
        "consulta_max_ms": max(tiempos),
        "repeticiones": repeticiones,
        "tracemalloc_mb": tracemalloc_mb,
        "rss_mb": _rss_mb(),
        "coincidencias": coincidencias,
    }


# ============================================================
# ORQUESTACIÓN EN PROCESOS LIMPIOS
# ============================================================

MARCA_JSON = "__JSON__"


def _medir_en_subproceso(
    version, corpus_dir, repeticiones, con_tracemalloc=False, serie_memoria=False
):
    """
    Lanza `--medir` en un intérprete nuevo y recupera su JSON.

    El proceso limpio es lo que hace comparable el pico de RSS: si
    todas las versiones corrieran en el mismo intérprete, la primera
    en construir el índice fijaría el máximo para todas las demás.

    :param version: Versión a medir, una de ``VERSIONES``.
    :type version: str
    :param corpus_dir: Directorio del corpus.
    :type corpus_dir: str | pathlib.Path
    :param repeticiones: Cantidad de consultas que se cronometran.
    :type repeticiones: int
    :param con_tracemalloc: Si se mide además el pico de memoria con ``tracemalloc``.
    :type con_tracemalloc: bool
    :param serie_memoria: Si se muestrea además el RSS durante toda la corrida.
    :type serie_memoria: bool
    :return: Las métricas de :func:`medir_version` calculadas en el proceso hijo; con
        ``serie_memoria``, también la serie ``serie_mb``.
    :rtype: dict
    :raises RuntimeError: Si el proceso hijo no imprime su JSON.
    """
    orden = [
        sys.executable,
        str(SRC_DIR / "perfilado.py"),
        "--medir",
        version,
        "--directorio",
        str(corpus_dir),
        "--repeticiones",
        str(repeticiones),
    ]

    if con_tracemalloc:
        orden.append("--con-tracemalloc")

    if serie_memoria:
        orden.append("--serie-memoria")

    salida = subprocess.run(  # nosec B603
        orden,
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        check=False,
    )

    for linea in salida.stdout.splitlines():
        if linea.startswith(MARCA_JSON):
            return json.loads(linea[len(MARCA_JSON) :])

    raise RuntimeError(
        f"la medición de '{version}' no devolvió JSON\n"
        f"stdout: {salida.stdout[-800:]}\nstderr: {salida.stderr[-800:]}"
    )


def comparativa(corpus_dir, rondas, repeticiones, descartar=1):
    """
    Mide las cinco versiones alternándolas dentro de cada ronda.

    Se descartan las primeras `descartar` rondas —el page cache no
    está en régimen estacionario— y se reporta la mediana del resto.

    :param corpus_dir: Directorio del corpus.
    :type corpus_dir: pathlib.Path
    :param rondas: Rondas que se resumen, sin contar las descartadas.
    :type rondas: int
    :param repeticiones: Consultas cronometradas por versión y ronda. La línea base usa
        3, porque relee el corpus completo en cada una.
    :type repeticiones: int
    :param descartar: Rondas iniciales de calentamiento que se descartan.
    :type descartar: int
    :return: ``{"resumen": ..., "crudo": ...}``: la mediana de cada versión y todas las
        mediciones individuales.
    :rtype: dict
    """
    # Una máquina sobresuscripta invalida la medición sin avisar: los
    # tiempos salen inflados de forma despareja y aparecen resultados
    # imposibles, como que la versión paralela tarde más que la
    # secuencial usando el mismo código.
    carga = _carga_del_sistema()
    nucleos = os.cpu_count() or 1

    if carga is not None and carga > nucleos:
        print(
            f"  ⚠ ADVERTENCIA: carga del sistema {carga:.1f} sobre {nucleos} "
            f"núcleos ({carga / nucleos:.1f}× sobresuscripta).\n"
            f"    Las mediciones van a salir infladas. Cerrá el resto de los "
            f"programas y volvé a correr.",
            flush=True,
        )

    crudo = {version: [] for version in VERSIONES}

    for ronda in range(rondas + descartar):
        marca = "descartada" if ronda < descartar else "medida"
        print(f"  ronda {ronda + 1}/{rondas + descartar} ({marca})", flush=True)

        for version in VERSIONES:
            # `inicial` relee todo el corpus en cada repetición: con el
            # corpus grande, 10 repeticiones son medio minuto por ronda.
            reps = 3 if version == "inicial" else repeticiones

            medicion = _medir_en_subproceso(version, corpus_dir, reps)
            medicion["ronda"] = ronda
            medicion["descartada"] = ronda < descartar
            crudo[version].append(medicion)

            print(
                f"    {ETIQUETAS[version]:28} "
                f"consulta {medicion['consulta_ms']:9.3f} ms   "
                f"índice {(medicion['indexacion_ms'] or 0):8.1f} ms   "
                f"RSS {(medicion['rss_mb'] or 0):6.1f} MB",
                flush=True,
            )

    # La atribución de memoria va en su propia pasada: activar
    # tracemalloc durante el cronometrado contaminaría los tiempos.
    print("  pasada de memoria (tracemalloc, sin cronometrar)", flush=True)

    picos = {}

    for version in VERSIONES:
        medicion = _medir_en_subproceso(version, corpus_dir, 1, con_tracemalloc=True)
        picos[version] = medicion["tracemalloc_mb"]

    resumen = {}

    for version in VERSIONES:
        utiles = [medicion for medicion in crudo[version] if not medicion["descartada"]]

        indexaciones = [
            medicion["indexacion_ms"]
            for medicion in utiles
            if medicion["indexacion_ms"] is not None
        ]

        # En Windows sin psutil no hay lectura de RSS: la mediana se
        # calcula solo sobre las muestras que existen.
        rss = [
            medicion["rss_mb"] for medicion in utiles if medicion["rss_mb"] is not None
        ]

        resumen[version] = {
            "etiqueta": ETIQUETAS[version],
            "observacion": OBSERVACIONES[version],
            "documentos": utiles[0]["documentos"],
            "consulta_ms": statistics.median(
                medicion["consulta_ms"] for medicion in utiles
            ),
            "indexacion_ms": statistics.median(indexaciones) if indexaciones else None,
            "rss_mb": statistics.median(rss) if rss else None,
            "tracemalloc_mb": picos[version],
            "coincidencias": utiles[0]["coincidencias"],
            "rondas": len(utiles),
        }

    for version in VERSIONES:
        resumen[version]["carga_al_medir"] = carga
        resumen[version]["nucleos"] = nucleos

    return {"resumen": resumen, "crudo": crudo}


# ============================================================
# BARRIDO DE ESCALABILIDAD
# ============================================================


def asegurar_corpus(tamano):
    """
    Garantiza que exista un corpus del tamaño pedido.

    El de 50.000 es el que ya vive en data/corpus; los demás se
    generan con el mismo generador de la línea base, de modo que el
    vocabulario y la distribución sean idénticos y la única variable
    del barrido sea el volumen.

    :param tamano: Cantidad de documentos.
    :type tamano: int
    :return: Directorio del corpus, con exactamente ``tamano`` documentos. Si existía
        con otra cantidad, se regenera.
    :rtype: pathlib.Path
    """
    directorio = corpus_de(tamano)

    existentes = len(list(directorio.glob("*.txt"))) if directorio.exists() else 0

    if existentes == tamano:
        return directorio

    if existentes:
        print(
            f"  corpus_{tamano}: {existentes} documentos != {tamano}, se regenera",
            flush=True,
        )
        for archivo in directorio.glob("*.txt"):
            archivo.unlink()

    print(f"  generando corpus de {tamano} documentos...", flush=True)
    baseline.generar_corpus_prueba(tamano, str(directorio))

    return directorio


def escalabilidad(tamanos, rondas, repeticiones):
    """
    Repite la comparativa sobre corpus de tamaño creciente.

    Responde la pregunta de la consigna sobre si la mejora se
    sostiene al aumentar el volumen: una optimización que solo gana
    en corpus chicos se delata acá.

    :param tamanos: Tamaños de corpus a medir, en cantidad de documentos.
    :type tamanos: tuple[int, ...]
    :param rondas: Rondas por tamaño (ver :func:`comparativa`).
    :type rondas: int
    :param repeticiones: Consultas cronometradas por versión y ronda.
    :type repeticiones: int
    :return: El resumen de :func:`comparativa` para cada tamaño, con el tamaño como
        clave de texto.
    :rtype: dict[str, dict]
    """
    resultados = {}

    for tamano in tamanos:
        print(f"\n[escalabilidad] corpus de {tamano} documentos", flush=True)

        directorio = asegurar_corpus(tamano)

        resultados[str(tamano)] = comparativa(directorio, rondas, repeticiones)[
            "resumen"
        ]

    return resultados


# ============================================================
# HERRAMIENTA 1 — cProfile
# ============================================================


def perfilar_cprofile(corpus_dir, versiones):
    """
    Perfil determinista por función de cada versión.

    Se ejecuta en subprocesos para que el perfil no incluya al
    orquestador. Devuelve las funciones más caras por tiempo
    acumulado y deja el `.prof` para inspección con snakeviz.

    :param corpus_dir: Directorio del corpus.
    :type corpus_dir: pathlib.Path
    :param versiones: Versiones a perfilar (ver ``VERSIONES``).
    :type versiones: tuple[str, ...]
    :return: Por versión: la ruta del ``.prof``, el tiempo total instrumentado y las
        funciones más caras.
    :rtype: dict[str, dict]
    """
    import pstats

    hallazgos = {}

    for version in versiones:
        destino = DIR_PERFILES / f"cprofile-{version}.prof"

        print(f"  cProfile: {version}", flush=True)

        subprocess.run(  # nosec B603
            [
                sys.executable,
                str(SRC_DIR / "perfilado.py"),
                "--medir",
                version,
                "--directorio",
                str(corpus_dir),
                "--repeticiones",
                "1",
                "--perfil-cprofile",
                str(destino),
            ],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            check=True,
        )

        estadisticas = pstats.Stats(str(destino))
        estadisticas.sort_stats("cumulative")

        filas = []

        for func, (llamadas, _, propio, acumulado, _) in sorted(
            estadisticas.stats.items(),
            key=lambda par: par[1][3],
            reverse=True,
        )[:12]:
            archivo, linea, nombre = func

            filas.append(
                {
                    "funcion": f"{Path(archivo).name}:{linea}({nombre})",
                    "llamadas": llamadas,
                    "tottime": propio,
                    "cumtime": acumulado,
                }
            )

        hallazgos[version] = {
            "archivo": str(destino.relative_to(BASE_DIR)),
            "total_s": estadisticas.total_tt,
            "top": filas,
        }

    return hallazgos


# ============================================================
# HERRAMIENTA 2 — line_profiler
# ============================================================


def perfilar_line(corpus_dir, versiones):
    """
    Costo línea a línea de las funciones calientes.

    Corre en el propio proceso: `line_profiler` instrumenta objetos
    función y **no cruza el límite de proceso**, así que la versión
    concurrente no puede perfilarse por esta vía —sus workers son
    intérpretes separados—. Es una limitación de la herramienta, no
    del código, y queda registrada como tal.

    :param corpus_dir: Directorio del corpus.
    :type corpus_dir: pathlib.Path
    :param versiones: Versiones a perfilar (ver ``VERSIONES``).
    :type versiones: tuple[str, ...]
    :return: Por versión: la ruta del reporte y su texto, o el motivo por el que se
        omitió.
    :rtype: dict[str, dict]
    """
    from line_profiler import LineProfiler

    hallazgos = {}

    for version in versiones:
        if version in ("concurrencia", "final"):
            hallazgos[version] = {
                "omitido": "line_profiler no cruza el límite de proceso: "
                "el trabajo ocurre en los workers, no en este intérprete"
            }
            continue

        print(f"  line_profiler: {version}", flush=True)

        perfilador = LineProfiler()

        for funcion in (
            procesamiento_texto.tokenizar,
            # `stem` y `normalize` están envueltos por lru_cache: se
            # perfila la función original, no el wrapper.
            procesamiento_texto.stem.__wrapped__,
            optimizado.construir_indice,
            optimizado.buscar,
            optimizado.rankear,
            baseline.busqueda_secuencial,
            _rankear_sorted,
        ):
            perfilador.add_function(funcion)

        perfilador.runcall(medir_version, version, corpus_dir, 1)

        destino = DIR_PERFILES / f"line_profiler-{version}.txt"

        with open(destino, "w", encoding="utf-8") as salida:
            perfilador.print_stats(stream=salida, output_unit=1e-3)

        texto = destino.read_text(encoding="utf-8")

        hallazgos[version] = {
            "archivo": str(destino.relative_to(BASE_DIR)),
            "texto": texto,
        }

    return hallazgos


# ============================================================
# HERRAMIENTA 3 — memory_profiler
# ============================================================


def perfilar_memoria(corpus_dir, versiones):
    """
    Evolución del RSS durante la corrida completa de cada versión.

    `include_children=True` es imprescindible en la versión
    concurrente: sin él se mediría solo al padre y la memoria de los
    workers quedaría invisible.

    :param corpus_dir: Directorio del corpus.
    :type corpus_dir: pathlib.Path
    :param versiones: Versiones a perfilar (ver ``VERSIONES``).
    :type versiones: tuple[str, ...]
    :return: Por versión: la serie de RSS en MB, su pico, su base y el intervalo de
        muestreo, o el motivo por el que se omitió.
    :rtype: dict[str, dict]
    """
    hallazgos = {}

    for version in versiones:
        print(f"  memory_profiler: {version}", flush=True)

        # El muestreo lo hace el propio subproceso sobre sí mismo.
        # Muestrear desde el orquestador no sirve: en proceso, cada
        # versión heredaba la memoria de la anterior (las bases subían
        # de 27 a 107 MB); y desde afuera por PID, `memory_usage` toma
        # una sola muestra sin `timeout`, y con `timeout` revienta
        # cuando el hijo queda zombie antes de ser cosechado.
        medicion = _medir_en_subproceso(version, corpus_dir, 1, serie_memoria=True)

        serie = medicion.get("serie_mb") or []

        if not serie:
            hallazgos[version] = {
                "omitido": "el proceso terminó antes del primer muestreo"
            }
            continue

        hallazgos[version] = {
            "serie_mb": serie,
            "pico_mb": max(serie),
            "base_mb": min(serie),
            "intervalo_s": 0.05,
        }

    return hallazgos


# ============================================================
# HERRAMIENTA 4 — Scalene
# ============================================================


def perfilar_scalene(corpus_dir, versiones, limite_s=150):
    """
    Perfila CPU y memoria línea a línea con Scalene.

    Separa el tiempo de Python del tiempo nativo. Scalene 2.3 escribe
    un JSON y lo renderiza aparte con `scalene view <archivo>`.

    :param corpus_dir: Directorio del corpus.
    :type corpus_dir: pathlib.Path
    :param versiones: Versiones a perfilar (ver ``VERSIONES``).
    :type versiones: tuple[str, ...]
    :param limite_s: Segundos máximos por versión antes de abortar Scalene.
    :type limite_s: int
    :return: Por versión: el JSON de Scalene y su resumen, el error o el motivo de la
        omisión. Si Scalene no está instalado, ``{"omitido": ...}``.
    :rtype: dict
    """
    en_windows = sys.platform.startswith("win")

    nombre_ejecutable = "scalene.exe" if en_windows else "scalene"
    scalene = Path(sys.executable).parent / nombre_ejecutable

    if not scalene.exists():
        scalene = (
            BASE_DIR
            / ".venv"
            / ("Scripts" if en_windows else "bin")
            / nombre_ejecutable
        )

    if not scalene.exists():
        return {"omitido": f"scalene no está instalado en {scalene.parent}"}

    hallazgos = {}

    for version in versiones:
        destino = DIR_PERFILES / f"scalene-{version}.json"

        print(f"  scalene: {version}", flush=True)

        try:
            proceso = subprocess.run(  # nosec B603
                [
                    str(scalene),
                    "run",
                    "-o",
                    str(destino),
                    str(SRC_DIR / "perfilado.py"),
                    "---",
                    "--medir",
                    version,
                    "--directorio",
                    str(corpus_dir),
                    "--repeticiones",
                    "1",
                ],
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                timeout=limite_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            # Scalene instrumenta el intérprete entero; con los procesos
            # hijos de `spawn` de la versión concurrente se queda colgado.
            destino.unlink(missing_ok=True)
            hallazgos[version] = {
                "omitido": f"Scalene excedió {limite_s}s sobre esta versión: su "
                "instrumentación no acompaña a los procesos hijos "
                "creados por spawn"
            }
            continue

        if proceso.returncode != 0 or not destino.exists():
            hallazgos[version] = {"error": (proceso.stderr or proceso.stdout)[-400:]}
            continue

        hallazgos[version] = {
            "archivo": str(destino.relative_to(BASE_DIR)),
            "ver_con": f"{scalene} view {destino.relative_to(BASE_DIR)}",
            "resumen": _resumir_scalene(destino),
        }

    return hallazgos


def _resumir_scalene(archivo):
    """
    Extrae las líneas más caras del JSON de Scalene.

    El esquema cambia entre versiones, así que la lectura es
    defensiva: si no se reconoce, se informa y se deja el archivo.

    :param archivo: JSON que escribió Scalene.
    :type archivo: pathlib.Path
    :return: Tiempo total, huella máxima de memoria y las líneas más caras, o
        ``{"error": ...}`` si el JSON no se puede leer.
    :rtype: dict
    """
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"error": str(error)}

    filas = []

    for ruta, contenido in (datos.get("files") or {}).items():
        for linea in contenido.get("lines") or []:
            cpu = linea.get("n_cpu_percent_python", 0.0) + linea.get(
                "n_cpu_percent_c", 0.0
            )

            if cpu <= 0.5:
                continue

            filas.append(
                {
                    "ubicacion": f"{Path(ruta).name}:{linea.get('lineno')}",
                    "codigo": (linea.get("line") or "").strip()[:90],
                    "cpu_pct": round(cpu, 2),
                    "cpu_python_pct": round(linea.get("n_cpu_percent_python", 0.0), 2),
                    "memoria_mb": round(linea.get("n_peak_mb", 0.0), 2),
                }
            )

    filas.sort(key=lambda fila: fila["cpu_pct"], reverse=True)

    return {
        "elapsed_s": datos.get("elapsed_time_sec"),
        "max_footprint_mb": datos.get("max_footprint_mb"),
        "top": filas[:10],
    }


# ============================================================
# HERRAMIENTA 5 — py-spy
# ============================================================


def perfilar_pyspy(corpus_dir, versiones, ejecutar):
    """
    Muestreo estadístico desde fuera del proceso; genera flamegraphs.

    En macOS, `py-spy` necesita `sudo` para adjuntarse a otro proceso
    (restricción de SIP), así que por defecto no se ejecuta: se deja
    un script con los comandos exactos para correr a mano. Es la
    única herramienta de las cinco que puede perfilar un proceso ya
    en marcha sin instrumentarlo.

    :param corpus_dir: Directorio del corpus.
    :type corpus_dir: pathlib.Path
    :param versiones: Versiones a perfilar (ver ``VERSIONES``).
    :type versiones: tuple[str, ...]
    :param ejecutar: Si se corre ``py-spy`` ahora (en macOS pide ``sudo``). Si es falso,
        solo se escribe el script con los comandos.
    :type ejecutar: bool
    :return: Por versión, la ruta del flamegraph o el error. Sin ``ejecutar``,
        ``{"omitido": ..., "script": ..., "comandos": [...]}``.
    :rtype: dict
    """
    en_windows = sys.platform.startswith("win")

    pyspy = (
        BASE_DIR
        / ".venv"
        / ("Scripts" if en_windows else "bin")
        / ("py-spy.exe" if en_windows else "py-spy")
    )

    def _relativa(ruta):
        """
        Expresa una ruta relativa a la raíz del repositorio, si está dentro.

        :param ruta: Ruta a convertir.
        :type ruta: str | pathlib.Path
        :return: La ruta relativa a ``BASE_DIR``, o la original si queda fuera.
        :rtype: pathlib.Path
        """
        try:
            return Path(ruta).relative_to(BASE_DIR)
        except ValueError:
            return Path(ruta)

    # Windows no tiene SIP ni sudo: py-spy se adjunta sin privilegios.
    prefijo = "" if en_windows else "sudo "

    comandos = []

    for version in versiones:
        destino = DIR_PERFILES / f"pyspy-{version}.svg"

        comandos.append(
            f"{prefijo}{_relativa(pyspy)} record "
            f"--output {destino.relative_to(BASE_DIR)} --format flamegraph "
            f"--subprocesses -- {_relativa(sys.executable)} "
            f"src/perfilado.py --medir {version} "
            f"--directorio {corpus_dir} --repeticiones 1"
        )

    if en_windows:
        script = DIR_PERFILES / "pyspy.bat"
        script.write_text(
            "@echo off\r\n"
            "REM Ejecutar desde la raiz del repo.\r\n\r\n"
            + "\r\n\r\n".join(comandos)
            + "\r\n",
            encoding="utf-8",
        )
    else:
        script = DIR_PERFILES / "pyspy.sh"
        script.write_text(
            "#!/usr/bin/env bash\n"
            "# py-spy requiere sudo en macOS (SIP). Ejecutar desde la raíz del repo.\n"
            "set -euo pipefail\n\n" + "\n\n".join(comandos) + "\n",
            encoding="utf-8",
        )
        script.chmod(0o755)

    if not ejecutar:
        return {
            "omitido": (
                "comandos escritos en profiles/pyspy.bat"
                if en_windows
                else "requiere sudo en macOS; comandos escritos en profiles/pyspy.sh"
            ),
            "script": str(script.relative_to(BASE_DIR)),
            "comandos": comandos,
        }

    hallazgos = {}

    for version, comando in zip(versiones, comandos):
        print(f"  py-spy: {version} (pedirá contraseña)", flush=True)

        # shell=True porque el mismo comando se escribe en pyspy.sh/.bat
        # para correrlo a mano (incluye `sudo`); se arma con rutas internas.
        proceso = subprocess.run(  # nosec B602
            comando,
            shell=True,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            check=False,
        )

        destino = DIR_PERFILES / f"pyspy-{version}.svg"

        hallazgos[version] = (
            {"archivo": str(destino.relative_to(BASE_DIR))}
            if destino.exists()
            else {"error": (proceso.stderr or proceso.stdout)[-400:]}
        )

    return hallazgos


# ============================================================
# TABLA COMPARATIVA EN MARKDOWN
# ============================================================


def _ms(valor):
    """
    Formatea milisegundos con punto de miles y coma decimal.

    La precisión depende de la magnitud: cuatro decimales por debajo de
    0,01 ms, dos hasta 1.000 ms y ninguno por encima.

    :param valor: Milisegundos, o ``None``.
    :type valor: float | None
    :return: El valor formateado, o un guion si es ``None``.
    :rtype: str
    """
    if valor is None:
        return "—"
    if valor < 0.01:
        return f"{valor:.4f}".replace(".", ",")
    if valor < 1000:
        return f"{valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return f"{valor:,.0f}".replace(",", ".")


def _mb(valor):
    """
    Formatea megabytes con un decimal y coma decimal.

    :param valor: Megabytes, o ``None``.
    :type valor: float | None
    :return: El valor formateado, o un guion si es ``None``.
    :rtype: str
    """
    return "—" if valor is None else f"{valor:,.1f}".replace(".", ",")


def _num(valor, decimales=0):
    """
    Número con convención española: miles con punto, decimales con coma.

    Se formatea cada número por separado en lugar de aplicar un
    `.replace(",", ".")` sobre la frase entera, que también pisaba las
    comas de la prosa ("Sí, y se amplifica" -> "Sí. y se amplifica").

    :param valor: Número a formatear.
    :type valor: float
    :param decimales: Cantidad de decimales.
    :type decimales: int
    :return: El número con punto de miles y coma decimal.
    :rtype: str
    """
    texto = f"{valor:,.{decimales}f}"
    return texto.replace(",", "@").replace(".", ",").replace("@", ".")


def _celda_ms(valor):
    """
    Celda de tiempo: el guion va solo, sin unidad detrás.

    :param valor: Milisegundos, o ``None``.
    :type valor: float | None
    :return: ``"<valor> ms"``, o solo un guion si no hay valor.
    :rtype: str
    """
    return "—" if valor is None else f"{_ms(valor)} ms"


def tabla_markdown(resumen):
    """
    Tabla comparativa obligatoria, lista para pegar en el README.

    :param resumen: Mediana por versión, tal como la devuelve :func:`comparativa`.
    :type resumen: dict[str, dict]
    :return: La tabla en Markdown, con una fila por versión.
    :rtype: str
    """
    filas = [
        "| Versión | Tiempo de consulta | Costo de indexación | Memoria (RSS) | "
        "Observación |",
        "| :--- | ---: | ---: | ---: | :--- |",
    ]

    for version in VERSIONES:
        dato = resumen[version]

        filas.append(
            f"| {dato['etiqueta']} "
            f"| {_celda_ms(dato['consulta_ms'])} "
            f"| {_celda_ms(dato['indexacion_ms'])} "
            f"| {_mb(dato['rss_mb'])} MB "
            f"| {dato['observacion']} |"
        )

    return "\n".join(filas)


# ============================================================
# GRÁFICOS
# ============================================================

PALETAS = {
    "light": {
        "superficie": "#fcfcfb",
        "tinta": "#0b0b0b",
        "tinta_secundaria": "#52514e",
        "tinta_tenue": "#898781",
        "grilla": "#e1e0d9",
        "eje": "#c3c2b7",
        "series": ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"),
    },
    "dark": {
        "superficie": "#1a1a19",
        "tinta": "#ffffff",
        "tinta_secundaria": "#c3c2b7",
        "tinta_tenue": "#898781",
        "grilla": "#2c2c2a",
        "eje": "#383835",
        "series": ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"),
    },
}


def _figura(paleta, alto=4.2):
    """
    Crea una figura con el fondo de la paleta.

    :param paleta: Colores del modo (ver ``PALETAS``).
    :type paleta: dict[str, str]
    :param alto: Alto de la figura, en pulgadas.
    :type alto: float
    :return: La figura y sus ejes.
    :rtype: tuple[matplotlib.figure.Figure, matplotlib.axes.Axes]
    """
    import matplotlib.pyplot as plt

    figura, ejes = plt.subplots(figsize=(7.6, alto), dpi=192)
    figura.patch.set_facecolor(paleta["superficie"])
    ejes.set_facecolor(paleta["superficie"])

    return figura, ejes


def _cromo(ejes, paleta, titulo, etiqueta_x=None, etiqueta_y=None, grilla="y"):
    """
    Grilla y ejes en hairline sólido, recesivos; texto en tintas.

    :param ejes: Ejes a estilizar.
    :type ejes: matplotlib.axes.Axes
    :param paleta: Colores del modo (ver ``PALETAS``).
    :type paleta: dict[str, str]
    :param titulo: Título del gráfico.
    :type titulo: str
    :param etiqueta_x: Rótulo del eje x, si lo lleva.
    :type etiqueta_x: str | None
    :param etiqueta_y: Rótulo del eje y, si lo lleva.
    :type etiqueta_y: str | None
    :param grilla: Eje sobre el que se dibuja la grilla: ``"x"``, ``"y"`` o ``"both"``.
    :type grilla: str
    """
    ejes.set_title(
        titulo,
        color=paleta["tinta"],
        fontsize=11.5,
        loc="left",
        pad=14,
        fontweight="bold",
    )

    if etiqueta_x:
        ejes.set_xlabel(etiqueta_x, color=paleta["tinta_tenue"], fontsize=9)
    if etiqueta_y:
        ejes.set_ylabel(etiqueta_y, color=paleta["tinta_tenue"], fontsize=9)

    ejes.tick_params(colors=paleta["tinta_tenue"], labelsize=9, length=0)

    for lado in ("top", "right"):
        ejes.spines[lado].set_visible(False)
    for lado in ("bottom", "left"):
        ejes.spines[lado].set_color(paleta["eje"])
        ejes.spines[lado].set_linewidth(0.8)

    ejes.grid(
        axis=grilla,
        color=paleta["grilla"],
        linewidth=0.8,
        linestyle="-",
        zorder=0,
    )
    ejes.set_axisbelow(True)


def _guardar(figura, nombre, modo):
    """
    Guarda la figura como PNG en ``profiles/`` y la cierra.

    :param figura: Figura a guardar.
    :type figura: matplotlib.figure.Figure
    :param nombre: Nombre base del gráfico.
    :type nombre: str
    :param modo: ``"light"`` o ``"dark"``; se agrega al nombre del archivo.
    :type modo: str
    :return: Ruta del PNG generado.
    :rtype: pathlib.Path
    """
    destino = DIR_PERFILES / f"{nombre}-{modo}.png"
    figura.savefig(
        destino,
        facecolor=figura.get_facecolor(),
        bbox_inches="tight",
        pad_inches=0.28,
    )

    import matplotlib.pyplot as plt

    plt.close(figura)

    return destino


def _etiquetas_al_final(ejes, puntos, paleta, separacion_px=17):
    """
    Rotula cada serie en su extremo derecho sin que las etiquetas se pisen.

    Dos series con valores casi iguales —el caso de "algoritmo" y
    "concurrencia", que comparten el camino de consulta— dejan sus
    etiquetas una sobre otra. Se ordenan por altura y se empujan
    verticalmente hasta respetar una separación mínima.

    :param ejes: Ejes del gráfico.
    :type ejes: matplotlib.axes.Axes
    :param puntos: Último punto de cada serie, como ``(x, y, texto)``.
    :type puntos: list[tuple[float, float, str]]
    :param paleta: Colores del modo (ver ``PALETAS``).
    :type paleta: dict[str, str]
    :param separacion_px: Separación vertical mínima entre etiquetas, en píxeles.
    :type separacion_px: int
    """
    ejes.figure.canvas.draw()

    # (posición en píxeles, x, y, texto), de abajo hacia arriba
    ubicados = sorted(
        (ejes.transData.transform((x_dato, y_dato))[1], x_dato, y_dato, texto)
        for x_dato, y_dato, texto in puntos
    )

    ajustadas = []
    ultima = None

    for pixel, x_dato, y_dato, texto in ubicados:
        destino = pixel if ultima is None else max(pixel, ultima + separacion_px)
        ajustadas.append((x_dato, y_dato, texto, destino - pixel))
        ultima = destino

    # matplotlib desplaza en puntos tipográficos, no en píxeles
    por_punto = ejes.figure.dpi / 72

    for x_dato, y_dato, texto, desvio_px in ajustadas:
        ejes.annotate(
            texto,
            (x_dato, y_dato),
            xytext=(10, desvio_px / por_punto),
            textcoords="offset points",
            color=paleta["tinta_secundaria"],
            fontsize=8.5,
            va="center",
            zorder=4,
        )


def _grafico_escalabilidad_consulta(datos, paleta, modo):
    """
    Grafica el tiempo de consulta de cada versión según el tamaño del corpus.

    El eje y es logarítmico: los tiempos van de milésimas de
    milisegundo a segundos.

    :param datos: Resumen por tamaño de corpus, tal como lo devuelve
        :func:`escalabilidad`.
    :type datos: dict[str, dict]
    :param paleta: Colores del modo (ver ``PALETAS``).
    :type paleta: dict[str, str]
    :param modo: ``"light"`` o ``"dark"``; se agrega al nombre del archivo.
    :type modo: str
    :return: Ruta del PNG generado.
    :rtype: pathlib.Path
    """
    tamanos = sorted(int(tamano) for tamano in datos)
    figura, ejes = _figura(paleta)

    rotulos = []

    for indice, version in enumerate(VERSIONES):
        valores = [datos[str(tamano)][version]["consulta_ms"] for tamano in tamanos]

        ejes.plot(
            tamanos,
            valores,
            color=paleta["series"][indice],
            linewidth=2,
            marker="o",
            markersize=5,
            markeredgecolor=paleta["superficie"],
            markeredgewidth=2,
            label=ETIQUETAS[version],
            zorder=3,
        )
        rotulos.append((tamanos[-1], valores[-1], ETIQUETAS[version]))

    ejes.set_yscale("log")
    ejes.set_xticks(tamanos)
    ejes.set_xticklabels([f"{tamano:,}".replace(",", ".") for tamano in tamanos])
    ejes.set_xlim(tamanos[0] * 0.97, tamanos[-1] * 1.62)

    _cromo(
        ejes,
        paleta,
        "Tiempo de consulta según el volumen del corpus",
        "documentos del corpus",
        "milisegundos (escala log)",
    )

    _etiquetas_al_final(ejes, rotulos, paleta)

    # La leyenda va debajo del área de trazado: dentro se superponía
    # con las propias series que debía identificar.
    ejes.legend(
        frameon=False,
        fontsize=8.5,
        labelcolor=paleta["tinta_secundaria"],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        ncol=3,
        handlelength=1.6,
        columnspacing=1.6,
    )

    return _guardar(figura, "escalabilidad-consulta", modo)


def _grafico_escalabilidad_indexacion(datos, paleta, modo):
    """
    Grafica el costo de indexación según el tamaño del corpus.

    :param datos: Resumen por tamaño de corpus, tal como lo devuelve
        :func:`escalabilidad`.
    :type datos: dict[str, dict]
    :param paleta: Colores del modo (ver ``PALETAS``).
    :type paleta: dict[str, str]
    :param modo: ``"light"`` o ``"dark"``; se agrega al nombre del archivo.
    :type modo: str
    :return: Ruta del PNG generado.
    :rtype: pathlib.Path
    """
    tamanos = sorted(int(tamano) for tamano in datos)
    figura, ejes = _figura(paleta)

    lineas = (
        ("algoritmo", "Indexación secuencial", paleta["series"][0]),
        ("concurrencia", "Indexación paralela (P = 4)", paleta["series"][2]),
    )

    rotulos = []

    for version, etiqueta, color in lineas:
        valores = [
            datos[str(tamano)][version]["indexacion_ms"] / 1000 for tamano in tamanos
        ]
        ejes.plot(
            tamanos,
            valores,
            color=color,
            linewidth=2,
            marker="o",
            markersize=5,
            markeredgecolor=paleta["superficie"],
            markeredgewidth=2,
            label=etiqueta,
            zorder=3,
        )
        rotulos.append((tamanos[-1], valores[-1], etiqueta))

    ejes.set_xticks(tamanos)
    ejes.set_xticklabels([f"{tamano:,}".replace(",", ".") for tamano in tamanos])
    ejes.set_xlim(tamanos[0] * 0.97, tamanos[-1] * 1.72)
    ejes.set_ylim(0, None)

    _cromo(
        ejes,
        paleta,
        "Costo único de indexación según el volumen",
        "documentos del corpus",
        "segundos",
    )

    _etiquetas_al_final(ejes, rotulos, paleta)

    ejes.legend(
        frameon=False,
        fontsize=8.5,
        labelcolor=paleta["tinta_secundaria"],
        loc="upper left",
    )

    return _guardar(figura, "escalabilidad-indexacion", modo)


def _grafico_consulta_por_version(resumen, paleta, modo):
    """
    Punto por versión sobre eje logarítmico.

    Los valores cubren seis órdenes de magnitud (2.485 ms contra
    0,002 ms): una barra sobre eje log mentiría, porque su longitud
    ya no es proporcional al valor. El punto no promete esa lectura.

    :param resumen: Mediana por versión, tal como la devuelve :func:`comparativa`.
    :type resumen: dict[str, dict]
    :param paleta: Colores del modo (ver ``PALETAS``).
    :type paleta: dict[str, str]
    :param modo: ``"light"`` o ``"dark"``; se agrega al nombre del archivo.
    :type modo: str
    :return: Ruta del PNG generado.
    :rtype: pathlib.Path
    """
    figura, ejes = _figura(paleta, alto=3.4)

    etiquetas = [ETIQUETAS[version] for version in VERSIONES]
    valores = [resumen[version]["consulta_ms"] for version in VERSIONES]
    posiciones = list(range(len(VERSIONES)))[::-1]

    for posicion, valor, color in zip(posiciones, valores, paleta["series"]):
        ejes.plot(
            [valor],
            [posicion],
            marker="o",
            markersize=9,
            color=color,
            markeredgecolor=paleta["superficie"],
            markeredgewidth=2,
            zorder=3,
        )
        ejes.annotate(
            f"{_ms(valor)} ms",
            (valor, posicion),
            xytext=(13, 0),
            textcoords="offset points",
            color=paleta["tinta_secundaria"],
            fontsize=9,
            va="center",
            zorder=4,
        )

    ejes.set_yticks(posiciones)
    ejes.set_yticklabels(etiquetas, color=paleta["tinta_secundaria"], fontsize=9)
    ejes.set_xscale("log")
    ejes.set_xlim(min(valores) * 0.25, max(valores) * 9)

    _cromo(
        ejes,
        paleta,
        (
            "Tiempo por consulta — corpus de "
            f"{resumen['inicial']['documentos']:,} documentos"
        ).replace(",", "."),
        "milisegundos (escala log)",
        grilla="x",
    )

    return _guardar(figura, "consulta-por-version", modo)


def _grafico_memoria_por_version(resumen, paleta, modo):
    """
    Grafica el pico de RSS de cada versión en barras.

    Una sola serie: un color para todas las barras, nunca un ramp.

    :param resumen: Mediana por versión, tal como la devuelve :func:`comparativa`.
    :type resumen: dict[str, dict]
    :param paleta: Colores del modo (ver ``PALETAS``).
    :type paleta: dict[str, str]
    :param modo: ``"light"`` o ``"dark"``; se agrega al nombre del archivo.
    :type modo: str
    :return: Ruta del PNG generado.
    :rtype: pathlib.Path
    """
    figura, ejes = _figura(paleta, alto=3.4)

    etiquetas = [ETIQUETAS[version] for version in VERSIONES]
    valores = [resumen[version]["rss_mb"] for version in VERSIONES]
    posiciones = list(range(len(VERSIONES)))[::-1]

    ejes.barh(
        posiciones,
        valores,
        height=0.58,
        color=paleta["series"][0],
        zorder=3,
    )

    for posicion, valor in zip(posiciones, valores):
        ejes.annotate(
            f"{_mb(valor)} MB",
            (valor, posicion),
            xytext=(8, 0),
            textcoords="offset points",
            color=paleta["tinta_secundaria"],
            fontsize=9,
            va="center",
            zorder=4,
        )

    ejes.set_yticks(posiciones)
    ejes.set_yticklabels(etiquetas, color=paleta["tinta_secundaria"], fontsize=9)
    ejes.set_xlim(0, max(valores) * 1.24)

    _cromo(
        ejes,
        paleta,
        "Pico de memoria residente por versión",
        "megabytes",
        grilla="x",
    )

    return _guardar(figura, "memoria-por-version", modo)


def _grafico_memoria_en_el_tiempo(memoria, paleta, modo):
    """
    Grafica el RSS de cada versión a lo largo de su corrida.

    :param memoria: Series de RSS por versión, tal como las devuelve
        :func:`perfilar_memoria`.
    :type memoria: dict[str, dict]
    :param paleta: Colores del modo (ver ``PALETAS``).
    :type paleta: dict[str, str]
    :param modo: ``"light"`` o ``"dark"``; se agrega al nombre del archivo.
    :type modo: str
    :return: Ruta del PNG generado.
    :rtype: pathlib.Path
    """
    figura, ejes = _figura(paleta)

    for indice, version in enumerate(VERSIONES):
        datos = memoria.get(version)
        if not datos or "serie_mb" not in datos:
            continue

        serie = datos["serie_mb"]
        tiempo = [
            numero_muestra * datos["intervalo_s"]
            for numero_muestra in range(len(serie))
        ]

        ejes.plot(
            tiempo,
            serie,
            color=paleta["series"][indice],
            linewidth=2,
            label=ETIQUETAS[version],
            zorder=3,
        )

    _cromo(
        ejes,
        paleta,
        "Memoria residente durante la corrida completa",
        "segundos",
        "MB",
    )

    # Debajo del área de trazado: adentro tapaba las propias curvas.
    ejes.legend(
        frameon=False,
        fontsize=8.5,
        labelcolor=paleta["tinta_secundaria"],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        ncol=3,
        handlelength=1.6,
        columnspacing=1.6,
    )

    return _guardar(figura, "memoria-en-el-tiempo", modo)


def generar_graficos(resultados):
    """
    Renderiza cada gráfico en sus dos modos: claro y oscuro.

    :param resultados: Resultados acumulados en ``profiles/perfilado.json``.
    :type resultados: dict
    :return: Los gráficos generados, como ``{nombre: True}``.
    :rtype: dict[str, bool]
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.family"] = ["DejaVu Sans"]

    generados = {}

    for modo, paleta in PALETAS.items():
        if resultados.get("escalabilidad"):
            _grafico_escalabilidad_consulta(resultados["escalabilidad"], paleta, modo)
            _grafico_escalabilidad_indexacion(resultados["escalabilidad"], paleta, modo)

        if resultados.get("comparativa"):
            _grafico_consulta_por_version(resultados["comparativa"], paleta, modo)
            _grafico_memoria_por_version(resultados["comparativa"], paleta, modo)

        if resultados.get("memoria"):
            _grafico_memoria_en_el_tiempo(resultados["memoria"], paleta, modo)

    for nombre in (
        "escalabilidad-consulta",
        "escalabilidad-indexacion",
        "consulta-por-version",
        "memoria-por-version",
        "memoria-en-el-tiempo",
    ):
        if (DIR_PERFILES / f"{nombre}-light.png").exists():
            generados[nombre] = True

    return generados


# ============================================================
# LAS CINCO PREGUNTAS DE LA CONSIGNA
# ============================================================


def responder_preguntas(resultados):
    """
    Deriva las respuestas de los números medidos, no de la prosa.

    Si una medición falta, la respuesta lo dice en lugar de inventar
    un valor.

    :param resultados: Resultados acumulados en ``profiles/perfilado.json``.
    :type resultados: dict
    :return: Una respuesta en HTML por pregunta (``cuello``, ``optimizacion``,
        ``impacto``, ``escalabilidad`` y ``tradeoff``). Vacío si falta la comparativa.
    :rtype: dict[str, str]
    """
    comparativa_ = resultados.get("comparativa")
    escalabilidad_ = resultados.get("escalabilidad")
    cprofile_ = resultados.get("cprofile") or {}

    if not comparativa_:
        return {}

    inicial = comparativa_["inicial"]
    estructura = comparativa_["estructura"]
    algoritmo = comparativa_["algoritmo"]
    concurrencia = comparativa_["concurrencia"]
    final = comparativa_["final"]

    respuestas = {}

    # ---- 1. cuello de botella
    top_indexacion = ""
    perfil = cprofile_.get("algoritmo", {}).get("top") or []

    for fila in perfil:
        if "tokenizar" in fila["funcion"]:
            top_indexacion = (
                f" El perfil determinista lo confirma: <code>{fila['funcion']}</code> "
                f"acumula {_num(fila['cumtime'], 2)} s en "
                f"{_num(fila['llamadas'])} llamadas."
            )
            break

    respuestas["cuello"] = (
        "En la línea base, releer y escanear el corpus completo en "
        "<strong>cada</strong> "
        f"consulta: {_ms(inicial['consulta_ms'])} ms por búsqueda, con E/S "
        "proporcional al "
        "corpus. Una vez introducido el índice, el cuello de botella se "
        "<strong>desplaza</strong> "
        f"al costo único de indexación ({_ms(algoritmo['indexacion_ms'])} ms), y "
        "dentro de él a la "
        f"tokenización.{top_indexacion}"
    )

    # ---- 2. qué optimización
    respuestas["optimizacion"] = (
        "Cuatro incrementos acumulativos: <strong>(1)</strong> índice invertido con "
        "<code>dict</code> más intersección de <code>set</code>, que cambia el escaneo "
        "O(n·m) por "
        "resolución O(1) promedio; <strong>(2)</strong> ranking top-k con "
        "<code>heapq.nlargest</code> "
        "en O(r·log k) y memoria auxiliar O(k), más caché LRU de consultas; "
        "<strong>(3)</strong> indexación MapReduce sobre "
        "<code>ProcessPoolExecutor</code> para evadir "
        "el GIL en la fase CPU-bound; <strong>(4)</strong> la combinación de ambas."
    )

    # ---- 3. impacto
    mejora_consulta = inicial["consulta_ms"] / algoritmo["consulta_ms"]
    mejora_cache = inicial["consulta_ms"] / final["consulta_ms"]
    mejora_heap = estructura["consulta_ms"] / algoritmo["consulta_ms"]
    mejora_indexacion = algoritmo["indexacion_ms"] / concurrencia["indexacion_ms"]

    respuestas["impacto"] = (
        f"La consulta pasa de {_ms(inicial['consulta_ms'])} ms a "
        f"{_ms(algoritmo['consulta_ms'])} ms "
        f"(<strong>{_num(mejora_consulta)}×</strong>) y a "
        f"{_ms(final['consulta_ms'])} ms con caché caliente "
        f"(<strong>{_num(mejora_cache)}×</strong>). "
        "El heap por sí solo lleva la resolución de "
        f"{_ms(estructura['consulta_ms'])} ms a "
        f"{_ms(algoritmo['consulta_ms'])} ms "
        f"(<strong>{_num(mejora_heap, 1)}×</strong>). "
        f"La indexación paralela baja de {_ms(algoritmo['indexacion_ms'])} ms a "
        f"{_ms(concurrencia['indexacion_ms'])} ms "
        f"(<strong>{_num(mejora_indexacion, 2)}×</strong>)."
    )

    # ---- 4. escalabilidad
    if escalabilidad_:
        tamanos = sorted(int(tamano) for tamano in escalabilidad_)
        menor, mayor = tamanos[0], tamanos[-1]

        ratio_menor = (
            escalabilidad_[str(menor)]["inicial"]["consulta_ms"]
            / escalabilidad_[str(menor)]["algoritmo"]["consulta_ms"]
        )
        ratio_mayor = (
            escalabilidad_[str(mayor)]["inicial"]["consulta_ms"]
            / escalabilidad_[str(mayor)]["algoritmo"]["consulta_ms"]
        )
        speedup_menor = (
            escalabilidad_[str(menor)]["algoritmo"]["indexacion_ms"]
            / escalabilidad_[str(menor)]["concurrencia"]["indexacion_ms"]
        )
        speedup_mayor = (
            escalabilidad_[str(mayor)]["algoritmo"]["indexacion_ms"]
            / escalabilidad_[str(mayor)]["concurrencia"]["indexacion_ms"]
        )

        respuestas["escalabilidad"] = (
            "Sí, y se <strong>amplifica</strong>. La ventaja de la consulta indexada "
            "sobre la línea "
            f"base crece de <strong>{_num(ratio_menor)}×</strong> con {_num(menor)} "
            "documentos a "
            f"<strong>{_num(ratio_mayor)}×</strong> con {_num(mayor)}: la búsqueda "
            "secuencial crece "
            "con el corpus mientras la indexada depende de los documentos candidatos, "
            "no del total. "
            f"El paralelismo se comporta distinto: su ventaja va de "
            f"<strong>{_num(speedup_menor, 2)}×</strong> a "
            f"<strong>{_num(speedup_mayor, 2)}×</strong>, "
            "porque el costo fijo de levantar los procesos solo se amortiza con "
            "volumen."
        )
    else:
        respuestas["escalabilidad"] = (
            "No medido en esta corrida — ejecutar con <code>--escalabilidad</code>."
        )

    # ---- 5. trade-off
    equilibrio = final["indexacion_ms"] / (
        inicial["consulta_ms"] - final["consulta_ms"]
    )

    respuestas["tradeoff"] = (
        "<strong>Memoria y arranque a cambio de latencia.</strong> El pico de RSS "
        "sube de "
        f"{_mb(inicial['rss_mb'])} MB a {_mb(algoritmo['rss_mb'])} MB con el índice "
        f"(<strong>{_num(algoritmo['rss_mb'] / inicial['rss_mb'], 1)}×</strong>) y a "
        f"{_mb(concurrencia['rss_mb'])} MB con los procesos "
        f"(<strong>{_num(concurrencia['rss_mb'] / algoritmo['rss_mb'], 2)}×</strong> "
        "adicional por los "
        f"índices parciales en vuelo). Además hay un costo único de indexación de "
        f"{_ms(final['indexacion_ms'])} ms que la línea base no paga: el punto de "
        "equilibrio está en "
        f"<strong>~{math.ceil(equilibrio)} consultas</strong>. Por debajo de eso, la "
        "línea base gana."
    )

    return respuestas


# ============================================================
# REPORTE HTML AUTOCONTENIDO
# ============================================================


def _incrustar(nombre, modo):
    """
    PNG como data URI, para que el reporte sea un único archivo.

    :param nombre: Nombre base del gráfico.
    :type nombre: str
    :param modo: ``"light"`` o ``"dark"``.
    :type modo: str
    :return: El PNG como data URI, o ``None`` si el archivo no existe.
    :rtype: str | None
    """
    import base64

    archivo = DIR_PERFILES / f"{nombre}-{modo}.png"

    if not archivo.exists():
        return None

    codificado = base64.b64encode(archivo.read_bytes()).decode("ascii")

    return f"data:image/png;base64,{codificado}"


def _figura_html(nombre, titulo, tabla_html=""):
    """
    Arma el ``<figure>`` de un gráfico, con su variante oscura.

    :param nombre: Nombre base del gráfico.
    :type nombre: str
    :param titulo: Texto alternativo de la imagen.
    :type titulo: str
    :param tabla_html: Tabla con los datos del gráfico; si viene, se agrega dentro de un
        ``<details>``.
    :type tabla_html: str
    :return: El HTML de la figura, o una cadena vacía si el gráfico no existe.
    :rtype: str
    """
    claro = _incrustar(nombre, "light")

    if not claro:
        return ""

    oscuro = _incrustar(nombre, "dark")
    fuente = (
        f'<source srcset="{oscuro}" media="(prefers-color-scheme: dark)">'
        if oscuro
        else ""
    )

    detalle = (
        f"<details><summary>Ver los datos como tabla</summary>{tabla_html}</details>"
        if tabla_html
        else ""
    )

    return f"""
    <figure class="grafico">
      <picture>{fuente}<img src="{claro}" alt="{titulo}"></picture>
      {detalle}
    </figure>"""


def _tabla_html(cabeceras, filas):
    """
    Arma una tabla HTML con cabecera.

    :param cabeceras: Títulos de las columnas.
    :type cabeceras: tuple[str, ...]
    :param filas: Celdas de cada fila, ya en HTML.
    :type filas: list[tuple[str, ...]]
    :return: La tabla HTML.
    :rtype: str
    """
    encabezado = "".join(f"<th>{cabecera}</th>" for cabecera in cabeceras)
    cuerpo = "".join(
        "<tr>" + "".join(f"<td>{celda}</td>" for celda in fila) + "</tr>"
        for fila in filas
    )
    return f"<table><thead><tr>{encabezado}</tr></thead><tbody>{cuerpo}</tbody></table>"


ESTILOS = """
:root {
  color-scheme: light;
  --plano: #f9f9f7; --superficie: #fcfcfb;
  --tinta: #0b0b0b; --tinta-2: #52514e; --tinta-3: #898781;
  --linea: #e1e0d9; --borde: rgba(11,11,11,0.10);
  --acento: #2a78d6; --ok: #0ca30c; --alerta: #fab219;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --plano: #0d0d0d; --superficie: #1a1a19;
    --tinta: #ffffff; --tinta-2: #c3c2b7; --tinta-3: #898781;
    --linea: #2c2c2a; --borde: rgba(255,255,255,0.10);
    --acento: #3987e5; --ok: #0ca30c; --alerta: #fab219;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0 20px 80px;
  background: var(--plano); color: var(--tinta);
  font: 14px/1.65 system-ui, -apple-system, "Segoe UI", sans-serif;
}
.envoltorio { max-width: 940px; margin: 0 auto; }
header {
  padding: 52px 0 30px; border-bottom: 1px solid var(--linea); margin-bottom: 34px;
}
h1 { font-size: 27px; line-height: 1.25; margin: 0 0 10px; letter-spacing: -0.015em; }
.subtitulo { color: var(--tinta-2); margin: 0 0 20px; font-size: 15px; }
.chips { display: flex; flex-wrap: wrap; gap: 7px; }
.chip {
  font-size: 11.5px; color: var(--tinta-2); background: var(--superficie);
  border: 1px solid var(--borde); border-radius: 999px; padding: 3px 11px;
}
h2 {
  font-size: 12px; text-transform: uppercase; letter-spacing: 0.09em;
  color: var(--tinta-3); margin: 46px 0 16px; font-weight: 600;
}
h3 { font-size: 15px; margin: 30px 0 8px; }
p { margin: 0 0 14px; }
table {
  width: 100%; border-collapse: collapse; font-size: 13px;
  background: var(--superficie); border: 1px solid var(--borde);
  border-radius: 10px; overflow: hidden; margin: 0 0 18px;
}
th, td { padding: 9px 13px; text-align: left; border-bottom: 1px solid var(--linea); }
th { font-weight: 600; color: var(--tinta-2); font-size: 11.5px;
     text-transform: uppercase; letter-spacing: 0.05em; }
td:not(:first-child):not(:last-child), th:not(:first-child):not(:last-child) {
  text-align: right; font-variant-numeric: tabular-nums;
}
tbody tr:last-child td { border-bottom: 0; }
.envoltura-tabla { overflow-x: auto; }
.pregunta {
  background: var(--superficie); border: 1px solid var(--borde);
  border-left: 3px solid var(--acento); border-radius: 10px;
  padding: 16px 20px; margin: 0 0 14px;
}
.pregunta h3 { margin: 0 0 7px; font-size: 14.5px; }
.pregunta p { margin: 0; color: var(--tinta-2); }
.grafico { margin: 0 0 26px; }
.grafico img {
  width: 100%; height: auto; display: block;
  border: 1px solid var(--borde); border-radius: 10px; background: var(--superficie);
}
details { margin-top: 10px; }
summary { cursor: pointer; font-size: 12.5px; color: var(--tinta-3); padding: 5px 0; }
pre {
  background: var(--superficie); border: 1px solid var(--borde); border-radius: 10px;
  padding: 14px; overflow-x: auto; font-size: 11.5px; line-height: 1.5;
  color: var(--tinta-2); margin: 0 0 18px;
}
code { font-size: 0.92em; background: var(--superficie);
       border: 1px solid var(--borde); border-radius: 4px; padding: 1px 5px; }
pre code { border: 0; background: none; padding: 0; }
.nota {
  font-size: 12.5px; color: var(--tinta-2); border-left: 2px solid var(--linea);
  padding: 3px 0 3px 14px; margin: 0 0 18px;
}
footer { margin-top: 56px; padding-top: 22px; border-top: 1px solid var(--linea);
         color: var(--tinta-3); font-size: 12.5px; }
"""


def _html_encabezado(entorno):
    """
    Arma el encabezado del reporte, con el entorno de medición como etiquetas.

    :param entorno: Descripción del equipo y del intérprete (ver :func:`_entorno`).
    :type entorno: dict[str, str]
    :return: El HTML del encabezado.
    :rtype: str
    """
    chips = "".join(
        f'<span class="chip">{html.escape(str(valor))}</span>'
        for valor in entorno.values()
    )

    return f"""
    <header>
      <h1>Perfilado y medición — Buscador Eficiente de Información</h1>
      <p class="subtitulo">Comparativa de las cinco versiones con cProfile,
         line_profiler, memory_profiler, Scalene y py-spy.</p>
      <div class="chips">{chips}</div>
    </header>"""


def _html_comparativa(resumen):
    """
    Arma la tabla comparativa obligatoria de las cinco versiones.

    :param resumen: Mediana por versión, tal como la devuelve :func:`comparativa`.
    :type resumen: dict[str, dict]
    :return: El HTML de la sección, o una cadena vacía si no hay comparativa.
    :rtype: str
    """
    if not resumen:
        return ""

    filas = [
        (
            resumen[version]["etiqueta"],
            _celda_ms(resumen[version]["consulta_ms"]),
            _celda_ms(resumen[version]["indexacion_ms"]),
            f"{_mb(resumen[version]['rss_mb'])} MB",
            resumen[version]["observacion"],
        )
        for version in VERSIONES
    ]

    return (
        "<h2>Comparación obligatoria</h2>"
        '<div class="envoltura-tabla">'
        + _tabla_html(
            (
                "Versión",
                "Tiempo de consulta",
                "Costo de indexación",
                "Memoria (RSS)",
                "Observación",
            ),
            filas,
        )
        + "</div>"
        + '<p class="nota">Mediana de las rondas útiles; cada versión se mide en '
        "un "
        "proceso limpio y las versiones se alternan dentro de cada ronda. "
        "El total de coincidencias es idéntico en las cinco versiones "
        f"({_num(resumen['inicial']['coincidencias'])} documentos), que es el "
        "testigo de equivalencia.</p>"
    )


def _html_preguntas(respuestas):
    """
    Arma la sección con las respuestas a las cinco preguntas de la medición.

    :param respuestas: Respuestas en HTML, tal como las devuelve
        :func:`responder_preguntas`.
    :type respuestas: dict[str, str]
    :return: El HTML de la sección, o una cadena vacía si no hay respuestas.
    :rtype: str
    """
    if not respuestas:
        return ""

    titulos = (
        ("cuello", "¿Dónde está el principal cuello de botella?"),
        ("optimizacion", "¿Qué optimización se realizó?"),
        ("impacto", "¿Qué impacto tuvo?"),
        (
            "escalabilidad",
            "¿La mejora se mantiene al aumentar el volumen de datos?",
        ),
        ("tradeoff", "¿Qué trade-off se produjo?"),
    )

    return "<h2>Las cinco preguntas</h2>" + "".join(
        f'<div class="pregunta"><h3>{titulo}</h3>'
        f"<p>{respuestas.get(clave, '—')}</p></div>"
        for clave, titulo in titulos
    )


def _figuras_escalabilidad(por_tamano):
    """
    Arma las figuras de consulta e indexación según el tamaño del corpus.

    :param por_tamano: Resumen por tamaño de corpus, tal como lo devuelve
        :func:`escalabilidad`.
    :type por_tamano: dict[str, dict]
    :return: El HTML de las dos figuras, cada una con su tabla de datos.
    :rtype: list[str]
    """
    tamanos = sorted(int(tamano) for tamano in por_tamano)

    return [
        _figura_html(
            "escalabilidad-consulta",
            "Tiempo de consulta según el volumen",
            _tabla_html(
                ["Versión"] + [f"{tamano:,}".replace(",", ".") for tamano in tamanos],
                [
                    [ETIQUETAS[version]]
                    + [
                        _celda_ms(por_tamano[str(tamano)][version]["consulta_ms"])
                        for tamano in tamanos
                    ]
                    for version in VERSIONES
                ],
            ),
        ),
        _figura_html(
            "escalabilidad-indexacion",
            "Costo de indexación según el volumen",
            _tabla_html(
                ["Versión"] + [f"{tamano:,}".replace(",", ".") for tamano in tamanos],
                [
                    [ETIQUETAS[version]]
                    + [
                        _celda_ms(por_tamano[str(tamano)][version]["indexacion_ms"])
                        for tamano in tamanos
                    ]
                    for version in ("algoritmo", "concurrencia")
                ],
            ),
        ),
    ]


def _figuras_comparativa(resumen):
    """
    Arma las figuras de tiempo por consulta y de memoria por versión.

    :param resumen: Mediana por versión, tal como la devuelve :func:`comparativa`.
    :type resumen: dict[str, dict]
    :return: El HTML de las dos figuras, cada una con su tabla de datos.
    :rtype: list[str]
    """
    return [
        _figura_html(
            "consulta-por-version",
            "Tiempo por consulta",
            _tabla_html(
                ("Versión", "Tiempo de consulta"),
                [
                    (ETIQUETAS[version], _celda_ms(resumen[version]["consulta_ms"]))
                    for version in VERSIONES
                ],
            ),
        ),
        _figura_html(
            "memoria-por-version",
            "Pico de memoria por versión",
            _tabla_html(
                ("Versión", "RSS", "tracemalloc"),
                [
                    (
                        ETIQUETAS[version],
                        f"{_mb(resumen[version]['rss_mb'])} MB",
                        f"{_mb(resumen[version]['tracemalloc_mb'])} MB",
                    )
                    for version in VERSIONES
                ],
            ),
        ),
    ]


def _figura_memoria(memoria):
    """
    Arma la figura del RSS a lo largo de la corrida de cada versión.

    :param memoria: Series de RSS por versión, tal como las devuelve
        :func:`perfilar_memoria`.
    :type memoria: dict[str, dict]
    :return: El HTML de la figura con su tabla de datos, o una cadena vacía si el
        gráfico no existe.
    :rtype: str
    """
    return _figura_html(
        "memoria-en-el-tiempo",
        "Memoria residente en el tiempo",
        _tabla_html(
            ("Versión", "Base", "Pico", "Muestras"),
            [
                (
                    ETIQUETAS[version],
                    f"{_mb(memoria[version]['base_mb'])} MB",
                    f"{_mb(memoria[version]['pico_mb'])} MB",
                    len(memoria[version]["serie_mb"]),
                )
                for version in VERSIONES
                if version in memoria and "serie_mb" in memoria[version]
            ],
        ),
    )


def _html_graficos(resumen, por_tamano, memoria):
    """
    Arma la sección de gráficos con los que haya datos para dibujar.

    :param resumen: Mediana por versión (ver :func:`comparativa`).
    :type resumen: dict[str, dict]
    :param por_tamano: Resumen por tamaño de corpus (ver :func:`escalabilidad`).
    :type por_tamano: dict[str, dict]
    :param memoria: Series de RSS por versión (ver :func:`perfilar_memoria`).
    :type memoria: dict[str, dict]
    :return: El HTML de la sección, o una cadena vacía si no hay ningún gráfico.
    :rtype: str
    """
    graficos = []

    if por_tamano:
        graficos += _figuras_escalabilidad(por_tamano)

    if resumen:
        graficos += _figuras_comparativa(resumen)

    if memoria:
        graficos.append(_figura_memoria(memoria))

    graficos = [grafico for grafico in graficos if grafico]

    if not graficos:
        return ""

    return "<h2>Gráficos</h2>" + "".join(graficos)


def _html_cprofile(cprofile):
    """
    Arma la sección de cProfile: las funciones más caras de cada versión.

    :param cprofile: Hallazgos por versión, tal como los devuelve
        :func:`perfilar_cprofile`.
    :type cprofile: dict[str, dict]
    :return: El HTML de la sección, o una cadena vacía si no hay datos.
    :rtype: str
    """
    if not cprofile:
        return ""

    partes = ["<h3>cProfile — costo por función</h3>"]

    for version, datos in cprofile.items():
        filas = [
            (
                f"<code>{html.escape(estadistica['funcion'])}</code>",
                f"{estadistica['llamadas']:,}".replace(",", "."),
                f"{estadistica['tottime']:.3f}",
                f"{estadistica['cumtime']:.3f}",
            )
            for estadistica in datos["top"][:8]
        ]
        partes.append(
            f"<p><strong>{ETIQUETAS[version]}</strong> — "
            f"{datos['total_s']:.2f} s instrumentados · "
            f"<code>{datos['archivo']}</code></p>"
            '<div class="envoltura-tabla">'
            + _tabla_html(("Función", "Llamadas", "tottime (s)", "cumtime (s)"), filas)
            + "</div>"
        )

    partes.append(
        '<p class="nota">Visualizable con '
        "<code>.venv/bin/snakeviz "
        "profiles/cprofile-&lt;version&gt;.prof</code>.</p>"
    )

    return "".join(partes)


def _html_line_profiler(line_profiler):
    """
    Arma la sección de line_profiler: un extracto del costo por línea.

    :param line_profiler: Hallazgos por versión, tal como los devuelve
        :func:`perfilar_line`.
    :type line_profiler: dict[str, dict]
    :return: El HTML de la sección, o una cadena vacía si no hay datos.
    :rtype: str
    """
    if not line_profiler:
        return ""

    partes = ["<h3>line_profiler — costo por línea</h3>"]

    for version, datos in line_profiler.items():
        if "omitido" in datos:
            partes.append(
                f"<p><strong>{ETIQUETAS[version]}</strong> — omitido: "
                f"{html.escape(datos['omitido'])}.</p>"
            )
            continue

        extracto = "\n".join(datos["texto"].splitlines()[:44])
        partes.append(
            f"<p><strong>{ETIQUETAS[version]}</strong> — "
            f"<code>{datos['archivo']}</code></p>"
            f"<pre><code>{html.escape(extracto)}</code></pre>"
        )

    return "".join(partes)


def _html_memoria(memoria):
    """
    Arma la tabla de memory_profiler: base, pico y crecimiento del RSS.

    :param memoria: Series de RSS por versión, tal como las devuelve
        :func:`perfilar_memoria`.
    :type memoria: dict[str, dict]
    :return: El HTML de la sección, o una cadena vacía si no hay datos.
    :rtype: str
    """
    if not memoria:
        return ""

    filas_memoria = []

    for version in VERSIONES:
        medida = memoria.get(version, {})

        if "pico_mb" not in medida:
            continue

        filas_memoria.append(
            (
                ETIQUETAS[version],
                f"{_mb(medida['base_mb'])} MB",
                f"{_mb(medida['pico_mb'])} MB",
                f"{_mb(medida['pico_mb'] - medida['base_mb'])} MB",
            )
        )

    return (
        "<h3>memory_profiler — RSS muestreado</h3>"
        '<div class="envoltura-tabla">'
        + _tabla_html(("Versión", "Base", "Pico", "Crecimiento"), filas_memoria)
        + "</div>"
        + '<p class="nota">Cada versión se automuestrea dentro de su propio '
        "proceso, "
        "con <code>include_children=True</code>: sin esa opción la versión "
        "concurrente "
        "reportaría solo la memoria del padre. Estos picos son "
        "<strong>mayores</strong> que "
        "la columna RSS de la tabla comparativa porque no miden lo mismo: "
        "<code>include_children</code> <strong>suma</strong> padre e hijos, "
        "mientras "
        "<code>ru_maxrss</code> informa el <strong>máximo</strong> de un solo "
        "proceso del "
        "árbol. Las dos cifras son correctas; responden preguntas distintas.</p>"
    )


def _html_scalene(scalene):
    """
    Arma la sección de Scalene: las líneas más caras en CPU y memoria.

    :param scalene: Hallazgos por versión, tal como los devuelve
        :func:`perfilar_scalene`.
    :type scalene: dict
    :return: El HTML de la sección, o una cadena vacía si no hay datos.
    :rtype: str
    """
    if not scalene:
        return ""

    partes = ["<h3>Scalene — CPU y memoria por línea</h3>"]

    for version, datos in scalene.items():
        if isinstance(datos, dict) and "omitido" in datos:
            partes.append(
                f"<p><strong>{ETIQUETAS.get(version, version)}</strong> — omitido: "
                f"{html.escape(datos['omitido'])}.</p>"
            )
            continue

        if not isinstance(datos, dict) or "resumen" not in datos:
            partes.append(
                f"<p><strong>{ETIQUETAS.get(version, version)}</strong> — "
                f"{html.escape(str(datos)[:300])}</p>"
            )
            continue

        resumen_sc = datos["resumen"]
        filas = [
            (
                f"<code>{html.escape(linea['ubicacion'])}</code>",
                f"<code>{html.escape(linea['codigo'])}</code>",
                f"{linea['cpu_pct']:.1f} %",
                f"{linea['memoria_mb']:.1f} MB",
            )
            for linea in (resumen_sc.get("top") or [])[:8]
        ]
        partes.append(
            f"<p><strong>{ETIQUETAS[version]}</strong> — "
            f"<code>{datos['ver_con']}</code></p>"
            + (
                '<div class="envoltura-tabla">'
                + _tabla_html(("Línea", "Código", "CPU", "Memoria pico"), filas)
                + "</div>"
                if filas
                else "<p>Sin líneas por encima del umbral de muestreo.</p>"
            )
        )

    return "".join(partes)


def _html_pyspy(pyspy):
    """
    Arma la sección de py-spy: los flamegraphs o los comandos para generarlos.

    :param pyspy: Hallazgos de :func:`perfilar_pyspy`: por versión, o con la
        clave ``omitido`` si no se ejecutó.
    :type pyspy: dict
    :return: El HTML de la sección, o una cadena vacía si no hay datos.
    :rtype: str
    """
    if not pyspy:
        return ""

    partes = ["<h3>py-spy — muestreo externo y flamegraph</h3>"]

    if "omitido" in pyspy:
        comandos = "\n".join(pyspy["comandos"])
        partes.append(
            f"<p>{html.escape(pyspy['omitido'])}. Es la única de las cinco "
            "que "
            "perfila un proceso <strong>ya en marcha</strong> sin instrumentarlo, "
            "y la única "
            "que ve los procesos hijos con <code>--subprocesses</code>.</p>"
            f"<pre><code>{html.escape(comandos)}</code></pre>"
        )
        return "".join(partes)

    for version, datos in pyspy.items():
        detalle = datos.get("archivo") or datos.get("error", "")
        partes.append(
            f"<p><strong>{ETIQUETAS.get(version, version)}</strong> — "
            f"{html.escape(str(detalle))}</p>"
        )

    return "".join(partes)


def generar_reporte(resultados):
    """
    Arma el reporte HTML autocontenido en profiles/reporte.html.

    Cada sección la arma su propia función y queda vacía si no hay datos
    para ella; el reporte las concatena en orden.

    :param resultados: Resultados acumulados en ``profiles/perfilado.json``.
    :type resultados: dict
    :return: Ruta de ``profiles/reporte.html``.
    :rtype: pathlib.Path
    """
    resumen = resultados.get("comparativa") or {}
    memoria = resultados.get("memoria") or {}

    partes = [
        _html_encabezado(resultados.get("entorno") or {}),
        _html_comparativa(resumen),
        _html_preguntas(responder_preguntas(resultados)),
        _html_graficos(resumen, resultados.get("escalabilidad") or {}, memoria),
        "<h2>Hallazgos por herramienta</h2>",
        _html_cprofile(resultados.get("cprofile") or {}),
        _html_line_profiler(resultados.get("line_profiler") or {}),
        _html_memoria(memoria),
        _html_scalene(resultados.get("scalene") or {}),
        _html_pyspy(resultados.get("pyspy") or {}),
        """
    <footer>
      <p>Generado por <code>src/perfilado.py</code>.
         Reproducible con <code>.venv/bin/python src/perfilado.py --todo</code>.</p>
    </footer>""",
    ]

    documento = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Perfilado y medición — Buscador Eficiente de Información</title>
<style>{ESTILOS}</style>
</head>
<body><div class="envoltorio">{"".join(partes)}</div></body>
</html>"""

    destino = DIR_PERFILES / "reporte.html"
    destino.write_text(documento, encoding="utf-8")

    return destino


# ============================================================
# MAIN
# ============================================================


def _estado_del_gil():
    """
    `sys._is_gil_enabled()` existe recién desde Python 3.13.

    :return: El estado del GIL, como texto para el reporte.
    :rtype: str
    """
    consultar = getattr(sys, "_is_gil_enabled", None)

    if consultar is None:
        return "GIL activo (build sin free-threading)"

    return f"GIL {'activo' if consultar() else 'desactivado'}"


def _entorno():
    """
    Describe el equipo y el intérprete en que se midió.

    :return: CPU, núcleos, sistema operativo, versión de Python, estado del GIL y la
        consulta de referencia.
    :rtype: dict[str, str]
    """
    return {
        "cpu": platform.processor() or platform.machine(),
        "nucleos": f"{os.cpu_count()} lógicos",
        "so": f"{platform.system()} {platform.release()}",
        "python": f"CPython {platform.python_version()}",
        "gil": _estado_del_gil(),
        "consulta": f'consulta de referencia: "{CONSULTA}"',
    }


def _crear_parser():
    """
    Define las opciones de la línea de comandos.

    :return: El parser con las fases que se pueden pedir y las opciones
        internas (``--medir`` y sus variantes) que usa el propio orquestador.
    :rtype: argparse.ArgumentParser
    """
    parser = argparse.ArgumentParser(description="Perfilado y medición del buscador")

    parser.add_argument(
        "--medir",
        choices=VERSIONES,
        help="modo interno: mide una versión e imprime su JSON",
    )
    parser.add_argument(
        "--perfil-cprofile",
        type=str,
        default=None,
        help="modo interno: envuelve la medición en cProfile",
    )
    parser.add_argument(
        "--con-tracemalloc",
        action="store_true",
        help="modo interno: mide asignaciones (encarece el tiempo)",
    )
    parser.add_argument(
        "--serie-memoria",
        action="store_true",
        help="modo interno: se automuestrea el RSS con memory_profiler",
    )

    parser.add_argument("--todo", action="store_true", help="pipeline completo")
    parser.add_argument("--comparativa", action="store_true")
    parser.add_argument("--escalabilidad", action="store_true")
    parser.add_argument("--cprofile", action="store_true")
    parser.add_argument("--line", action="store_true")
    parser.add_argument("--memoria", action="store_true")
    parser.add_argument("--scalene", action="store_true")
    parser.add_argument("--pyspy", action="store_true")
    parser.add_argument(
        "--ejecutar-pyspy",
        action="store_true",
        help="ejecuta py-spy (pedirá sudo en macOS)",
    )
    parser.add_argument("--graficos", action="store_true")
    parser.add_argument("--reporte", action="store_true")

    parser.add_argument("--directorio", type=str, default=str(CORPUS_PRINCIPAL))
    parser.add_argument("--rondas", type=int, default=3)
    parser.add_argument("--repeticiones", type=int, default=10)
    parser.add_argument(
        "--tamanos",
        type=str,
        default=None,
        help="tamaños del barrido, separados por coma",
    )

    return parser


def _medir_modo_interno(args, corpus_dir):
    """
    Mide una sola versión en este proceso e imprime su JSON.

    Es el modo que usa :func:`_medir_en_subproceso`: el orquestador se
    invoca a sí mismo con ``--medir`` para medir cada versión en un
    proceso limpio. Según las opciones, envuelve la medición en
    memory_profiler o en cProfile.

    :param args: Opciones de la línea de comandos.
    :type args: argparse.Namespace
    :param corpus_dir: Directorio del corpus.
    :type corpus_dir: pathlib.Path
    """
    if args.serie_memoria:
        from memory_profiler import memory_usage

        serie, medicion = memory_usage(
            (
                medir_version,
                (args.medir, corpus_dir, args.repeticiones, args.con_tracemalloc),
            ),
            interval=0.05,
            include_children=True,
            retval=True,
        )
        medicion["serie_mb"] = serie

    elif args.perfil_cprofile:
        import cProfile

        perfilador = cProfile.Profile()
        perfilador.enable()
        medicion = medir_version(
            args.medir, corpus_dir, args.repeticiones, args.con_tracemalloc
        )
        perfilador.disable()
        perfilador.dump_stats(args.perfil_cprofile)
    else:
        medicion = medir_version(
            args.medir, corpus_dir, args.repeticiones, args.con_tracemalloc
        )

    print(MARCA_JSON + json.dumps(medicion))


def _persistir(resultados, archivo, fase):
    """
    Vuelca el estado apenas termina una fase.

    Las fases son largas y esta máquina se queda sin aire: si el
    volcado fuera solo al final, un corte a mitad de camino
    tiraría también las fases que ya habían terminado bien.

    :param resultados: Resultados acumulados hasta el momento.
    :type resultados: dict
    :param archivo: Ruta de ``profiles/perfilado.json``.
    :type archivo: pathlib.Path
    :param fase: Nombre de la fase que terminó, para el mensaje.
    :type fase: str
    """
    archivo.write_text(
        json.dumps(resultados, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        f"  ✓ {fase} guardada en {archivo.relative_to(BASE_DIR)}",
        flush=True,
    )


def _correr_mediciones(args, resultados, archivo, corpus_dir, tamanos):
    """
    Corre la comparativa y el barrido de escalabilidad, si se pidieron.

    :param args: Opciones de la línea de comandos.
    :type args: argparse.Namespace
    :param resultados: Resultados acumulados; se completan en el lugar.
    :type resultados: dict
    :param archivo: Ruta de ``profiles/perfilado.json``.
    :type archivo: pathlib.Path
    :param corpus_dir: Directorio del corpus de la comparativa.
    :type corpus_dir: pathlib.Path
    :param tamanos: Tamaños de corpus del barrido de escalabilidad.
    :type tamanos: tuple[int, ...]
    """
    if args.todo or args.comparativa:
        print(f"\n[comparativa] corpus {corpus_dir}")
        resultados["comparativa"] = comparativa(
            corpus_dir, args.rondas, args.repeticiones
        )["resumen"]
        _persistir(resultados, archivo, "comparativa")

    if args.todo or args.escalabilidad:
        resultados["escalabilidad"] = escalabilidad(
            tamanos, max(1, args.rondas - 1), args.repeticiones
        )
        _persistir(resultados, archivo, "escalabilidad")


def _correr_perfiladores(args, resultados, archivo, corpus_dir, corpus_liviano):
    """
    Corre las herramientas de perfilado que se pidieron, en orden.

    :param args: Opciones de la línea de comandos.
    :type args: argparse.Namespace
    :param resultados: Resultados acumulados; se completan en el lugar.
    :type resultados: dict
    :param archivo: Ruta de ``profiles/perfilado.json``.
    :type archivo: pathlib.Path
    :param corpus_dir: Directorio del corpus principal, para memory_profiler.
    :type corpus_dir: pathlib.Path
    :param corpus_liviano: Corpus chico, para las herramientas que
        instrumentan línea a línea y encarecen mucho la ejecución.
    :type corpus_liviano: pathlib.Path
    """
    # (pedida, clave en perfilado.json, nombre de la fase, perfilador)
    fases = (
        (
            args.cprofile,
            "cprofile",
            "cProfile",
            lambda: perfilar_cprofile(corpus_liviano, VERSIONES),
        ),
        (
            args.line,
            "line_profiler",
            "line_profiler",
            lambda: perfilar_line(corpus_liviano, VERSIONES),
        ),
        (
            args.memoria,
            "memoria",
            "memory_profiler",
            lambda: perfilar_memoria(corpus_dir, VERSIONES),
        ),
        (
            args.scalene,
            "scalene",
            "scalene",
            lambda: perfilar_scalene(corpus_liviano, VERSIONES),
        ),
        (
            args.pyspy,
            "pyspy",
            "py-spy",
            lambda: perfilar_pyspy(corpus_liviano, VERSIONES, args.ejecutar_pyspy),
        ),
    )

    for pedida, clave, nombre, perfilar in fases:
        if not (args.todo or pedida):
            continue

        print(f"\n[{nombre}]")
        resultados[clave] = perfilar()
        _persistir(resultados, archivo, nombre)


def _generar_salidas(args, resultados):
    """
    Genera los gráficos, el reporte HTML y la tabla comparativa.

    :param args: Opciones de la línea de comandos.
    :type args: argparse.Namespace
    :param resultados: Resultados acumulados en ``profiles/perfilado.json``.
    :type resultados: dict
    """
    if args.todo or args.graficos:
        print("\n[gráficos]")
        generar_graficos(resultados)

    if args.todo or args.reporte:
        destino = generar_reporte(resultados)
        print(f"\n[reporte] {destino.relative_to(BASE_DIR)}")

    if resultados.get("comparativa"):
        print("\n" + tabla_markdown(resultados["comparativa"]))

        tabla = DIR_PERFILES / "comparativa.md"
        tabla.write_text(
            tabla_markdown(resultados["comparativa"]) + "\n", encoding="utf-8"
        )
        print(f"\nTabla guardada en {tabla.relative_to(BASE_DIR)}")


def main():
    """
    Ejecuta las fases de medición pedidas por línea de comandos.

    Cada fase vuelca su resultado en ``profiles/perfilado.json`` apenas
    termina. Con ``--medir`` corre en modo interno: mide una sola
    versión e imprime su JSON para el proceso orquestador.
    """
    args = _crear_parser().parse_args()

    corpus_dir = Path(args.directorio)

    # ---- modo interno: una versión, un proceso limpio
    if args.medir:
        _medir_modo_interno(args, corpus_dir)
        return

    DIR_PERFILES.mkdir(exist_ok=True)

    archivo_resultados = DIR_PERFILES / "perfilado.json"

    resultados = (
        json.loads(archivo_resultados.read_text(encoding="utf-8"))
        if archivo_resultados.exists()
        else {}
    )
    resultados["entorno"] = _entorno()

    tamanos = (
        tuple(int(tamano) for tamano in args.tamanos.split(","))
        if args.tamanos
        else TAMANOS
    )

    # El corpus chico mantiene acotado el costo de las herramientas
    # que instrumentan línea a línea.
    corpus_liviano = corpus_de(min(tamanos))

    _correr_mediciones(args, resultados, archivo_resultados, corpus_dir, tamanos)
    _correr_perfiladores(
        args, resultados, archivo_resultados, corpus_dir, corpus_liviano
    )
    _generar_salidas(args, resultados)


if __name__ == "__main__":
    main()
