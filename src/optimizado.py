import argparse
import heapq
import re
import time
from collections import Counter, OrderedDict
from functools import lru_cache
from pathlib import Path


# ============================================================
# CONFIGURACIÓN
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = BASE_DIR / "data" / "corpus"

STOPWORDS = {
    "el", "la", "los", "las",
    "un", "una", "unos", "unas",
    "de", "del", "al",
    "y", "o",
    "en", "por", "para",
    "con", "sin",
    "que", "es",
    "se", "su", "sus",
    "a"
}


# ============================================================
# NORMALIZACIÓN
# ============================================================

@lru_cache(maxsize=10000)
def normalize(token):
    """
    Normaliza un token:
    - convierte a minúsculas
    - elimina caracteres no alfanuméricos
    """

    token = token.lower()
    token = re.sub(r"[^a-záéíóúüñ0-9]", "", token)

    return token


@lru_cache(maxsize=10000)
def stem(token):
    """
    Stemming muy sencillo.

    No utilizamos una librería externa.
    El objetivo es agrupar algunas variantes simples
    de una palabra.
    """

    if len(token) <= 4:
        return token

    sufijos = (
        "amientos",
        "imientos",
        "aciones",
        "mente",
        "ando",
        "iendo",
        "es",
        "os",
        "as",
        "s"
    )

    for sufijo in sufijos:
        if token.endswith(sufijo) and len(token) - len(sufijo) >= 3:
            return token[:-len(sufijo)]

    return token


def tokenizar(texto):
    """
    Convierte el texto en una lista de tokens normalizados.
    """

    palabras = re.findall(r"\b[\wáéíóúüñÁÉÍÓÚÜÑ]+\b", texto.lower())

    tokens = []

    for palabra in palabras:

        token = normalize(palabra)

        if not token:
            continue

        if token in STOPWORDS:
            continue

        token = stem(token)

        if token:
            tokens.append(token)

    return tokens


# ============================================================
# ÍNDICE INVERTIDO
# ============================================================

