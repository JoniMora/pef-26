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


def _contar_construcciones(monkeypatch):
    """Envuelve la construcción del índice para contar cuántas veces ocurre."""
    import indice_en_disco

    llamadas = []
    original = indice_en_disco.construir_y_guardar

    def contada(*args, **kwargs):
        llamadas.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(indice_en_disco, "construir_y_guardar", contada)
    return llamadas


def test_reutiliza_el_indice_entre_consultas(corpus_api, monkeypatch):
    construcciones = _contar_construcciones(monkeypatch)
    client = TestClient(create_app(corpus_api))

    client.get("/buscar", params={"q": "algoritmo"})
    client.get("/buscar", params={"q": "memoria"})

    assert len(construcciones) == 1


def test_reconstruye_si_se_agrega_un_archivo(corpus_api, monkeypatch):
    construcciones = _contar_construcciones(monkeypatch)
    client = TestClient(create_app(corpus_api))
    assert client.get("/buscar", params={"q": "algoritmo"}).json()["total"] == 1

    # Agregar un archivo cambia la fecha de modificación del directorio.
    (corpus_api / "doc_2.txt").write_text("algoritmo", encoding="utf-8")

    assert client.get("/buscar", params={"q": "algoritmo"}).json()["total"] == 2
    assert len(construcciones) == 2


def test_reindexar_toma_cambios_dentro_de_un_archivo(corpus_api):
    client = TestClient(create_app(corpus_api))
    assert client.get("/buscar", params={"q": "memoria"}).json()["total"] == 1

    # Reescribir un archivo existente no cambia el directorio: la consulta
    # sigue usando el índice anterior hasta que se pide reindexar.
    (corpus_api / "doc_0.txt").write_text("memoria", encoding="utf-8")
    assert client.get("/buscar", params={"q": "memoria"}).json()["total"] == 1

    respuesta = client.post("/reindexar")

    assert respuesta.status_code == 200
    assert respuesta.json()["documentos"] == 2
    assert client.get("/buscar", params={"q": "memoria"}).json()["total"] == 2


def test_corpus_inexistente_responde_503(tmp_path):
    client = TestClient(create_app(tmp_path / "no-existe"))

    assert client.get("/buscar", params={"q": "algoritmo"}).status_code == 503
    assert client.post("/reindexar").status_code == 503


def test_al_reiniciar_carga_el_indice_guardado(corpus_api, monkeypatch):
    TestClient(create_app(corpus_api)).get("/buscar", params={"q": "algoritmo"})

    # Una aplicación nueva simula reiniciar el servidor: no tiene el índice
    # en memoria, pero lo encuentra en disco y no lo reconstruye.
    construcciones = _contar_construcciones(monkeypatch)
    client = TestClient(create_app(corpus_api))

    assert client.get("/buscar", params={"q": "algoritmo"}).json()["total"] == 1
    assert construcciones == []


def test_el_directorio_del_indice_es_configurable(corpus_api, tmp_path_factory):
    destino = tmp_path_factory.mktemp("indice")
    client = TestClient(create_app(corpus_api, indice_dir=destino))

    client.get("/buscar", params={"q": "algoritmo"})

    assert (destino / "manifiesto.json").exists()


def test_swagger_documenta_parametros_y_respuestas(corpus_api):
    esquema = TestClient(create_app(corpus_api)).get("/openapi.json").json()
    modelos = esquema["components"]["schemas"]

    def modelo_de_respuesta(operacion):
        contenido = operacion["responses"]["200"]["content"]["application/json"]
        return contenido["schema"]["$ref"].rsplit("/", 1)[-1]

    buscar = esquema["paths"]["/buscar"]["get"]
    parametros = {parametro["name"]: parametro for parametro in buscar["parameters"]}
    assert modelo_de_respuesta(buscar) == "RespuestaBusqueda"
    assert set(modelos["RespuestaBusqueda"]["properties"]) == {
        "consulta",
        "total",
        "resultados",
    }
    assert parametros["q"]["description"]
    assert parametros["top_k"]["schema"]["maximum"] == 100
    assert "503" in buscar["responses"]

    reindexar = esquema["paths"]["/reindexar"]["post"]
    assert modelo_de_respuesta(reindexar) == "RespuestaReindexado"
    assert "503" in reindexar["responses"]
