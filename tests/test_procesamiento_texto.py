"""
Tests unitarios del procesamiento de texto (``core.procesamiento_texto``):
normalización, stemming y tokenización, aislados del índice y la búsqueda.
"""

import pytest

from core.procesamiento_texto import normalize, stem, tokenizar


# ============================================================
# NORMALIZACIÓN
# ============================================================


def test_normalize_quita_mayusculas_y_signos():
    assert normalize("¡Algoritmo!") == "algoritmo"


# ============================================================
# STEMMING
# ============================================================

# Los 16 pares sobre los que el README documenta la validación del
# stemmer: cada plural tiene que reducirse a su singular.
PARES_SINGULAR_PLURAL = [
    ("dato", "datos"),
    ("indice", "indices"),
    ("lista", "listas"),
    ("clase", "clases"),
    ("red", "redes"),
    ("vector", "vectores"),
    ("variable", "variables"),
    ("funcion", "funciones"),
    ("metodo", "metodos"),
    ("papel", "papeles"),
    ("arbol", "arboles"),
    ("usuario", "usuarios"),
    ("servidor", "servidores"),
    ("documento", "documentos"),
    ("luz", "luces"),
    ("vez", "veces"),
]


@pytest.mark.parametrize(("singular", "plural"), PARES_SINGULAR_PLURAL)
def test_stem_unifica_singular_y_plural(singular, plural):
    assert stem(plural) == stem(singular) == singular


@pytest.mark.parametrize(
    ("palabra", "esperado"),
    [
        ("datos", "dato"),  # plural sobre vocal
        ("redes", "red"),  # -es tras consonante final válida
        ("vectores", "vector"),
        ("variables", "variable"),  # no debe recortar a "variab"
        ("luces", "luz"),  # alternancia z/c
        ("corpus", "corpus"),  # invariables
        ("analisis", "analisis"),
        ("rapidamente", "rapida"),  # sufijo -mente
        ("tests", "tests"),  # -s tras consonante: se deja igual
        ("mes", "mes"),  # demasiado corta
    ],
)
def test_stem(palabra, esperado):
    assert stem(palabra) == esperado


# ============================================================
# TOKENIZACIÓN
# ============================================================


def test_tokenizar_descarta_stopwords_y_tokens_vacios():
    assert tokenizar("El algoritmo y los datos ___") == ["algoritmo", "dato"]
