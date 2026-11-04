"""
Caracterización del arnés de medición (src/perfilado.py).

Fijan lo que un error de refactorización rompería sin que nada falle: qué
queda adentro de cada ventana cronometrada, en qué orden se miden las
versiones y qué texto sale de cada número. Se escribieron contra el código
anterior a la refactorización y no se tocaron para hacerla.

Las operaciones medidas se reemplazan por dobles que avanzan un reloj falso
con un costo primo distinto. Así el tiempo informado se descompone de una sola
manera: si una operación entra o sale de una ventana, el número cambia.
"""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import perfilado


DATOS = Path(__file__).resolve().parent / "datos"

COSTO_SECUENCIAL = 2
COSTO_INDICE_SECUENCIAL = 3
COSTO_INDICE_PARALELO = 5
COSTO_NORMALIZAR = 7
COSTO_INTERSECCION = 11
COSTO_RANKING_SORTED = 13
COSTO_BUSCADOR = 17
COSTO_CACHE_NUEVA = 19
COSTO_LISTAR_CORPUS = 23
COSTO_BUSCADOR_NUEVO = 29

CORPUS = "corpus-falso"
INDICE = {"algoritmo": {0: 1}}
ARCHIVOS = ["a.txt", "b.txt", "c.txt"]
CANDIDATOS = {0, 1, 2, 3}
RSS_MB = 41.5


class Banco:
    """Reloj falso y registro ordenado de todo lo que hace medir_version."""

    def __init__(self):
        self.ahora = 0
        self.eventos = []

    def reloj(self):
        self.eventos.append("reloj")
        return self.ahora

    def operacion(self, nombre, costo, devuelve=None):
        def doble(*_args, **_kwargs):
            self.eventos.append(nombre)
            self.ahora += costo
            return devuelve

        return doble


class CorpusFalso:
    """Directorio del corpus: listarlo también consume tiempo."""

    def __init__(self, banco):
        self.banco = banco

    def glob(self, patron):
        assert patron == "*.txt"
        self.banco.operacion("listar", COSTO_LISTAR_CORPUS)()
        return iter(ARCHIVOS)

    def __str__(self):
        return CORPUS


@pytest.fixture
def banco(monkeypatch):
    banco = Banco()

    class BuscadorFalso:
        def __init__(self, indice, archivos):
            assert indice is INDICE
            assert archivos is ARCHIVOS
            banco.operacion("Buscador()", COSTO_BUSCADOR_NUEVO)()
            self.cache = "original"

        def buscar(self, consulta, top_k):
            assert (consulta, top_k) == (perfilado.CONSULTA, perfilado.TOP_K)
            banco.operacion(f"buscar[{self.cache}]", COSTO_BUSCADOR)()
            return 4, ["resultado"]

    def cache_nueva(tamano):
        assert tamano == 1024
        banco.operacion("QueryCache()", COSTO_CACHE_NUEVA)()
        return "vacia"

    monkeypatch.setattr(perfilado, "time", SimpleNamespace(perf_counter=banco.reloj))
    monkeypatch.setattr(
        perfilado.baseline,
        "busqueda_secuencial",
        banco.operacion("secuencial", COSTO_SECUENCIAL, ["r1", "r2", "r3", "r4", "r5"]),
    )
    monkeypatch.setattr(
        perfilado.optimizado,
        "construir_indice",
        banco.operacion(
            "indice_secuencial", COSTO_INDICE_SECUENCIAL, (INDICE, ARCHIVOS)
        ),
    )
    monkeypatch.setattr(
        perfilado.concurrente,
        "construir_indice",
        banco.operacion("indice_paralelo", COSTO_INDICE_PARALELO, (INDICE, ARCHIVOS)),
    )
    monkeypatch.setattr(
        perfilado.optimizado,
        "normalizar_consulta",
        banco.operacion("normalizar", COSTO_NORMALIZAR, ("algoritmo",)),
    )
    monkeypatch.setattr(
        perfilado.optimizado,
        "buscar",
        banco.operacion("interseccion", COSTO_INTERSECCION, CANDIDATOS),
    )
    monkeypatch.setattr(
        perfilado,
        "_rankear_sorted",
        banco.operacion("sorted", COSTO_RANKING_SORTED, ["top"]),
    )
    monkeypatch.setattr(perfilado.optimizado, "Buscador", BuscadorFalso)
    monkeypatch.setattr(perfilado.optimizado, "QueryCache", cache_nueva)
    monkeypatch.setattr(perfilado, "_rss_mb", lambda: RSS_MB)

    return banco


