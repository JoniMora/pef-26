"""
Versión concurrente del Buscador Eficiente de Información.

Refactorización de la fase de indexación como un MapReduce de un
solo nodo. La construcción del índice es CPU-bound (tokenización,
normalización y stemming), por lo que ``threading`` no aporta
paralelismo real bajo el GIL: se usa ``ProcessPoolExecutor``, donde
cada intérprete hijo posee su propio GIL.

- **Particionado:** lista de documentos -> P * K lotes equitativos.
- **Map:** ``_procesar_lote()`` -> índice invertido parcial.
- **Reduce:** fusión de los parciales en el índice global.

Los lotes son disjuntos y los workers no comparten estado mutable:
no hay locks ni condiciones de carrera por construcción.

Comandos para correr el script (desde cualquier directorio; el corpus
siempre se genera y se lee en ``<repo>/data/corpus``)::

    python3 src/baseline.py --generar --num-docs 50000
    python3 src/concurrente.py --query "algoritmo" --top-k 10
    python3 src/concurrente.py --query "algoritmo" --workers 4 --comparar
"""

import argparse
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from core.lectura import contar_terminos
from optimizado import (
    DEFAULT_CORPUS,
    construir_indice as construir_indice_secuencial,
    resolver_consulta,
)


# ============================================================
# CONFIGURACIÓN
# ============================================================

# Lotes por proceso. Con K > 1 hay más tareas que workers, así el
# pool reequilibra la carga cuando un lote resulta más pesado que
# otro, sin llegar a la granularidad por archivo (IPC dominante).
LOTES_POR_PROCESO = 4

# Por debajo de este volumen el arranque del pool y el pickle de
# los índices parciales cuestan más que el trabajo que ahorran.
UMBRAL_PARALELO = 512


# ============================================================
# PARTICIONADO
# ============================================================


def _lotes_equitativos(items, cantidad_lotes):
    """
    Reparte items en lotes contiguos de tamaño equitativo.

    El resto de la división se distribuye de a un elemento entre
    los primeros lotes, de modo que ninguno difiera en más de uno.

    :param items: Elementos a repartir.
    :type items: list
    :param cantidad_lotes: Cantidad de lotes deseada. Si hay menos elementos que lotes,
        se generan tantos lotes como elementos.
    :type cantidad_lotes: int
    :return: Los lotes, en el orden original. Vacío si no hay elementos o si
        ``cantidad_lotes`` no es positiva.
    :rtype: list[list]
    """
    total = len(items)

    if total == 0 or cantidad_lotes <= 0:
        return []

    cantidad_lotes = min(cantidad_lotes, total)

    tamano, resto = divmod(total, cantidad_lotes)

    lotes = []
    inicio = 0

    for posicion in range(cantidad_lotes):
        fin = inicio + tamano + (1 if posicion < resto else 0)

        lotes.append(items[inicio:fin])

        inicio = fin

    return lotes


# ============================================================
# FASE MAP
# ============================================================


def _procesar_lote(lote_archivos):
    """
    Construye el índice invertido parcial de un lote del corpus.

    Se ejecuta en un proceso hijo. Recibe pares ``(doc_id, ruta)`` —el
    doc_id se asigna en el padre para que sea global y estable— y
    devuelve la estructura ``término -> {doc_id: frecuencia}``.

    Función pura: no lee ni escribe estado compartido, por lo que
    el resultado no depende del orden de despacho de los lotes.

    :param lote_archivos: Pares ``(doc_id, ruta)`` del lote.
    :type lote_archivos: list[tuple[int, str]]
    :return: Índice invertido parcial del lote: término -> {doc_id: frecuencia}. Los
        archivos que no se pueden leer quedan fuera.
    :rtype: dict[str, dict[int, int]]
    """
    parcial = {}

    for doc_id, ruta in lote_archivos:
        try:
            frecuencias = contar_terminos(ruta)
        except OSError:
            continue

        for termino, frecuencia in frecuencias.items():
            postings = parcial.get(termino)

            if postings is None:
                parcial[termino] = {doc_id: frecuencia}
            else:
                postings[doc_id] = frecuencia

    return parcial


# ============================================================
# FASE REDUCE
# ============================================================


def _fusionar(indice, parcial):
    """
    Vuelca un índice parcial sobre el índice global.

    Los lotes son disjuntos, así que ningún doc_id se repite entre
    parciales: la fusión no necesita sumar frecuencias y el dict de
    postings del primer parcial se adopta tal cual, sin copiarlo.

    :param indice: Índice global; se modifica en el lugar.
    :type indice: dict[str, dict[int, int]]
    :param parcial: Índice parcial de un lote.
    :type parcial: dict[str, dict[int, int]]
    """
    for termino, postings in parcial.items():
        destino = indice.get(termino)

        if destino is None:
            indice[termino] = postings
        else:
            destino.update(postings)


