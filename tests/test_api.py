"""Pruebas del endpoint HTTP del buscador."""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api import create_app  # noqa: E402


@pytest.fixture
def corpus_api(tmp_path):
    """Crea un corpus pequeño para las pruebas de la API."""
    (tmp_path / "doc_0.txt").write_text(
        "algoritmo datos algoritmo",
        encoding="utf-8",
    )
    (tmp_path / "doc_1.txt").write_text(
        "estructura memoria",
        encoding="utf-8",
    )
    return tmp_path


def test_buscar_devuelve_resultados(corpus_api):
    """El endpoint devuelve total, ranking y nombre de documento."""
    client = TestClient(create_app(corpus_api))

    respuesta = client.get("/buscar", params={"q": "algoritmo", "top_k": 1})

    assert respuesta.status_code == 200
    assert respuesta.json()["total"] == 1
    assert respuesta.json()["resultados"][0]["documento"] == "doc_0.txt"


def test_buscar_rechaza_consulta_vacia(corpus_api):
    """Una consulta compuesta solo por espacios no es válida."""
    client = TestClient(create_app(corpus_api))

    respuesta = client.get("/buscar", params={"q": "   "})

    assert respuesta.status_code == 422