def _metricas(version, repeticiones, consulta_ms, indexacion_ms, documentos, total):
    return {
        "version": version,
        "corpus": CORPUS,
        "documentos": documentos,
        "indexacion_ms": indexacion_ms,
        "consulta_ms": consulta_ms,
        "consulta_min_ms": consulta_ms,
        "consulta_max_ms": consulta_ms,
        "repeticiones": repeticiones,
        "tracemalloc_mb": None,
        "rss_mb": RSS_MB,
        "coincidencias": total,
    }


def _ventana(*operaciones):
    return ["reloj", *operaciones, "reloj"]


# ---- medir_version: qué entra en cada ventana cronometrada


def test_inicial_cronometra_solo_la_busqueda_secuencial(banco):
    medicion = perfilado.medir_version("inicial", CorpusFalso(banco), 2)

    assert banco.eventos == [
        *_ventana("secuencial"),
        *_ventana("secuencial"),
        "listar",
    ]
    assert medicion == _metricas(
        "inicial",
        2,
        consulta_ms=COSTO_SECUENCIAL * 1000,
        indexacion_ms=None,
        documentos=3,
        total=5,
    )


def test_estructura_cronometra_interseccion_y_ranking_con_sorted(banco):
    medicion = perfilado.medir_version("estructura", CorpusFalso(banco), 2)

    assert banco.eventos == [
        *_ventana("indice_secuencial"),
        "normalizar",
        *_ventana("interseccion", "sorted"),
        *_ventana("interseccion", "sorted"),
    ]
    assert medicion == _metricas(
        "estructura",
        2,
        consulta_ms=(COSTO_INTERSECCION + COSTO_RANKING_SORTED) * 1000,
        indexacion_ms=COSTO_INDICE_SECUENCIAL * 1000,
        documentos=3,
        # Todos los candidatos, no solo la página que devuelve el ranking.
        total=len(CANDIDATOS),
    )


@pytest.mark.parametrize(
    "version, indice, costo_indice",
    [
        ("algoritmo", "indice_secuencial", COSTO_INDICE_SECUENCIAL),
        ("concurrencia", "indice_paralelo", COSTO_INDICE_PARALELO),
    ],
)
def test_sin_cache_caliente_cada_consulta_arranca_con_cache_vacia(
    banco, version, indice, costo_indice
):
    medicion = perfilado.medir_version(version, CorpusFalso(banco), 2)

    assert banco.eventos == [
        *_ventana(indice),
        # Sin usar en estas versiones, pero calienta en este proceso el
        # lru_cache de normalize y stem. En `concurrencia` el índice se
        # construye en otros procesos: sin esta llamada, la primera consulta
        # cronometrada pagaría esos fallos.
        "normalizar",
        "Buscador()",
        "QueryCache()",
        *_ventana("buscar[vacia]"),
        "QueryCache()",
        *_ventana("buscar[vacia]"),
    ]
    assert medicion == _metricas(
        version,
        2,
        consulta_ms=COSTO_BUSCADOR * 1000,
        indexacion_ms=costo_indice * 1000,
        documentos=3,
        total=4,
    )


def test_final_calienta_la_cache_fuera_de_la_ventana(banco):
    medicion = perfilado.medir_version("final", CorpusFalso(banco), 2)

    assert banco.eventos == [
        *_ventana("indice_paralelo"),
        "normalizar",
        "Buscador()",
        "buscar[original]",
        *_ventana("buscar[original]"),
        *_ventana("buscar[original]"),
    ]
    assert medicion == _metricas(
        "final",
        2,
        consulta_ms=COSTO_BUSCADOR * 1000,
        indexacion_ms=COSTO_INDICE_PARALELO * 1000,
        documentos=3,
        total=4,
    )


