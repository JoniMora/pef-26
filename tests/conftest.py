"""
Fixtures compartidas por la suite.

El corpus real (data/corpus) no se versiona, así que en CI no existe:
cada sesión de tests genera uno sintético y determinista en un
directorio temporal con el mismo generador que usa la línea base.
"""

import os
import random

import pytest

from baseline import generar_corpus_prueba
from optimizado import construir_indice


# Configurable para probar con más volumen en local:
#     CORPUS_DOCS=20000 pytest -m rendimiento
CORPUS_DOCS = int(os.environ.get("CORPUS_DOCS", "2000"))
SEMILLA = 2026


@pytest.fixture(scope="session")
def corpus_dir(tmp_path_factory):
    directorio = tmp_path_factory.mktemp("corpus")

    random.seed(SEMILLA)
    generar_corpus_prueba(CORPUS_DOCS, str(directorio))

    return directorio


@pytest.fixture(scope="session")
def indice_y_archivos(corpus_dir):
    """
    El índice se construye una sola vez por sesión: es el costo único
    O(N) de la versión optimizada y no forma parte de la consulta.
    """

    return construir_indice(corpus_dir)