def construir_indice(corpus_dir):
    """
    Construye el índice invertido.

    Estructura:

        término -> {doc_id -> frecuencia}

    Ejemplo:

        {
            "java": {
                1: 3,
                5: 2,
                8: 1
            }
        }
    """

    indice = {}

    archivos = sorted(corpus_dir.glob("*.txt"))

    for doc_id, archivo in enumerate(archivos):

        try:
            texto = archivo.read_text(
                encoding="utf-8",
                errors="ignore"
            )
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
    Caché LRU para guardar resultados de consultas.

    Mantiene como máximo maxsize consultas.
    """

    def __init__(self, maxsize=1024):
        self.maxsize = maxsize
        self.cache = OrderedDict()

        self.hits = 0
        self.misses = 0

    def get(self, clave):

        if clave not in self.cache:
            self.misses += 1
            return None

        self.hits += 1

        # La consulta pasa a ser la más recientemente utilizada
        self.cache.move_to_end(clave)

        return self.cache[clave]

    def put(self, clave, valor):

        if clave in self.cache:
            self.cache.move_to_end(clave)

        self.cache[clave] = valor

        # Eliminamos la consulta menos utilizada
        if len(self.cache) > self.maxsize:
            self.cache.popitem(last=False)

    def info(self):
        return {
            "hits": self.hits,
            "misses": self.misses,
            "size": len(self.cache)
        }


# ============================================================
# CONSULTA DEL ÍNDICE
# ============================================================

def normalizar_consulta(consulta):
    """
    Convierte la consulta en una tupla canónica.

    Esto permite que:

        "Java Concurrencia"

    y

        "concurrencia java"

    tengan la misma representación.
    """

    tokens = tokenizar(consulta)

    return tuple(sorted(set(tokens)))


def buscar(indice, consulta):
    """
    Busca documentos que contengan TODOS los términos.

    Utiliza intersección de conjuntos.
    """

    terminos = normalizar_consulta(consulta)

    if not terminos:
        return set()

    postings = []

    for termino in terminos:

        if termino not in indice:
            return set()

        documentos = set(indice[termino].keys())

        postings.append((len(documentos), documentos))

    # Primero usamos los términos menos frecuentes.
    postings.sort(key=lambda x: x[0])

    candidatos = postings[0][1].copy()

    for _, documentos in postings[1:]:
        candidatos &= documentos

        if not candidatos:
            break

    return candidatos


# ============================================================
# RANKING TOP-K
# ============================================================

def rankear(indice, consulta, candidatos, k):
    """
    Calcula un score simple basado en la frecuencia
    de aparición de los términos.

    Luego utiliza heapq para obtener solamente
    los k mejores documentos.
    """

    terminos = normalizar_consulta(consulta)

    scores = {}

    for doc_id in candidatos:

        score = 0

        for termino in terminos:

            frecuencia = indice[termino].get(doc_id, 0)

            score += frecuencia

        scores[doc_id] = score

    if not scores:
        return []

    # heapq.nlargest evita ordenar completamente
    # todos los candidatos.
    mejores = heapq.nlargest(
        k,
        scores.keys(),
        key=lambda doc_id: scores[doc_id]
    )

    return [
        (doc_id, scores[doc_id])
        for doc_id in mejores
    ]


# ============================================================
# BUSCADOR COMPLETO
# ============================================================

class Buscador:

    def __init__(self, indice, archivos, cache_size=1024):

        self.indice = indice
        self.archivos = archivos

        self.cache = QueryCache(cache_size)

    def buscar(self, consulta, top_k=10):

        clave = (
            normalizar_consulta(consulta),
            top_k
        )

        # Primero consultamos la caché
        resultado_cache = self.cache.get(clave)

        if resultado_cache is not None:
            return resultado_cache

        # Si no estaba en caché, buscamos
        candidatos = buscar(
            self.indice,
            consulta
        )

        resultado = rankear(
            self.indice,
            consulta,
            candidatos,
            top_k
        )

        # Guardamos el resultado
        self.cache.put(
            clave,
            resultado
        )

        return resultado


# ============================================================
# MOSTRAR RESULTADOS
# ============================================================

def mostrar_resultados(resultados, archivos):

    print()
    print("Resultados:")
    print("-" * 60)

    if not resultados:
        print("No se encontraron documentos.")
        return

    for posicion, (doc_id, score) in enumerate(resultados, start=1):

        nombre = archivos[doc_id].name

        print(
            f"{posicion}. {nombre} "
            f"(score={score})"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="Buscador optimizado con índice invertido"
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
        "--cache-size",
        type=int,
        default=1024,
        help="Cantidad máxima de consultas almacenadas"
    )

    args = parser.parse_args()

    corpus_dir = Path(args.directorio)

    if not corpus_dir.exists():
        print(
            f"Error: no existe el directorio "
            f"{corpus_dir}"
        )
        return

    print("Construyendo índice invertido...")

    inicio_indice = time.perf_counter()

    indice, archivos = construir_indice(
        corpus_dir
    )

    tiempo_indice = (
        time.perf_counter() - inicio_indice
    ) * 1000

    print(
        f"Documentos indexados: {len(archivos)}"
    )

    print(
        f"Términos en el índice: {len(indice)}"
    )

    print(
        f"Tiempo de construcción del índice: "
        f"{tiempo_indice:.2f} ms"
    )

    if not args.query:
        return

    buscador = Buscador(
        indice,
        archivos,
        args.cache_size
    )

    inicio_busqueda = time.perf_counter()

    resultados = buscador.buscar(
        args.query,
        args.top_k
    )

    tiempo_busqueda = (
        time.perf_counter() - inicio_busqueda
    ) * 1000

    print()
    print(
        f"Tiempo de búsqueda: "
        f"{tiempo_busqueda:.4f} ms"
    )

    print(
        f"Documentos encontrados: "
        f"{len(resultados)}"
    )

    mostrar_resultados(
        resultados,
        archivos
    )

    print()
    print("Información de caché:")
    print(buscador.cache.info())


if __name__ == "__main__":
    main()