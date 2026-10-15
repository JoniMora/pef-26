"""
La indexación concurrente (MapReduce) debe producir exactamente el
mismo índice que la secuencial, con los mismos doc_id.
"""

from concurrente import _lotes_equitativos, construir_indice, fusionar
from optimizado import construir_indice as construir_indice_secuencial


def test_lotes_equitativos_reparte_el_resto():
    lotes = _lotes_equitativos(list(range(10)), 3)

    assert [len(lote) for lote in lotes] == [4, 3, 3]
    assert [numero for lote in lotes for numero in lote] == list(range(10))


def test_lotes_equitativos_casos_borde():
    assert _lotes_equitativos([], 4) == []
    assert _lotes_equitativos([1, 2], 0) == []
    assert _lotes_equitativos([1, 2], 5) == [[1], [2]]


def test_fusionar_combina_parciales():
    indice = {}

    fusionar(indice, {"a": {0: 1}})
    fusionar(indice, {"a": {1: 2}, "b": {1: 1}})

    assert indice == {"a": {0: 1, 1: 2}, "b": {1: 1}}


def test_indice_paralelo_igual_al_secuencial(corpus_dir):
    # El corpus de la sesión supera UMBRAL_PARALELO: usa el pool.
    paralelo = construir_indice(corpus_dir, workers=2)
    secuencial = construir_indice_secuencial(corpus_dir)

    assert paralelo == secuencial


def test_con_un_proceso_indexa_en_el_padre(tmp_path):
    (tmp_path / "a.txt").write_text("algoritmo datos", encoding="utf-8")
    (tmp_path / "b.txt").mkdir()  # ilegible: se omite

    indice, archivos = construir_indice(tmp_path, workers=1)

    assert len(archivos) == 2
    assert indice == {"algoritmo": {0: 1}, "dato": {0: 1}}


def test_admite_archivos_vacios(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"")  # 0 bytes
    (tmp_path / "b.txt").write_text("algoritmo datos", encoding="utf-8")

    # Con menos de UMBRAL_PARALELO archivos indexa el padre con
    # _procesar_lote(), la misma función que corren los workers.
    indice, archivos = construir_indice(tmp_path, workers=2)

    assert len(archivos) == 2
    assert indice == {"algoritmo": {1: 1}, "dato": {1: 1}}


def test_corpus_vacio(tmp_path):
    assert construir_indice(tmp_path) == ({}, [])
