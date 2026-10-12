"""
Versión optimizada del Buscador Eficiente de Información.

Índice invertido en memoria. El costo se invierte: se paga una
indexación única O(N) sobre el total de tokens del corpus, y cada
consulta pasa de O(n * m) a O(t + r), donde t son los términos de la
consulta y r los documentos candidatos (no el tamaño del corpus).

Estructuras y técnicas usadas en este script:

- ``dict``: índice invertido, término -> {doc_id: frecuencia}.
- ``set``: intersección de postings en ``O(min(|A|, |B|))``.
- ``heapq.nlargest``: ranking top-k en O(r * log k) en vez de O(r * log r).
- ``lru_cache``: memoización de la normalización y el stemming (ver
  :mod:`core.procesamiento_texto`).
- ``OrderedDict``: caché LRU de consultas (:class:`QueryCache`).

Comandos para correr el script (desde cualquier directorio; el corpus
siempre se genera y se lee en ``<repo>/data/corpus``)::

    python3 src/baseline.py --generar --num-docs 50000
    python3 src/optimizado.py --query "algoritmo" --top-k 10
"""

import argparse
import heapq
import math
import time
from collections import Counter, OrderedDict
from pathlib import Path

from core.procesamiento_texto import tokenizar


# ============================================================
# CONFIGURACIÓN
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = BASE_DIR / "data" / "corpus"


# ============================================================
# ÍNDICE INVERTIDO
# ============================================================


def construir_indice(corpus_dir):
    """
    Construye el índice invertido de todos los ``.txt`` del corpus.

    El doc_id de cada documento es su posición en la lista ordenada de
    archivos. Los archivos que no se pueden leer quedan fuera del índice,
    pero conservan su doc_id. Estructura y ejemplo::

        término -> {doc_id: frecuencia}

        {"java": {1: 3, 5: 2, 8: 1}}

    :param corpus_dir: Directorio del corpus.
    :type corpus_dir: pathlib.Path
    :return: Tupla ``(indice, archivos)``: el índice invertido y la lista
        ordenada de rutas, cuya posición es el doc_id.
    :rtype: tuple[dict[str, dict[int, int]], list[pathlib.Path]]
    """
    indice = {}

    archivos = sorted(corpus_dir.glob("*.txt"))

    for doc_id, archivo in enumerate(archivos):
        try:
            texto = archivo.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        tokens = tokenizar(texto)

        # Contamos cuántas veces aparece cada término
        frecuencias = Counter(tokens)

        for termino, frecuencia in frecuencias.items():
            if termino not in indice:
                indice[termino] = {}

            indice[termino][doc_id] = frecuencia

    return indice, archivos


# ============================================================
# CACHE DE CONSULTAS
# ============================================================


class QueryCache:
    """
    Caché LRU de resultados de consultas.

    Guarda como máximo ``maxsize`` consultas y, al superar ese límite,
    descarta la usada hace más tiempo. Cuenta aciertos y fallos para
    poder medir su efectividad (ver :meth:`info`).
    """

    def __init__(self, maxsize=1024):
        """
        Crea una caché vacía.

        :param maxsize: Cantidad máxima de consultas que se guardan.
        :type maxsize: int
        """
        self.maxsize = maxsize
        self.cache = OrderedDict()

        self.hits = 0
        self.misses = 0

    def get(self, clave):
        """
        Devuelve el resultado guardado para una clave y lo marca como reciente.

        Cuenta un acierto si la clave está y un fallo si no.

        :param clave: Clave de la consulta, ``(terminos, top_k)``.
        :type clave: tuple
        :return: El resultado guardado, o ``None`` si la clave no está.
        :rtype: object | None
        """
        if clave not in self.cache:
            self.misses += 1
            return None

        self.hits += 1

        # La consulta pasa a ser la más recientemente utilizada
        self.cache.move_to_end(clave)

        return self.cache[clave]

    def put(self, clave, valor):
        """
        Guarda un resultado y, si se supera el límite, descarta el más viejo.

        :param clave: Clave de la consulta, ``(terminos, top_k)``.
        :type clave: tuple
        :param valor: Resultado que se guarda.
        :type valor: object
        """
        if clave in self.cache:
            self.cache.move_to_end(clave)

        self.cache[clave] = valor

        # Eliminamos la consulta menos utilizada
        if len(self.cache) > self.maxsize:
            self.cache.popitem(last=False)

    def info(self):
        """
        Devuelve las estadísticas de uso de la caché.

        :return: Diccionario con ``hits`` (aciertos), ``misses`` (fallos) y
            ``size`` (consultas guardadas).
        :rtype: dict[str, int]
        """
        return {"hits": self.hits, "misses": self.misses, "size": len(self.cache)}