def test_resume_la_consulta_con_mediana_minimo_y_maximo(banco, monkeypatch):
    costos = iter([2, 10, 3])

    def secuencial_variable(*_args):
        banco.ahora += next(costos)
        return ["r1"]

    monkeypatch.setattr(perfilado.baseline, "busqueda_secuencial", secuencial_variable)

    medicion = perfilado.medir_version("inicial", CorpusFalso(banco), 3)

    assert medicion["consulta_ms"] == 3000
    assert medicion["consulta_min_ms"] == 2000
    assert medicion["consulta_max_ms"] == 10000


def test_tracemalloc_envuelve_toda_la_medicion_y_se_lee_antes_de_apagarlo(
    banco, monkeypatch
):
    def pico():
        banco.eventos.append("tracemalloc_leer")
        return (0, 3 * 1024 * 1024)

    monkeypatch.setattr(
        perfilado,
        "tracemalloc",
        SimpleNamespace(
            start=banco.operacion("tracemalloc_start", 0),
            get_traced_memory=pico,
            stop=banco.operacion("tracemalloc_stop", 0),
        ),
    )

    medicion = perfilado.medir_version(
        "algoritmo", CorpusFalso(banco), 1, con_tracemalloc=True
    )

    assert banco.eventos == [
        "tracemalloc_start",
        *_ventana("indice_secuencial"),
        "normalizar",
        "Buscador()",
        "QueryCache()",
        *_ventana("buscar[vacia]"),
        "tracemalloc_leer",
        "tracemalloc_stop",
    ]
    assert medicion["tracemalloc_mb"] == 3


def test_sin_pedirlo_tracemalloc_no_se_activa(banco, monkeypatch):
    # Activo, encarece el código medido: inflaba los tiempos de la tabla.
    monkeypatch.setattr(perfilado, "tracemalloc", None)

    medicion = perfilado.medir_version("algoritmo", CorpusFalso(banco), 1)

    assert medicion["tracemalloc_mb"] is None


# ---- comparativa: orden de las mediciones y resumen


def _medicion_comparativa(llamada, version, repeticiones):
    """
    Valores distintos por versión y por llamada, para seguirlos en el resumen.

    Crecen con el cuadrado de la llamada para que la mediana y la media de
    varias rondas no coincidan.
    """
    return {
        "version": version,
        "documentos": 50 + llamada,
        "consulta_ms": 1000.0 + llamada**2,
        "indexacion_ms": None if version == "inicial" else 2000.0 + llamada**2,
        "rss_mb": 3000.0 + llamada**2,
        "tracemalloc_mb": 4000.0 + llamada**2,
        "coincidencias": 60 + llamada,
        "repeticiones": repeticiones,
    }


@pytest.fixture
def subproceso(monkeypatch):
    llamadas = []

    def falso(version, corpus_dir, repeticiones, con_tracemalloc=False):
        llamadas.append((version, corpus_dir, repeticiones, con_tracemalloc))
        return _medicion_comparativa(len(llamadas), version, repeticiones)

    monkeypatch.setattr(perfilado, "_medir_en_subproceso", falso)
    monkeypatch.setattr(perfilado, "_carga_del_sistema", lambda: 1.5)
    monkeypatch.setattr(perfilado.os, "cpu_count", lambda: 8)

    return llamadas


def test_comparativa_alterna_las_versiones_y_mide_la_memoria_aparte(subproceso):
    perfilado.comparativa("corpus", rondas=2, repeticiones=9, descartar=1)

    rondas = [
        (version, "corpus", 3 if version == "inicial" else 9, False)
        for _ronda in range(3)
        for version in perfilado.VERSIONES
    ]
    pasada_de_memoria = [
        (version, "corpus", 1, True) for version in perfilado.VERSIONES
    ]

    assert subproceso == rondas + pasada_de_memoria


