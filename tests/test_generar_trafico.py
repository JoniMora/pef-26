"""
Tests del generador de carga (``generar_trafico``). Corre contra la API en
el mismo proceso, con el transporte ASGI de httpx2: no abre puertos.
"""

import asyncio
import json
import sys

import httpx2
import pytest

import generar_trafico
from api import create_app
from generar_trafico import ejecutar_carga, percentiles, resumir


@pytest.fixture
def app(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for numero, texto in enumerate(
        ["algoritmo datos python", "memoria red codigo", "algoritmo memoria"]
    ):
        (corpus / f"doc_{numero}.txt").write_text(texto, encoding="utf-8")
    return create_app(corpus, tmp_path / "indice")


def _correr(app, **opciones):
    async def correr():
        transporte = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(
            transport=transporte, base_url="http://prueba"
        ) as cliente:
            return await ejecutar_carga(cliente, **opciones)

    return asyncio.run(correr())


def test_percentiles():
    valores = [float(numero) for numero in range(1, 101)]

    resultado = percentiles(valores)

    assert resultado["p50"] == pytest.approx(50.5)
    assert resultado["p95"] == pytest.approx(95.05)
    assert resultado["max"] == 100.0
    assert percentiles([]) == {}


def test_hace_la_cantidad_pedida_y_todas_responden_200(app):
    mediciones = _correr(app, solicitudes=60, concurrencia=5, semilla=1)

    assert len(mediciones) == 60
    assert {medicion["estado"] for medicion in mediciones} == {200}
    assert {medicion["tipo"] for medicion in mediciones} <= {
        "repetida",
        "variada",
        "inexistente",
    }


def test_la_mezcla_y_la_semilla_son_reproducibles(app):
    primera = _correr(app, solicitudes=40, concurrencia=4, semilla=7)
    segunda = _correr(app, solicitudes=40, concurrencia=4, semilla=7)

    def contar(mediciones):
        return sorted(medicion["tipo"] for medicion in mediciones)

    assert contar(primera) == contar(segunda)


def test_solo_consultas_inexistentes(app):
    mediciones = _correr(app, solicitudes=10, concurrencia=2, mezcla=(0, 0, 1))

    assert {medicion["tipo"] for medicion in mediciones} == {"inexistente"}
    assert {medicion["total"] for medicion in mediciones} == {0}


def test_reindexa_periodicamente(app):
    mediciones = _correr(
        app, duracion=0.6, concurrencia=2, reindexar_cada=0.2, semilla=3
    )

    recargas = [medicion for medicion in mediciones if medicion["tipo"] == "reindexar"]
    assert 1 <= len(recargas) <= 4
    assert {medicion["estado"] for medicion in recargas} == {200}


def test_resumir_agrupa_por_tipo_y_cuenta_errores():
    mediciones = [
        {"tipo": "repetida", "estado": 200, "ms": 1.0, "total": 2},
        {"tipo": "repetida", "estado": 200, "ms": 3.0, "total": 2},
        {"tipo": "variada", "estado": 500, "ms": 9.0, "total": None},
    ]

    resumen = resumir(mediciones, segundos=2.0)

    assert resumen["total"]["solicitudes"] == 3
    assert resumen["total"]["errores"] == 1
    assert resumen["total"]["por_segundo"] == pytest.approx(1.5)
    assert resumen["por_tipo"]["repetida"]["solicitudes"] == 2
    assert resumen["por_tipo"]["variada"]["errores"] == 1


def test_main_guarda_el_resumen(monkeypatch, tmp_path, capsys):
    async def carga_falsa(cliente, **opciones):
        return [{"tipo": "repetida", "estado": 200, "ms": 2.0, "total": 1}]

    monkeypatch.setattr(generar_trafico, "ejecutar_carga", carga_falsa)
    destino = tmp_path / "trafico.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["generar_trafico.py", "--solicitudes", "1", "--salida", str(destino)],
    )

    generar_trafico.main()

    resumen = json.loads(destino.read_text())
    assert resumen["total"]["solicitudes"] == 1
    assert resumen["opciones"]["solicitudes"] == 1
    assert "repetida" in capsys.readouterr().out


def test_un_servidor_caido_cuenta_como_error():
    def caido(peticion):
        raise httpx2.ConnectError("sin conexión", request=peticion)

    async def correr():
        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(caido), base_url="http://prueba"
        ) as cliente:
            return await ejecutar_carga(cliente, solicitudes=5, concurrencia=2)

    mediciones = asyncio.run(correr())

    assert len(mediciones) == 5
    assert {medicion["estado"] for medicion in mediciones} == {None}
    assert resumir(mediciones, segundos=1.0)["total"]["errores"] == 5


def test_sin_cantidad_ni_duracion_es_un_error():
    with pytest.raises(ValueError, match="solicitudes o duracion"):
        asyncio.run(ejecutar_carga(cliente=None))
