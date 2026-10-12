"""
Tests unitarios de las piezas del buscador optimizado: normalización,
caché de consultas, intersección de postings y ranking top-k.
"""

import pytest

from optimizado import (
    Buscador,
    QueryCache,
    buscar,
    construir_indice,
    normalizar_consulta,
    normalize,
    rankear,
    stem,
    tokenizar,
)


# ============================================================
# NORMALIZACIÓN
# ============================================================

def test_normalize_quita_mayusculas_y_signos():
    assert normalize("¡Algoritmo!") == "algoritmo"


@pytest.mark.parametrize(
    ("palabra", "esperado"),
    [
        ("datos", "dato"),            # plural sobre vocal
        ("redes", "red"),             # -es tras consonante final válida
        ("vectores", "vector"),
        ("variables", "variable"),    # no debe recortar a "variab"
        ("luces", "luz"),             # alternancia z/c
        ("corpus", "corpus"),         # invariables
        ("analisis", "analisis"),
        ("rapidamente", "rapida"),    # sufijo -mente
        ("tests", "tests"),           # -s tras consonante: se deja igual
        ("mes", "mes"),               # demasiado corta
    ],
)
def test_stem(palabra, esperado):
    assert stem(palabra) == esperado


def test_tokenizar_descarta_stopwords_y_tokens_vacios():
    assert tokenizar("El algoritmo y los datos ___") == ["algoritmo", "dato"]


def test_normalizar_consulta_es_canonica():
    assert normalizar_consulta("Java Concurrencia") == normalizar_consulta(
        "concurrencia java java"
    )


# ============================================================
# ÍNDICE
# ============================================================

def test_construir_indice_ignora_archivos_ilegibles(tmp_path):
    (tmp_path / "a.txt").write_text("algoritmo datos", encoding="utf-8")
    # Un directorio que matchea *.txt no se puede leer: OSError.
    (tmp_path / "b.txt").mkdir()

    indice, archivos = construir_indice(tmp_path)

    assert len(archivos) == 2
    assert indice == {"algoritmo": {0: 1}, "dato": {0: 1}}


# ============================================================
# CACHÉ DE CONSULTAS
# ============================================================

def test_query_cache_lru():
    cache = QueryCache(maxsize=2)

    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1      # "a" pasa a ser la más reciente

    cache.put("c", 3)               # desaloja "b", la menos usada
    assert cache.get("b") is None

    cache.put("a", 10)              # actualizar una clave existente
    assert cache.get("a") == 10

    assert cache.info() == {"hits": 2, "misses": 1, "size": 2}


# ============================================================
# CONSULTA Y RANKING
# ============================================================

INDICE = {
    "a": {0: 1, 1: 1},
    "b": {2: 1},
    "c": {0: 1, 2: 1, 3: 1},
}


@pytest.mark.parametrize(
    ("terminos", "esperado"),
    [
        ((), set()),
        (("inexistente",), set()),
        (("a", "c"), {0}),
        (("a", "b", "c"), set()),   # la intersección se vacía antes de terminar
    ],
)
def test_buscar(terminos, esperado):
    assert buscar(INDICE, terminos) == esperado


def test_rankear_sin_candidatos_o_k_nulo():
    assert rankear(INDICE, ("a",), set(), 10, 4) == []
    assert rankear(INDICE, ("a",), {0, 1}, 0, 4) == []


def test_rankear_varios_terminos_ordena_por_tfidf():
    indice = {"x": {0: 3, 1: 1, 2: 1}, "y": {0: 1, 1: 5}}

    ranking = rankear(indice, ("x", "y"), {0, 1}, 10, 4)

    assert [doc_id for doc_id, _ in ranking] == [1, 0]


def test_rankear_desempata_por_doc_id():
    indice = {"x": {0: 1, 1: 1, 2: 1}}

    ranking = rankear(indice, ("x",), {0, 1, 2}, 2, 4)

    assert [doc_id for doc_id, _ in ranking] == [0, 1]


def test_buscador_usa_la_cache(indice_y_archivos):
    indice, archivos = indice_y_archivos
    buscador = Buscador(indice, archivos)

    primero = buscador.buscar("algoritmo")
    segundo = buscador.buscar("ALGORITMO")

    assert primero == segundo
    assert buscador.cache.info()["hits"] == 1
