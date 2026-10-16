"""
Tests de la simulación en proceso de la API (``perfilar_api``).
"""

import pstats
import sys

import pytest

import perfilar_api
from api import ServicioDeBusqueda
from perfilar_api import simular_carga


@pytest.fixture
def corpus(tmp_path):
    directorio = tmp_path / "corpus"
    directorio.mkdir()
    for numero, texto in enumerate(
        ["algoritmo datos python", "memoria red codigo", "algoritmo memoria"]
    ):
        (directorio / f"doc_{numero}.txt").write_text(texto, encoding="utf-8")
    return directorio


def test_resuelve_la_cantidad_pedida_con_la_mezcla(corpus, tmp_path):
    servicio = ServicioDeBusqueda(corpus, tmp_path / "indice")

    por_tipo = simular_carga(servicio, 50, semilla=1)

    assert sum(por_tipo.values()) == 50
    assert set(por_tipo) == {"repetida", "variada", "inexistente"}


def test_la_semilla_repite_la_secuencia(corpus, tmp_path):
    servicio = ServicioDeBusqueda(corpus, tmp_path / "indice")

    primera = simular_carga(servicio, 40, semilla=7)
    segunda = simular_carga(servicio, 40, semilla=7)

    assert primera == segunda


def test_reindexar_reconstruye_el_indice(corpus, tmp_path):
    servicio = ServicioDeBusqueda(corpus, tmp_path / "indice")
    simular_carga(servicio, 5, semilla=1)
    anterior = servicio.obtener_buscador()

    simular_carga(servicio, 0, reindexar=True)

    assert servicio.obtener_buscador() is not anterior


def test_main_guarda_el_perfil_de_cprofile(corpus, tmp_path, monkeypatch, capsys):
    destino = tmp_path / "perfiles" / "api.prof"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "perfilar_api.py",
            "--corpus",
            str(corpus),
            "--indice",
            str(tmp_path / "indice"),
            "--consultas",
            "20",
            "--cprofile",
            str(destino),
        ],
    )

    perfilar_api.main()

    funciones = {funcion for _, _, funcion in pstats.Stats(str(destino)).stats}
    assert "simular_carga" in funciones
    assert "20 búsquedas" in capsys.readouterr().out