def test_comparativa_devuelve_el_mismo_json(subproceso):
    resultado = perfilado.comparativa("corpus", rondas=3, repeticiones=9, descartar=1)

    # Texto y no diccionarios: el orden de las claves llega a perfilado.json.
    esperado = (DATOS / "comparativa_esperada.json").read_text(encoding="utf-8")
    assert json.dumps(resultado, ensure_ascii=False, indent=1) + "\n" == esperado


def test_comparativa_imprime_el_mismo_progreso(subproceso, capsys):
    perfilado.comparativa("corpus", rondas=1, repeticiones=9, descartar=1)

    esperado = (DATOS / "comparativa_progreso.txt").read_text(encoding="utf-8")
    assert capsys.readouterr().out == esperado


def test_comparativa_sin_descartar_mide_todas_las_rondas(subproceso):
    resultado = perfilado.comparativa("corpus", rondas=1, repeticiones=9, descartar=0)

    assert [m["descartada"] for m in resultado["crudo"]["inicial"]] == [False]
    assert resultado["resumen"]["inicial"]["rondas"] == 1


def test_comparativa_tolera_que_falte_el_rss(subproceso, monkeypatch):
    real = perfilado._medir_en_subproceso

    def sin_rss(*args, **kwargs):
        return {**real(*args, **kwargs), "rss_mb": None}

    monkeypatch.setattr(perfilado, "_medir_en_subproceso", sin_rss)

    resultado = perfilado.comparativa("corpus", rondas=2, repeticiones=9, descartar=0)

    assert resultado["resumen"]["final"]["rss_mb"] is None
    # Sin índice no hay indexación que resumir.
    assert resultado["resumen"]["inicial"]["indexacion_ms"] is None


def test_comparativa_resume_el_rss_con_las_muestras_que_existen(
    subproceso, monkeypatch
):
    real = perfilado._medir_en_subproceso

    def falta_en_la_primera_ronda(*args, **kwargs):
        medicion = real(*args, **kwargs)
        faltante = len(subproceso) <= len(perfilado.VERSIONES)
        return {**medicion, "rss_mb": None if faltante else medicion["rss_mb"]}

    monkeypatch.setattr(perfilado, "_medir_en_subproceso", falta_en_la_primera_ronda)

    resultado = perfilado.comparativa("corpus", rondas=3, repeticiones=9, descartar=0)

    # `final` es la quinta medición de cada ronda: llamadas 5, 10 y 15.
    assert resultado["resumen"]["final"]["rss_mb"] == 3000 + (10**2 + 15**2) / 2


@pytest.mark.parametrize(
    "carga, avisa",
    [(9.0, True), (8.0, False), (None, False)],
)
def test_comparativa_avisa_solo_si_la_maquina_esta_sobresuscripta(
    subproceso, monkeypatch, capsys, carga, avisa
):
    monkeypatch.setattr(perfilado, "_carga_del_sistema", lambda: carga)

    resultado = perfilado.comparativa("corpus", rondas=1, repeticiones=1, descartar=0)

    salida = capsys.readouterr().out
    assert ("ADVERTENCIA" in salida) is avisa
    assert resultado["resumen"]["final"]["carga_al_medir"] == carga


def test_comparativa_lee_la_carga_una_sola_vez_y_antes_de_medir(
    subproceso, monkeypatch
):
    lecturas = []

    def carga():
        lecturas.append(len(subproceso))
        return 1.0

    monkeypatch.setattr(perfilado, "_carga_del_sistema", carga)

    perfilado.comparativa("corpus", rondas=1, repeticiones=1, descartar=0)

    assert lecturas == [0]


# ---- responder_preguntas: el texto sale de los números medidos


def _resultados_de_preguntas():
    return json.loads(
        (DATOS / "preguntas_entrada.json").read_text(encoding="utf-8"),
    )