# ============================================================
# CONSULTA DEL ÍNDICE
# ============================================================


def normalizar_consulta(consulta):
    """
    Convierte la consulta en una tupla canónica de términos.

    Elimina repetidos y ordena los términos, para que consultas
    equivalentes como ``"Java Concurrencia"`` y ``"concurrencia java"``
    tengan la misma representación y compartan la entrada de la caché.

    :param consulta: Texto de la consulta.
    :type consulta: str
    :return: Términos normalizados, sin repetidos y en orden alfabético.
    :rtype: tuple[str, ...]
    """
    tokens = tokenizar(consulta)

    return tuple(sorted(set(tokens)))


def buscar(indice, terminos):
    """
    Busca los documentos que contienen todos los términos de la consulta.

    Intersecta las listas de *postings* empezando por la del término
    menos frecuente, para que el conjunto de candidatos se reduzca lo
    antes posible. Recibe la consulta ya normalizada (ver
    :func:`normalizar_consulta`) para no volver a tokenizarla.

    :param indice: Índice invertido: término -> {doc_id: frecuencia}.
    :type indice: dict[str, dict[int, int]]
    :param terminos: Términos normalizados de la consulta.
    :type terminos: tuple[str, ...]
    :return: Identificadores de los documentos que contienen todos los
        términos. Vacío si la consulta no tiene términos o si alguno no
        figura en el índice.
    :rtype: set[int]
    """
    if not terminos:
        return set()

    postings = []

    for termino in terminos:
        if termino not in indice:
            return set()

        postings.append(indice[termino])

    # Primero usamos los términos menos frecuentes, para que el
    # conjunto candidato se reduzca lo antes posible.
    postings.sort(key=len)

    candidatos = set(postings[0])

    for posting in postings[1:]:
        candidatos &= posting.keys()

        if not candidatos:
            break

    return candidatos


# ============================================================
# RANKING TOP-K
# ============================================================


def rankear(indice, terminos, candidatos, top_k, total_docs):
    """
    Puntúa los candidatos con TF-IDF y devuelve los ``top_k`` mejores.

    Memoria auxiliar O(top_k): los scores se evalúan al vuelo y
    ``heapq.nlargest`` mantiene solo ``top_k`` elementos en el heap. No
    se materializa ningún diccionario de tamaño O(r). Los empates se
    resuelven a favor del doc_id más bajo, para que el orden sea
    determinista.

    :param indice: Índice invertido: término -> {doc_id: frecuencia}.
    :type indice: dict[str, dict[int, int]]
    :param terminos: Términos normalizados de la consulta. Si hay
        candidatos, todos figuran en el índice.
    :type terminos: tuple[str, ...]
    :param candidatos: Documentos que contienen todos los términos (ver
        :func:`buscar`).
    :type candidatos: set[int]
    :param top_k: Cantidad máxima de documentos a devolver.
    :type top_k: int
    :param total_docs: Cantidad de documentos del corpus, para el IDF.
    :type total_docs: int
    :return: Pares ``(doc_id, score)`` ordenados de mayor a menor score.
        Vacío si no hay candidatos o si ``top_k`` no es positivo.
    :rtype: list[tuple[int, float]]
    """
    if not candidatos or top_k <= 0:
        return []

    pesos = [
        (indice[termino], math.log(total_docs / len(indice[termino])))
        for termino in terminos
    ]

    def puntuados():
        """
        Genera el score de cada candidato al vuelo, sin guardarlos.

        :return: Pares ``(score, -doc_id)`` que ``heapq.nlargest`` consume de a uno.
        :rtype: collections.abc.Iterator[tuple[float, int]]
        """
        # El caso de un solo término es el más frecuente y evita
        # el bucle interno por candidato.
        if len(pesos) == 1:
            postings, idf = pesos[0]

            for doc_id in candidatos:
                yield (postings.get(doc_id, 0) * idf, -doc_id)

            return

        for doc_id in candidatos:
            score = 0.0

            for postings, idf in pesos:
                score += postings.get(doc_id, 0) * idf

            yield (score, -doc_id)

    # El doc_id va negado para desempatar por el documento más
    # antiguo y hacer el orden determinista.
    return [
        (-doc_id_invertido, score)
        for score, doc_id_invertido in heapq.nlargest(top_k, puntuados())
    ]


# ============================================================
# BUSCADOR COMPLETO
# ============================================================


