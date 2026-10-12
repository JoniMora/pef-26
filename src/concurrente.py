"""
Versión Concurrente — Buscador Eficiente de Información
------------------------------------------------------------
Refactorización de la fase de indexación como un MapReduce de un
solo nodo. La construcción del índice es CPU-bound (tokenización,
normalización y stemming), por lo que `threading` no aporta
paralelismo real bajo el GIL: se usa `ProcessPoolExecutor`, donde
cada intérprete hijo posee su propio GIL.

    Particionado   lista de documentos -> P * K lotes equitativos
    Map            _procesar_lote() -> índice invertido parcial
    Reduce         fusión de los parciales en el índice global

Los lotes son disjuntos y los workers no comparten estado mutable:
no hay locks ni condiciones de carrera por construcción.

Comandos para correr el script (desde cualquier directorio;
el corpus siempre se genera/lee en <repo>/data/corpus):
    python3 src/baseline.py --generar --num-docs 50000
    python3 src/concurrente.py --query "algoritmo" --top-k 10
    python3 src/concurrente.py --query "algoritmo" --workers 4 --comparar
"""

import argparse
import os
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from optimizado import (
    DEFAULT_CORPUS,
    Buscador,
    construir_indice as construir_indice_secuencial,
    mostrar_resultados,
    tokenizar,
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
    Construye el índice invertido parcial de un subconjunto del
    corpus. Se ejecuta en un proceso hijo.

    Recibe pares (doc_id, ruta) — el doc_id se asigna en el padre
    para que sea global y estable — y retorna:

        término -> {doc_id -> frecuencia}

    Función pura: no lee ni escribe estado compartido, por lo que
    el resultado no depende del orden de despacho de los lotes.
    """

    parcial = {}

    for doc_id, ruta in lote_archivos:

        try:
            with open(ruta, encoding="utf-8", errors="ignore") as archivo:
                texto = archivo.read()
        except OSError:
            continue

        frecuencias = Counter(tokenizar(texto))

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
    """

    for termino, postings in parcial.items():

        destino = indice.get(termino)

        if destino is None:
            indice[termino] = postings
        else:
            destino.update(postings)


def construir_indice(corpus_dir, workers=None, lotes_por_proceso=LOTES_POR_PROCESO):
    """
    Construye el índice invertido en paralelo.

    Devuelve (indice, archivos), con la misma estructura y el mismo
    orden de doc_id que la versión secuencial:

        término -> {doc_id -> frecuencia}
    """

    archivos = sorted(Path(corpus_dir).glob("*.txt"))

    if not archivos:
        return {}, archivos

    procesos = workers or os.cpu_count() or 1
    procesos = max(1, min(procesos, len(archivos)))

    # Las rutas viajan como str: Path se serializa más caro y el
    # worker solo necesita abrirlas.
    tareas = [
        (doc_id, str(archivo))
        for doc_id, archivo in enumerate(archivos)
    ]

    if procesos == 1 or len(archivos) < UMBRAL_PARALELO:
        return _procesar_lote(tareas), archivos

    lotes = _lotes_equitativos(tareas, procesos * lotes_por_proceso)

    indice = {}

    with ProcessPoolExecutor(max_workers=procesos) as pool:

        futuros = [
            pool.submit(_procesar_lote, lote)
            for lote in lotes
        ]

        # as_completed fusiona en orden de finalización: el padre
        # reduce mientras los workers siguen mapeando.
        for futuro in as_completed(futuros):
            _fusionar(indice, futuro.result())

    return indice, archivos


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="Buscador con indexación paralela (MapReduce)"
    )

    parser.add_argument(
        "--query",
        type=str,
        help="Consulta a realizar"
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Cantidad de resultados"
    )

    parser.add_argument(
        "--directorio",
        type=str,
        default=str(DEFAULT_CORPUS),
        help="Directorio donde se encuentra el corpus"
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Cantidad de procesos (por defecto os.cpu_count())"
    )

    parser.add_argument(
        "--cache-size",
        type=int,
        default=1024,
        help="Cantidad máxima de consultas almacenadas"
    )

    parser.add_argument(
        "--comparar",
        action="store_true",
        help="Mide también la indexación secuencial y el speedup"
    )

    args = parser.parse_args()

    corpus_dir = Path(args.directorio)

    if not corpus_dir.exists():
        print(f"Error: no existe el directorio {corpus_dir}")
        return

    procesos = args.workers or os.cpu_count() or 1

    print(f"Construyendo índice invertido con {procesos} procesos...")

    inicio_indice = time.perf_counter()

    indice, archivos = construir_indice(
        corpus_dir,
        args.workers
    )

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

    buscador = Buscador(
        indice,
        archivos,
        args.cache_size
    )

    inicio_busqueda = time.perf_counter()

    total, resultados = buscador.buscar(
        args.query,
        args.top_k
    )

    tiempo_busqueda = (time.perf_counter() - inicio_busqueda) * 1000

    print()
    print(f"Tiempo de búsqueda: {tiempo_busqueda:.4f} ms")

    if total > len(resultados):
        print(
            f"Documentos encontrados: {total} "
            f"(se muestran los {len(resultados)} mejores)"
        )
    else:
        print(f"Documentos encontrados: {total}")

    mostrar_resultados(
        resultados,
        archivos
    )


# La guarda es obligatoria: con el método de arranque spawn
# (macOS/Windows) cada proceso hijo reimporta este módulo, y sin
# ella el pool se recrearía en cascada — fork bomb.
if __name__ == "__main__":
    main()
