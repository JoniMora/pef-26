"""
Procesamiento de texto compartido por el índice y las consultas.

Convierte un texto en la lista de términos que se indexan: separa las
palabras, las normaliza, descarta las *stopwords* y lleva cada término a
singular. Lo usan :mod:`optimizado`, al construir el índice y al
resolver consultas, y :mod:`concurrente`, en los workers del MapReduce;
así el índice secuencial y el paralelo tokenizan exactamente igual.

La línea base (:mod:`baseline`) no lo usa a propósito: busca la
subcadena literal, y es la referencia contra la que se mide la mejora.

``normalize`` y ``stem`` se memoizan con ``lru_cache`` porque el corpus
repite las mismas palabras muchas veces.
"""

import re
from functools import lru_cache


VOCALES = frozenset("aeiouáéíóúü")
CONSONANTES_FINALES = frozenset("dlnrz")

STOPWORDS = {
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "unos",
    "unas",
    "de",
    "del",
    "al",
    "y",
    "o",
    "en",
    "por",
    "para",
    "con",
    "sin",
    "que",
    "es",
    "se",
    "su",
    "sus",
    "a",
}


# ============================================================
# NORMALIZACIÓN
# ============================================================


@lru_cache(maxsize=10000)
def normalize(token):
    """
    Normaliza un token: lo pasa a minúsculas y le quita los signos.

    Conserva letras (incluidas las acentuadas y la ñ) y dígitos.

    :param token: Palabra tal como aparece en el texto.
    :type token: str
    :return: El token normalizado; puede quedar vacío si solo tenía signos.
    :rtype: str
    """
    token = token.lower()
    token = re.sub(r"[^a-záéíóúüñ0-9]", "", token)

    return token


@lru_cache(maxsize=10000)
def stem(token):
    """
    Normaliza plurales del español a su forma singular.

    Regla general: el plural se forma con -s tras vocal y con -es
    tras consonante. Se invierte esa regla en lugar de recortar
    sufijos a ciegas, que era lo que separaba "datos" de "dato".
    También quita el sufijo -mente de los adverbios largos.

    :param token: Token ya normalizado con :func:`normalize`.
    :type token: str
    :return: El token en singular, o sin cambios si no es un plural reconocido.
    :rtype: str
    """
    if len(token) > 8 and token.endswith("mente"):
        token = token[:-5]

    if len(token) <= 3 or not token.endswith("s"):
        return token

    # Invariables: corpus, analisis, crisis, virus.
    if token.endswith(("is", "us")):
        return token

    # Alternancia z/c: luz -> luces, vez -> veces.
    if len(token) <= 5 and token.endswith("ces"):
        return token[:-3] + "z"

    # -es solo si el singular termina en consonante final válida
    # precedida de vocal: redes -> red, vectores -> vector.
    # El chequeo de la vocal evita romper "variables" -> "variab".
    if (
        len(token) >= 5
        and token.endswith("es")
        and token[-3] in CONSONANTES_FINALES
        and token[-4] in VOCALES
    ):
        return token[:-2]

    # Plural sobre vocal: datos -> dato, clases -> clase.
    if token[-2] in VOCALES:
        return token[:-1]

    return token


def tokenizar(texto):
    """
    Convierte un texto en la lista de tokens que se indexan.

    Separa las palabras, las normaliza (:func:`normalize`), descarta las
    stopwords y lleva cada token a singular (:func:`stem`).

    :param texto: Texto de un documento o de una consulta.
    :type texto: str
    :return: Tokens en el orden en que aparecen, con repeticiones.
    :rtype: list[str]
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
