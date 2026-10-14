"""
Tests del índice guardado en disco (``indice_en_disco``): lo que se carga
tiene que ser exactamente lo que se construyó, y un índice que ya no
corresponde al corpus no se usa.
"""

import json

import pytest

import indice_en_disco
from concurrente import LOTES_POR_PROCESO
from indice_en_disco import cargar_indice, construir_y_guardar, obtener_indice
from optimizado import construir_indice as construir_indice_secuencial


@pytest.fixture
def corpus(tmp_path):
    directorio = tmp_path / "corpus"
    directorio.mkdir()
    for numero, texto in enumerate(
        ["algoritmo datos algoritmo", "estructura memoria", "datos redes python"]
    ):
        (directorio / f"doc_{numero}.txt").write_text(texto, encoding="utf-8")
    return directorio


@pytest.fixture
def destino(tmp_path):
    return tmp_path / "indice"


def _nombres(archivos):
    return [archivo.name for archivo in archivos]


def test_guardar_y_cargar_da_el_mismo_indice(corpus, destino):
    indice, archivos = construir_y_guardar(corpus, destino)

    cargado, archivos_cargados = cargar_indice(corpus, destino)

    assert cargado == indice == construir_indice_secuencial(corpus)[0]
    assert _nombres(archivos_cargados) == _nombres(archivos)
    assert archivos_cargados[0].parent == corpus


def test_con_el_pool_escribe_un_archivo_por_lote(corpus_dir, tmp_path):
    # El corpus de la sesión supera UMBRAL_PARALELO: usa el pool.
    destino = tmp_path / "indice"
    construir_y_guardar(corpus_dir, destino, workers=2)

    lotes = sorted(destino.glob("lote_*.json"))
    assert len(lotes) == 2 * LOTES_POR_PROCESO
    assert cargar_indice(corpus_dir, destino) == construir_indice_secuencial(corpus_dir)


def test_sin_indice_guardado_devuelve_none(corpus, destino):
    assert cargar_indice(corpus, destino) is None


def test_corpus_modificado_invalida_el_indice(corpus, destino):
    construir_y_guardar(corpus, destino)

    (corpus / "doc_9.txt").write_text("algoritmo", encoding="utf-8")

    assert cargar_indice(corpus, destino) is None


def test_no_usa_el_indice_de_otro_corpus(corpus, destino, tmp_path):
    construir_y_guardar(corpus, destino)
    otro = tmp_path / "otro"
    otro.mkdir()
    (otro / "doc_0.txt").write_text("algoritmo", encoding="utf-8")

    assert cargar_indice(otro, destino) is None


def test_lote_danado_devuelve_none(corpus, destino):
    construir_y_guardar(corpus, destino)
    lote = next(destino.glob("lote_*.json"))
    lote.write_text("{no es json", encoding="utf-8")

    assert cargar_indice(corpus, destino) is None


def test_corpus_vacio(tmp_path, destino):
    vacio = tmp_path / "vacio"
    vacio.mkdir()

    assert construir_y_guardar(vacio, destino) == ({}, [])
    assert cargar_indice(vacio, destino) == ({}, [])


def test_el_manifiesto_describe_el_corpus(corpus, destino):
    construir_y_guardar(corpus, destino)

    manifiesto = json.loads((destino / "manifiesto.json").read_text())

    assert manifiesto["archivos"] == ["doc_0.txt", "doc_1.txt", "doc_2.txt"]
    assert manifiesto["firma"]["documentos"] == 3


def test_obtener_indice_construye_y_despues_carga(corpus, destino, monkeypatch):
    construcciones = []
    original = indice_en_disco.construir_y_guardar

    def contada(*args, **kwargs):
        construcciones.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(indice_en_disco, "construir_y_guardar", contada)

    *_, desde_disco_1 = obtener_indice(corpus, destino)
    indice, _, desde_disco_2 = obtener_indice(corpus, destino)
    *_, desde_disco_3 = obtener_indice(corpus, destino, forzar=True)

    assert (desde_disco_1, desde_disco_2, desde_disco_3) == (False, True, False)
    assert len(construcciones) == 2
    assert indice == construir_indice_secuencial(corpus)[0]


def test_un_manifiesto_alterado_no_lee_fuera_del_indice(corpus, destino, tmp_path):
    construir_y_guardar(corpus, destino)
    # Un archivo JSON válido fuera del directorio del índice.
    (tmp_path / "afuera.json").write_text('{"algoritmo": [[0], [1]]}')
    manifiesto = json.loads((destino / "manifiesto.json").read_text())
    manifiesto["lotes"] = ["../afuera.json"]
    (destino / "manifiesto.json").write_text(json.dumps(manifiesto))

    assert cargar_indice(corpus, destino) is None
