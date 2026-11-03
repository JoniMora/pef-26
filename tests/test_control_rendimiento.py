"""
Los controles de benchmark, profiling y memoria: qué rechazan, qué reportes dejan
y que de verdad midan el código que dicen medir.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tracemalloc
from pathlib import Path

import pytest

import perfilado


RAIZ = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "control_rendimiento", RAIZ / "scripts" / "control_rendimiento.py"
)
control = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(control)

TOLERANCIA = control.TOLERANCIA


@pytest.fixture
def reportes(monkeypatch, tmp_path):
    monkeypatch.setattr(control, "REPORTES", tmp_path)
    monkeypatch.setattr(control, "RAIZ", tmp_path)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "resumen.md"))

    return tmp_path


@pytest.fixture
def corpus_chico(monkeypatch, tmp_path):
    monkeypatch.setattr(control, "DOCUMENTOS", 5)
    directorio = tmp_path / "corpus"
    control.generar_corpus(directorio)

    return directorio


# ---- comparar


@pytest.mark.parametrize(
    "razon, regresion",
    [
        (0.5, False),
        (1.0, False),
        (1 + TOLERANCIA, False),
        (1 + TOLERANCIA + 0.01, True),
        (100.0, True),
    ],
)
def test_comparar_rechaza_solo_por_encima_de_la_tolerancia(razon, regresion):
    fila = control.comparar({"consulta": 1.0}, {"consulta": razon}, TOLERANCIA)[0]

    assert fila["regresion"] is regresion
    assert fila["razon"] == pytest.approx(razon)
    assert fila["base_ms"] == 1000
    assert fila["actual_ms"] == pytest.approx(razon * 1000)


def test_comparar_informa_cada_benchmark():
    filas = control.comparar({"a": 1.0, "b": 1.0}, {"b": 1.0, "a": 9.0}, TOLERANCIA)

    assert [(f["benchmark"], f["regresion"]) for f in filas] == [
        ("a", True),
        ("b", False),
    ]


# ---- medir_alternado


def test_mide_alternado_y_conserva_el_mejor_tiempo(monkeypatch, tmp_path):
    corridas = []
    tiempos = iter([5.0, 7.0, 6.0, 4.0, 9.0, 8.0])

    def falso(src, corpus, salida):
        assert corpus == "corpus"
        corridas.append((src, salida.name))
        return {"consulta": next(tiempos)}

    monkeypatch.setattr(control, "correr_benchmarks", falso)

    base, actual = control.medir_alternado("B", "A", "corpus", tmp_path, rondas=3)

    # Alternar el orden reparte entre los dos lados la deriva de la máquina.
    assert corridas == [
        ("B", "base-1.json"),
        ("A", "actual-1.json"),
        ("A", "actual-2.json"),
        ("B", "base-2.json"),
        ("B", "base-3.json"),
        ("A", "actual-3.json"),
    ]
    assert base == {"consulta": 4.0}
    assert actual == {"consulta": 6.0}


# ---- correr_benchmarks


def _suite_real(src, corpus):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "benchmarks",
            "-k",
            "tokenizar",
            "--benchmark-disable",
            "-o",
            f"pythonpath={src}",
            "-p",
            "no:cacheprovider",
        ],
        cwd=RAIZ,
        env={**os.environ, "BENCHMARK_SRC": str(src), "BENCHMARK_CORPUS": str(corpus)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_la_suite_mide_el_codigo_extraido_y_no_el_del_repositorio(
    tmp_path, corpus_chico
):
    src = control.extraer_src("HEAD", tmp_path)

    assert (src / "optimizado.py").is_file()

    # La suite verifica de dónde importó el motor: si `-o pythonpath` no pisara
    # al de pyproject.toml, los dos lados medirían lo mismo y nunca rechazaría.
    proceso = _suite_real(src, corpus_chico)

    assert proceso.returncode == 0, proceso.stdout


def test_la_suite_falla_si_mide_otro_codigo(tmp_path, corpus_chico):
    proceso = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "benchmarks",
            "-k",
            "tokenizar",
            "--benchmark-disable",
            "-p",
            "no:cacheprovider",
        ],
        cwd=RAIZ,
        env={
            **os.environ,
            "BENCHMARK_SRC": str(tmp_path),
            "BENCHMARK_CORPUS": str(corpus_chico),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert proceso.returncode != 0
    assert "codigo_medido" in proceso.stdout


def test_extraer_src_falla_si_no_existe_la_referencia(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        control.extraer_src("no-existe-esta-rama", tmp_path)


def test_si_falla_la_suite_el_control_rechaza(monkeypatch, tmp_path):
    def falso(_orden, **_opciones):
        return subprocess.CompletedProcess(
            [], 1, stdout="Error de importación", stderr=""
        )

    monkeypatch.setattr(control.subprocess, "run", falso)

    with pytest.raises(SystemExit, match="Error de importación"):
        control.correr_benchmarks(tmp_path, tmp_path, tmp_path / "salida.json")


def test_correr_benchmarks_devuelve_el_minimo_de_cada_uno(monkeypatch, tmp_path):
    salida = tmp_path / "salida.json"

    def falso(_orden, **_opciones):
        salida.write_text(
            json.dumps(
                {"benchmarks": [{"name": "consulta", "stats": {"min": 0.5, "mean": 9}}]}
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(control.subprocess, "run", falso)

    assert control.correr_benchmarks(tmp_path, tmp_path, salida) == {"consulta": 0.5}


# ---- control_benchmark


def _simular_medicion(monkeypatch, base, actual):
    monkeypatch.setattr(control, "extraer_src", lambda _ref, destino: destino)
    monkeypatch.setattr(control, "generar_corpus", lambda _directorio: None)
    monkeypatch.setattr(
        control, "medir_alternado", lambda *_args, **_kwargs: (base, actual)
    )


def test_benchmark_aprobado_deja_sus_reportes(monkeypatch, reportes, capsys):
    _simular_medicion(monkeypatch, {"consulta": 1.0}, {"consulta": 1.0})

    control.control_benchmark("HEAD^1")

    reporte = json.loads((reportes / "benchmark.json").read_text(encoding="utf-8"))
    assert reporte["base"] == "HEAD^1"
    assert reporte["tolerancia"] == TOLERANCIA
    assert reporte["benchmarks"][0]["regresion"] is False
    assert "Aprobado" in capsys.readouterr().out
    assert "Aprobado" in (reportes / "resumen.md").read_text(encoding="utf-8")


def test_benchmark_con_una_regresion_rechaza_y_deja_el_reporte(monkeypatch, reportes):
    _simular_medicion(
        monkeypatch,
        {"consulta": 1.0, "indice": 1.0},
        {"consulta": 1.0, "indice": 2.0},
    )

    with pytest.raises(SystemExit, match="regresión"):
        control.control_benchmark("HEAD^1")

    assert "Rechazado" in (reportes / "resumen.md").read_text(encoding="utf-8")
    assert (reportes / "benchmark.json").is_file()


# ---- corpus


def test_el_corpus_siempre_tiene_los_mismos_documentos(monkeypatch, tmp_path):
    monkeypatch.setattr(control, "DOCUMENTOS", 3)

    control.generar_corpus(tmp_path / "uno")
    control.generar_corpus(tmp_path / "dos")

    uno = {a.name: a.read_bytes() for a in (tmp_path / "uno").iterdir()}
    dos = {a.name: a.read_bytes() for a in (tmp_path / "dos").iterdir()}

    assert len(uno) == 3
    assert uno == dos


# ---- memoria


def _picos(**por_version):
    return {
        version: {"tracemalloc_mb": pico, "rss_mb": 30.0}
        for version, pico in por_version.items()
    }


def test_hay_un_limite_de_memoria_por_version():
    assert set(control.LIMITES_MB) == set(perfilado.VERSIONES)


@pytest.mark.parametrize(
    "pico, excedidas", [(9.0, []), (10.0, []), (10.001, ["final"])]
)
def test_memoria_rechaza_solo_por_encima_del_limite(pico, excedidas):
    assert control.versiones_excedidas(_picos(final=pico), {"final": 10.0}) == excedidas


def test_memoria_dentro_del_limite_deja_su_reporte(monkeypatch, reportes):
    monkeypatch.setattr(control, "generar_corpus", lambda _directorio: None)
    rutas = []

    def medir(corpus):
        rutas.append(corpus)
        return _picos(final=1.0)

    monkeypatch.setattr(control, "medir_picos", medir)
    monkeypatch.setattr(
        control, "asignaciones_relevantes", lambda _c: [{"linea": "x.py:1"}]
    )
    monkeypatch.setattr(control, "LIMITES_MB", {"final": 2.0})

    control.control_memoria()

    reporte = json.loads((reportes / "memoria.json").read_text(encoding="utf-8"))
    assert reporte["picos"]["final"]["tracemalloc_mb"] == 1.0
    assert reporte["limites_mb"] == {"final": 2.0}
    assert reporte["asignaciones"] == [{"linea": "x.py:1"}]
    # Con una ruta absoluta, el pico dependería de dónde esté el repositorio.
    assert not rutas[0].is_absolute()


def test_memoria_sobre_el_limite_rechaza_y_deja_el_reporte(monkeypatch, reportes):
    excedido = {version: 1e9 for version in perfilado.VERSIONES}

    monkeypatch.setattr(control, "generar_corpus", lambda _directorio: None)
    monkeypatch.setattr(control, "medir_picos", lambda _c: _picos(**excedido))
    monkeypatch.setattr(control, "asignaciones_relevantes", lambda _c: [])

    with pytest.raises(SystemExit, match="límite de memoria"):
        control.control_memoria()

    assert (reportes / "memoria.json").is_file()


def test_medir_picos_usa_un_proceso_limpio_con_tracemalloc(monkeypatch):
    llamadas = []

    def falso(version, corpus, repeticiones, con_tracemalloc=False):
        llamadas.append((version, corpus, repeticiones, con_tracemalloc))
        return {"tracemalloc_mb": 1.5, "rss_mb": 30.0, "consulta_ms": 9}

    monkeypatch.setattr(control.perfilado, "_medir_en_subproceso", falso)

    picos = control.medir_picos("corpus")

    assert llamadas == [(v, "corpus", 1, True) for v in perfilado.VERSIONES]
    assert picos["final"] == {"tracemalloc_mb": 1.5, "rss_mb": 30.0}


def test_las_asignaciones_salen_del_indice_y_dejan_tracemalloc_apagado(corpus_chico):
    asignaciones = control.asignaciones_relevantes(corpus_chico)

    assert asignaciones
    assert {"linea", "mb", "bloques"} == set(asignaciones[0])
    assert any(fila["linea"].startswith("optimizado.py:") for fila in asignaciones)
    assert not tracemalloc.is_tracing()


# ---- profiling


def _simular_perfiles(monkeypatch, top):
    monkeypatch.setattr(control, "generar_corpus", lambda _directorio: None)
    monkeypatch.setattr(
        control.perfilado,
        "perfilar_cprofile",
        lambda _c, versiones: {
            version: {
                "archivo": "x.prof",
                "total_s": 1.0,
                "top": top,
            }
            for version in versiones
        },
    )
    monkeypatch.setattr(
        control.perfilado,
        "perfilar_line",
        lambda _c, _v: {
            "algoritmo": {"archivo": "x.txt", "texto": "muy largo"},
            "final": {"omitido": "no cruza el límite de proceso"},
        },
    )


FILA = {"funcion": "a.py:1(f)", "llamadas": 1, "tottime": 0.5, "cumtime": 1.0}


def test_profiling_deja_el_ranking_y_escribe_donde_corresponde(monkeypatch, reportes):
    monkeypatch.setattr(control.perfilado, "DIR_PERFILES", perfilado.DIR_PERFILES)
    _simular_perfiles(monkeypatch, [FILA])

    control.control_profiling()

    assert control.perfilado.DIR_PERFILES == reportes / "profiling"
    reporte = json.loads(
        (reportes / "profiling" / "ranking.json").read_text(encoding="utf-8")
    )
    assert reporte["cprofile"]["algoritmo"]["top"] == [FILA]
    assert reporte["line_profiler"] == {
        "algoritmo": {"archivo": "x.txt"},
        "final": {"omitido": "no cruza el límite de proceso"},
    }
    assert "a.py:1(f)" in (reportes / "resumen.md").read_text(encoding="utf-8")


def test_profiling_rechaza_un_perfil_vacio(monkeypatch, reportes):
    monkeypatch.setattr(control.perfilado, "DIR_PERFILES", perfilado.DIR_PERFILES)
    _simular_perfiles(monkeypatch, [])

    with pytest.raises(SystemExit, match="vacío"):
        control.control_profiling()


def test_profiling_propaga_un_perfil_que_no_se_pudo_generar(monkeypatch, reportes):
    monkeypatch.setattr(control.perfilado, "DIR_PERFILES", perfilado.DIR_PERFILES)
    monkeypatch.setattr(control, "generar_corpus", lambda _directorio: None)

    def falla(_c, _v):
        raise subprocess.CalledProcessError(1, "perfilado.py")

    monkeypatch.setattr(control.perfilado, "perfilar_cprofile", falla)

    with pytest.raises(subprocess.CalledProcessError):
        control.control_profiling()


# ---- línea de comandos


def test_el_benchmark_exige_una_referencia(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["control_rendimiento.py", "benchmark"])

    with pytest.raises(SystemExit):
        control.main()

    assert "--base" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argumentos, funcion, esperado",
    [
        (["benchmark", "--base", "HEAD^1"], "control_benchmark", ("HEAD^1",)),
        (["profiling"], "control_profiling", ()),
        (["memoria"], "control_memoria", ()),
    ],
)
def test_cada_comando_corre_su_control(monkeypatch, argumentos, funcion, esperado):
    llamadas = []
    monkeypatch.setattr(sys, "argv", ["control_rendimiento.py", *argumentos])
    monkeypatch.setattr(control, funcion, lambda *args: llamadas.append(args))

    control.main()

    assert llamadas == [esperado]