def _variantes_de_preguntas():
    completos = _resultados_de_preguntas()
    sin_tokenizar = {
        "algoritmo": {"top": [{"funcion": "otra", "cumtime": 1, "llamadas": 2}]}
    }

    return {
        "completos": completos,
        "sin_comparativa": {k: v for k, v in completos.items() if k != "comparativa"},
        "sin_escalabilidad": {
            k: v for k, v in completos.items() if k != "escalabilidad"
        },
        "sin_cprofile": {k: v for k, v in completos.items() if k != "cprofile"},
        "cprofile_sin_top": {**completos, "cprofile": {"algoritmo": {}}},
        "cprofile_sin_tokenizar": {**completos, "cprofile": sin_tokenizar},
    }


@pytest.mark.parametrize("variante", _variantes_de_preguntas())
def test_responder_preguntas_da_el_mismo_texto(variante):
    resultados = _variantes_de_preguntas()[variante]
    esperado = json.loads(
        (DATOS / "preguntas_esperadas.json").read_text(encoding="utf-8")
    )[variante]

    # Texto y no diccionarios: el orden de las preguntas llega al reporte.
    assert json.dumps(perfilado.responder_preguntas(resultados)) == json.dumps(esperado)


def test_responder_preguntas_no_inventa_si_falta_una_version():
    resultados = _resultados_de_preguntas()
    del resultados["comparativa"]["final"]

    with pytest.raises(KeyError):
        perfilado.responder_preguntas(resultados)


# ---- perfilar_scalene: cómo se lanza y qué se informa


@pytest.fixture
def entorno_scalene(monkeypatch, tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "scalene").touch()
    (tmp_path / "perfiles").mkdir()

    monkeypatch.setattr(
        perfilado,
        "sys",
        SimpleNamespace(executable=str(tmp_path / "bin" / "python"), platform="linux"),
    )
    monkeypatch.setattr(perfilado, "BASE_DIR", tmp_path)
    monkeypatch.setattr(perfilado, "SRC_DIR", tmp_path / "src")
    monkeypatch.setattr(perfilado, "DIR_PERFILES", tmp_path / "perfiles")
    monkeypatch.setattr(perfilado, "_resumir_scalene", lambda archivo: archivo.name)

    return tmp_path


