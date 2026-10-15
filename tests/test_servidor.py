"""
Tests del lanzador de la API (``servidor``): la API arranca con o sin
New Relic según haya licencia, sin conectarse nunca a New Relic.
"""

import sys
import types

import pytest

import servidor


@pytest.fixture
def agente_falso(monkeypatch):
    """Reemplaza el agente de New Relic por uno que registra las llamadas."""
    llamadas = []
    agente = types.ModuleType("newrelic.agent")
    agente.initialize = lambda archivo=None: llamadas.append(archivo)
    paquete = types.ModuleType("newrelic")
    paquete.agent = agente
    monkeypatch.setitem(sys.modules, "newrelic", paquete)
    monkeypatch.setitem(sys.modules, "newrelic.agent", agente)
    return llamadas


def test_sin_licencia_no_inicia_el_agente(agente_falso):
    entorno = {}

    assert servidor.iniciar_monitoreo(entorno) is False
    assert agente_falso == []


def test_con_licencia_inicia_el_agente_con_el_nombre_por_defecto(agente_falso):
    entorno = {"NEW_RELIC_LICENSE_KEY": "x" * 40}

    assert servidor.iniciar_monitoreo(entorno) is True
    assert agente_falso == [None]
    assert entorno["NEW_RELIC_APP_NAME"] == "pef-26"


def test_respeta_el_nombre_y_el_archivo_de_configuracion(agente_falso):
    entorno = {
        "NEW_RELIC_LICENSE_KEY": "x" * 40,
        "NEW_RELIC_APP_NAME": "otra-app",
        "NEW_RELIC_CONFIG_FILE": "newrelic.ini",
    }

    servidor.iniciar_monitoreo(entorno)

    assert agente_falso == ["newrelic.ini"]
    assert entorno["NEW_RELIC_APP_NAME"] == "otra-app"


def test_con_licencia_pero_sin_el_agente_instalado_avisa(monkeypatch):
    # Un None en sys.modules hace que el import falle con ImportError.
    monkeypatch.setitem(sys.modules, "newrelic", None)

    with pytest.raises(SystemExit, match="requirements-apm.txt"):
        servidor.iniciar_monitoreo({"NEW_RELIC_LICENSE_KEY": "x" * 40})


def test_cargar_variables_lee_el_archivo_sin_pisar_el_entorno(tmp_path):
    archivo = tmp_path / ".env"
    archivo.write_text(
        "# comentario\n"
        "\n"
        "NEW_RELIC_LICENSE_KEY='desde-el-archivo'\n"
        'NEW_RELIC_APP_NAME="app-del-archivo"\n'
        "BUSCADOR_CORPUS=/ruta/al/corpus\n",
        encoding="utf-8",
    )
    entorno = {"BUSCADOR_CORPUS": "/ruta/ya/definida"}

    cargadas = servidor.cargar_variables(archivo, entorno)

    assert entorno == {
        "BUSCADOR_CORPUS": "/ruta/ya/definida",
        "NEW_RELIC_LICENSE_KEY": "desde-el-archivo",
        "NEW_RELIC_APP_NAME": "app-del-archivo",
    }
    assert cargadas == ["NEW_RELIC_LICENSE_KEY", "NEW_RELIC_APP_NAME"]


def test_main_levanta_uvicorn_con_la_api(monkeypatch, agente_falso, capsys):
    corridas = []
    monkeypatch.setattr(
        servidor.uvicorn,
        "run",
        lambda app, **opciones: corridas.append((app, opciones)),
    )
    # main() lee y escribe os.environ: cada test usa un entorno propio para
    # no dejar variables definidas en el resto de la sesión.
    monkeypatch.setattr(servidor.os, "environ", {})
    monkeypatch.setattr(sys, "argv", ["servidor.py", "--port", "8123"])

    servidor.main()

    app, opciones = corridas[0]
    assert app == "api:app"
    assert opciones["port"] == 8123
    assert opciones["app_dir"] == str(servidor.SRC_DIR)
    assert "New Relic: desactivado" in capsys.readouterr().out
    assert agente_falso == []


def test_main_con_licencia_en_el_archivo_activa_new_relic(
    monkeypatch, agente_falso, capsys, tmp_path
):
    monkeypatch.setattr(servidor.uvicorn, "run", lambda app, **opciones: None)
    entorno = {}
    monkeypatch.setattr(servidor.os, "environ", entorno)
    archivo = tmp_path / ".env"
    archivo.write_text("NEW_RELIC_LICENSE_KEY=" + "x" * 40 + "\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["servidor.py", "--env-file", str(archivo)])

    servidor.main()

    salida = capsys.readouterr().out
    assert "New Relic: activo (app pef-26)" in salida
    assert "x" * 40 not in salida  # la licencia nunca se imprime
    assert agente_falso == [None]
    assert entorno["NEW_RELIC_APP_NAME"] == "pef-26"