class Buscador:
    """
    Motor de búsqueda sobre un índice invertido ya construido.

    Combina la intersección de *postings* (:func:`buscar`), el ranking
    TF-IDF top-k (:func:`rankear`) y una caché LRU de consultas
    (:class:`QueryCache`). El índice se construye una sola vez con
    :func:`construir_indice` y se reutiliza en todas las consultas.
    """

    def __init__(self, indice, archivos, cache_size=1024):
        """
        Inicializa el buscador con un índice y su caché de consultas.

        :param indice: Índice invertido: término -> {doc_id: frecuencia}.
        :type indice: dict[str, dict[int, int]]
        :param archivos: Rutas del corpus. La posición de cada archivo en
            la lista es su doc_id.
        :type archivos: list[pathlib.Path]
        :param cache_size: Cantidad máxima de consultas que guarda la caché.
        :type cache_size: int
        """
        self.indice = indice
        self.archivos = archivos

        self.cache = QueryCache(cache_size)

    def buscar(self, consulta, top_k=10):
        """
        Resuelve una consulta y devuelve sus mejores resultados.

        El total de coincidencias y el top-k se devuelven por separado
        para no confundir el tamaño del resultado con el tamaño de la
        página mostrada. Las consultas equivalentes, como
        ``"Java Concurrencia"`` y ``"concurrencia java"``, comparten la
        misma entrada de la caché.

        :param consulta: Texto de la consulta, tal como lo escribe el usuario.
        :type consulta: str
        :param top_k: Cantidad máxima de documentos a devolver.
        :type top_k: int
        :return: Tupla ``(total_coincidencias, resultados)``, donde
            ``resultados`` es una lista de pares ``(doc_id, score)``
            ordenada de mayor a menor score.
        :rtype: tuple[int, list[tuple[int, float]]]
        """
        terminos = normalizar_consulta(consulta)

        clave = (terminos, top_k)

        # Primero consultamos la caché
        resultado_cache = self.cache.get(clave)

        if resultado_cache is not None:
            return resultado_cache

        # Si no estaba en caché, buscamos y rankeamos
        candidatos = buscar(self.indice, terminos)

        resultado = (
            len(candidatos),
            rankear(self.indice, terminos, candidatos, top_k, len(self.archivos)),
        )

        self.cache.put(clave, resultado)

        return resultado


# ============================================================
# MOSTRAR RESULTADOS
# ============================================================


def mostrar_resultados(resultados, archivos):
    """
    Imprime el ranking en la consola, un documento por línea.

    :param resultados: Pares ``(doc_id, score)`` devueltos por
        :meth:`Buscador.buscar`.
    :type resultados: list[tuple[int, float]]
    :param archivos: Rutas del corpus; la posición de cada una es su doc_id.
    :type archivos: list[pathlib.Path]
    """
    print()
    print("Resultados:")
    print("-" * 60)

    if not resultados:
        print("No se encontraron documentos.")
        return

    for posicion, (doc_id, score) in enumerate(resultados, start=1):
        nombre = archivos[doc_id].name

        print(f"{posicion}. {nombre} (score={score:.4f})")


# ============================================================
# MAIN
# ============================================================


def main():
    """
    Ejecuta el buscador optimizado desde la línea de comandos.

    Construye el índice del corpus e informa cuánto tardó. Si se pasa
    ``--query``, resuelve la consulta y muestra el ranking y el estado
    de la caché.
    """
    parser = argparse.ArgumentParser(
        description="Buscador optimizado con índice invertido"
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
        "--cache-size",
        type=int,
        default=1024,
        help="Cantidad máxima de consultas almacenadas",
    )

    args = parser.parse_args()

    corpus_dir = Path(args.directorio)

    if not corpus_dir.exists():
        print(f"Error: no existe el directorio {corpus_dir}")
        return

    print("Construyendo índice invertido...")

    inicio_indice = time.perf_counter()

    indice, archivos = construir_indice(corpus_dir)

    tiempo_indice = (time.perf_counter() - inicio_indice) * 1000

    print(f"Documentos indexados: {len(archivos)}")

    print(f"Términos en el índice: {len(indice)}")

    print(f"Tiempo de construcción del índice: {tiempo_indice:.2f} ms")

    if not args.query:
        return

    buscador = Buscador(indice, archivos, args.cache_size)

    inicio_busqueda = time.perf_counter()

    total, resultados = buscador.buscar(args.query, args.top_k)

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

    mostrar_resultados(resultados, archivos)

    print()
    print("Información de caché:")
    print(buscador.cache.info())


if __name__ == "__main__":
    main()