def _proceso(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _simular_scalene(monkeypatch, comportamiento):
    """Reemplaza subprocess.run; `comportamiento` decide por versión."""
    llamadas = []

    def falso(orden, **opciones):
        llamadas.append((orden, opciones))
        return comportamiento(Path(orden[3]))

    monkeypatch.setattr(perfilado.subprocess, "run", falso)

    return llamadas


def test_scalene_se_lanza_con_los_argumentos_exactos(entorno_scalene, monkeypatch):
    def escribe_el_json(destino):
        destino.touch()
        return _proceso()

    llamadas = _simular_scalene(monkeypatch, escribe_el_json)

    perfilado.perfilar_scalene("corpus", ("algoritmo",), limite_s=7)

    orden, opciones = llamadas[0]
    assert orden == [
        str(entorno_scalene / "bin" / "scalene"),
        "run",
        "-o",
        str(entorno_scalene / "perfiles" / "scalene-algoritmo.json"),
        str(entorno_scalene / "src" / "perfilado.py"),
        "---",
        "--medir",
        "algoritmo",
        "--directorio",
        "corpus",
        "--repeticiones",
        "1",
    ]
    assert opciones == {
        "cwd": str(entorno_scalene),
        "capture_output": True,
        "text": True,
        "timeout": 7,
        "check": False,
    }


def test_scalene_informa_cada_resultado_y_sigue_con_la_version_siguiente(
    entorno_scalene, monkeypatch, capsys
):
    def comportamiento(destino):
        version = destino.stem.removeprefix("scalene-")

        if version == "inicial":
            destino.touch()
            return _proceso()
        if version == "estructura":
            return _proceso(returncode=3, stdout="salida", stderr="x" * 500)
        if version == "algoritmo":
            return _proceso(returncode=1, stdout="solo stdout")
        if version == "concurrencia":
            destino.touch()
            raise subprocess.TimeoutExpired("scalene", 7)
        return _proceso()

    _simular_scalene(monkeypatch, comportamiento)

    hallazgos = perfilado.perfilar_scalene(
        "corpus",
        ("inicial", "estructura", "algoritmo", "concurrencia", "final"),
        limite_s=7,
    )

    destino_inicial = Path("perfiles") / "scalene-inicial.json"
    scalene = entorno_scalene / "bin" / "scalene"
    assert hallazgos == {
        "inicial": {
            "archivo": str(destino_inicial),
            "ver_con": f"{scalene} view {destino_inicial}",
            "resumen": "scalene-inicial.json",
        },
        # Los últimos 400 caracteres de stderr: el final suele traer la causa.
        "estructura": {"error": "x" * 400},
        "algoritmo": {"error": "solo stdout"},
        "concurrencia": {
            "omitido": "Scalene excedió 7s sobre esta versión: su "
            "instrumentación no acompaña a los procesos hijos "
            "creados por spawn"
        },
        # Terminó bien pero no escribió el JSON: no hay nada que resumir.
        "final": {"error": ""},
    }
    assert not (entorno_scalene / "perfiles" / "scalene-concurrencia.json").exists()
    assert capsys.readouterr().out.splitlines() == [
        "  scalene: inicial",
        "  scalene: estructura",
        "  scalene: algoritmo",
        "  scalene: concurrencia",
        "  scalene: final",
    ]


def test_scalene_usa_el_del_venv_si_no_esta_junto_al_interprete(
    entorno_scalene, monkeypatch
):
    (entorno_scalene / "bin" / "scalene").unlink()
    (entorno_scalene / ".venv" / "bin").mkdir(parents=True)
    (entorno_scalene / ".venv" / "bin" / "scalene").touch()

    llamadas = _simular_scalene(monkeypatch, lambda _destino: _proceso())

    perfilado.perfilar_scalene("corpus", ("final",))

    assert llamadas[0][0][0] == str(entorno_scalene / ".venv" / "bin" / "scalene")
    assert llamadas[0][1]["timeout"] == 150


def test_scalene_en_windows_busca_el_ejecutable_en_scripts(
    entorno_scalene, monkeypatch
):
    monkeypatch.setattr(perfilado.sys, "platform", "win32")
    (entorno_scalene / ".venv" / "Scripts").mkdir(parents=True)
    (entorno_scalene / ".venv" / "Scripts" / "scalene.exe").touch()

    llamadas = _simular_scalene(monkeypatch, lambda _destino: _proceso())

    perfilado.perfilar_scalene("corpus", ("final",))

    assert llamadas[0][0][0] == str(
        entorno_scalene / ".venv" / "Scripts" / "scalene.exe"
    )


def test_sin_scalene_instalado_lo_informa_sin_lanzar_nada(entorno_scalene, monkeypatch):
    (entorno_scalene / "bin" / "scalene").unlink()

    llamadas = _simular_scalene(monkeypatch, lambda _destino: _proceso())

    hallazgos = perfilado.perfilar_scalene("corpus", ("final",))

    assert hallazgos == {
        "omitido": f"scalene no está instalado en {entorno_scalene / '.venv' / 'bin'}"
    }
    assert llamadas == []


# ---- perfilar_cprofile: el ranking muestra las funciones medidas


def test_el_ranking_de_cprofile_omite_las_funciones_del_arnes():
    def fila(acumulado):
        return (1, 1, 0.5, acumulado, {})

    estadisticas = SimpleNamespace(
        stats={
            ("/repo/src/perfilado.py", 9, "medir_version"): fila(100.0),
            ("/repo/src/perfilado.py", 8, "_medir_con_indice"): fila(99.0),
            **{
                ("/repo/src/motor.py", numero, f"funcion_{numero}"): fila(50.0 - numero)
                for numero in range(20)
            },
        }
    )

    ranking = perfilado._ranking_cprofile(estadisticas)

    assert len(ranking) == 12
    assert ranking[0] == {
        "funcion": "perfilado.py:9(medir_version)",
        "llamadas": 1,
        "tottime": 0.5,
        "cumtime": 100.0,
    }
    assert ranking[1]["funcion"] == "motor.py:0(funcion_0)"
    assert ranking[-1]["funcion"] == "motor.py:10(funcion_10)"
