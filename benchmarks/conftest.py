"""
Fixtures de los benchmarks.

``scripts/control_rendimiento.py`` corre esta suite dos veces, contra el
``src/`` de la rama base y contra el actual: indica cuál con ``BENCHMARK_SRC`` y
con ``-o pythonpath``, y comparte el corpus con ``BENCHMARK_CORPUS``. Se puede
correr sola, con un corpus propio, para depurar un benchmark::

    pytest benchmarks --benchmark-only
"""

import os
import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import optimizado
from api import create_app
from baseline import generar_corpus_prueba
from indice_en_disco import construir_y_guardar


DOCUMENTOS = 2000
SEMILLA = 2026


@pytest.fixture(scope="session", autouse=True)
def codigo_medido():
    # Si los dos lados midieran el mismo código, el control nunca rechazaría.
    esperado = os.environ.get("BENCHMARK_SRC")

    if esperado:
        origen = Path(optimizado.__file__).resolve().parent
        assert origen == Path(esperado).resolve()


@pytest.fixture(scope="session")
def corpus_dir(tmp_path_factory):
    compartido = os.environ.get("BENCHMARK_CORPUS")

    if compartido:
        return Path(compartido)

    directorio = tmp_path_factory.mktemp("corpus")
    random.seed(SEMILLA)
    generar_corpus_prueba(DOCUMENTOS, str(directorio))

    return directorio


@pytest.fixture(scope="session")
def indice_y_archivos(corpus_dir):
    return optimizado.construir_indice(corpus_dir)


@pytest.fixture(scope="session")
def indice_guardado(corpus_dir, tmp_path_factory):
    directorio = tmp_path_factory.mktemp("indice")
    construir_y_guardar(corpus_dir, directorio)

    return directorio


@pytest.fixture(scope="session")
def cliente(corpus_dir, tmp_path_factory):
    app = create_app(corpus_dir, tmp_path_factory.mktemp("indice_api"))

    with TestClient(app) as cliente:
        yield cliente