def construir_indice(corpus_dir, workers=None, lotes_por_proceso=LOTES_POR_PROCESO):
    """
    Construye el índice invertido en paralelo, con un pool de procesos.

    Devuelve la misma estructura y el mismo orden de doc_id que
    :func:`optimizado.construir_indice`. Con un solo proceso, o con menos
    de ``UMBRAL_PARALELO`` archivos, indexa en el proceso padre: por
    debajo de ese volumen, levantar el pool cuesta más de lo que ahorra.

    :param corpus_dir: Directorio del corpus.
    :type corpus_dir: str | pathlib.Path
    :param workers: Cantidad de procesos; por defecto, ``os.cpu_count()``.
    :type workers: int | None
    :param lotes_por_proceso: Lotes por proceso. Con más de uno, el pool
        reequilibra la carga cuando un lote resulta más pesado que otro.
    :type lotes_por_proceso: int
    :return: Tupla ``(indice, archivos)``: el índice invertido y la lista
        ordenada de rutas, cuya posición es el doc_id.
    :rtype: tuple[dict[str, dict[int, int]], list[pathlib.Path]]
    """
    archivos = sorted(Path(corpus_dir).glob("*.txt"))

    if not archivos:
        return {}, archivos

    procesos = workers or os.cpu_count() or 1
    procesos = max(1, min(procesos, len(archivos)))

    # Las rutas viajan como str: Path se serializa más caro y el
    # worker solo necesita abrirlas.
    tareas = [(doc_id, str(archivo)) for doc_id, archivo in enumerate(archivos)]

    if procesos == 1 or len(archivos) < UMBRAL_PARALELO:
        return _procesar_lote(tareas), archivos

    lotes = _lotes_equitativos(tareas, procesos * lotes_por_proceso)

    indice = {}

    with ProcessPoolExecutor(max_workers=procesos) as pool:
        futuros = [pool.submit(_procesar_lote, lote) for lote in lotes]

        # as_completed fusiona en orden de finalización: el padre
        # reduce mientras los workers siguen mapeando.
        for futuro in as_completed(futuros):
            _fusionar(indice, futuro.result())

    return indice, archivos


# ============================================================
# MAIN
# ============================================================


def main():
    """
    Ejecuta el buscador concurrente desde la línea de comandos.

    Construye el índice en paralelo. Con ``--comparar`` también lo
    construye en forma secuencial para informar el speedup y verificar
    que los dos índices sean idénticos. Si se pasa ``--query``, resuelve
    la consulta y muestra el ranking.
    """
    parser = argparse.ArgumentParser(
        description="Buscador con indexación paralela (MapReduce)"
    )

    parser.add_argument("--query", type=str, help="Consulta a realizar")

    parser.add_argument("--top-k", type=int, default=10, help="Cantidad de resultados")

    parser.add_argument(
        "--directorio",
        type=str,
        default=str(DEFAULT_CORPUS),
        help="Directorio donde se encuentra el corpus",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Cantidad de procesos (por defecto os.cpu_count())",
    )

    parser.add_argument(
        "--cache-size",
        type=int,
        default=1024,
        help="Cantidad máxima de consultas almacenadas",
    )

    parser.add_argument(
        "--comparar",
        action="store_true",
        help="Mide también la indexación secuencial y el speedup",
    )

    args = parser.parse_args()

    corpus_dir = Path(args.directorio)

    if not corpus_dir.exists():
        print(f"Error: no existe el directorio {corpus_dir}")
        return

    procesos = args.workers or os.cpu_count() or 1

    print(f"Construyendo índice invertido con {procesos} procesos...")

    inicio_indice = time.perf_counter()

    indice, archivos = construir_indice(corpus_dir, args.workers)

    tiempo_indice = (time.perf_counter() - inicio_indice) * 1000

    print(f"Documentos indexados: {len(archivos)}")
    print(f"Términos en el índice: {len(indice)}")
    print(f"Tiempo de construcción del índice: {tiempo_indice:.2f} ms")

    if args.comparar:
        inicio_secuencial = time.perf_counter()

        indice_secuencial, _ = construir_indice_secuencial(corpus_dir)

        tiempo_secuencial = (time.perf_counter() - inicio_secuencial) * 1000

        print()
        print(f"Índice secuencial: {tiempo_secuencial:.2f} ms")
        print(f"Speedup: {tiempo_secuencial / tiempo_indice:.2f}x")
        print(f"Índices idénticos: {indice == indice_secuencial}")

    if not args.query:
        return

    resolver_consulta(indice, archivos, args.query, args.top_k, args.cache_size)


# La guarda es obligatoria: con el método de arranque spawn
# (macOS/Windows) cada proceso hijo reimporta este módulo, y sin
# ella el pool se recrearía en cascada — fork bomb.
if __name__ == "__main__":
    main()
