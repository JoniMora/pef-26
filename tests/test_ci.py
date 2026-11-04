"""
Protege las reglas del pipeline que se pueden romper sin que ningún job
falle: un job nuevo que no bloquea porque nadie lo sumó a "Resultado final",
o un comando suelto en el YAML que deja de coincidir con el local.
"""

import json
import re
import tomllib
from pathlib import Path

import pytest
import yaml


RAIZ = Path(__file__).resolve().parents[1]
JOB_FINAL = "resultado-final"
# Corren después del veredicto: no pueden formar parte de lo que decide.
JOBS_POSTERIORES = {"publicar-docs"}

WORKFLOW = yaml.safe_load((RAIZ / ".github/workflows/ci.yml").read_text("utf-8"))
OBJETIVOS = re.findall(
    r"^([a-z][a-z-]*):", (RAIZ / "Makefile").read_text("utf-8"), flags=re.MULTILINE
)
PASOS = [
    paso for job in WORKFLOW["jobs"].values() for paso in job["steps"] if "run" in paso
]


def test_resultado_final_depende_de_todos_los_jobs():
    job_final = WORKFLOW["jobs"][JOB_FINAL]

    assert set(job_final["needs"]) == (
        set(WORKFLOW["jobs"]) - {JOB_FINAL} - JOBS_POSTERIORES
    )


def test_resultado_final_corre_aunque_falle_un_job():
    # Sin always() quedaría "skipped", y la protección de rama lo toma
    # como aprobado.
    assert WORKFLOW["jobs"][JOB_FINAL]["if"] == "always()"


@pytest.mark.parametrize("paso", PASOS, ids=lambda paso: paso["run"])
def test_los_pasos_delegan_en_un_objetivo_de_make(paso):
    comando = paso["run"].split()

    assert comando[0] == "make"
    assert len(comando) == 2
    assert comando[1] in OBJETIVOS


def test_ningun_control_ignora_sus_fallos():
    # Solo los enlaces externos informan sin bloquear (docs/matriz-controles.md).
    ignoran = [paso["run"] for paso in PASOS if paso.get("continue-on-error")]

    assert ignoran == ["make enlaces"]
    assert not any(job.get("continue-on-error") for job in WORKFLOW["jobs"].values())


def test_la_documentacion_solo_se_publica_desde_master_si_todo_aprueba():
    publicar = WORKFLOW["jobs"]["publicar-docs"]

    assert publicar["needs"] == [JOB_FINAL]
    assert "refs/heads/master" in publicar["if"]
    assert "always()" not in publicar["if"]


def test_los_secretos_se_buscan_en_todo_el_historial():
    # Un clon superficial revisaría un solo commit, y el control pasaría igual.
    checkout = WORKFLOW["jobs"]["secretos"]["steps"][0]

    assert checkout["with"]["fetch-depth"] == 0


def test_el_reporte_de_secretos_oculta_los_valores():
    # El reporte se publica como artefacto.
    lineas = (RAIZ / "Makefile").read_text("utf-8").splitlines()
    comando = next(linea for linea in lineas if linea.startswith("\t$(GITLEAKS) git"))

    assert "--redact" in comando


@pytest.mark.parametrize(
    "job,reporte",
    [
        ("complejidad", "reportes/lizard.txt"),
        ("tipado", "reportes/mypy.xml"),
        ("tests", "reportes/pruebas.xml"),
    ],
)
def test_el_control_guarda_su_reporte_aunque_rechace(job, reporte):
    subidas = [
        paso
        for paso in WORKFLOW["jobs"][job]["steps"]
        if "upload-artifact" in paso.get("uses", "") and reporte in paso["with"]["path"]
    ]

    assert reporte in (RAIZ / "Makefile").read_text("utf-8")
    assert [paso["if"] for paso in subidas] == ["always()"]


@pytest.mark.parametrize("job", ["seguridad", "documentacion"])
def test_los_jobs_con_npm_fijan_la_version_de_node(job):
    # Sin esto usarían el Node del runner, que cambia con la imagen.
    pasos = WORKFLOW["jobs"][job]["steps"]
    nodo = [paso for paso in pasos if "setup-node" in paso.get("uses", "")]

    assert [paso["with"]["node-version"] for paso in nodo] == [
        "${{ env.NODE_VERSION }}"
    ]


def test_la_version_de_node_del_ci_cumple_lo_que_pide_package_json():
    paquete = json.loads((RAIZ / "package.json").read_text("utf-8"))
    minima = re.fullmatch(r">=(\d+)", paquete["engines"]["node"])[1]

    assert int(WORKFLOW["env"]["NODE_VERSION"]) >= int(minima)


def test_la_seguridad_no_filtra_por_severidad():
    # La política rechaza cualquier hallazgo (docs/seguridad.md). Un filtro dejaría
    # pasar los de menor severidad sin que ningún job falle.
    makefile = (RAIZ / "Makefile").read_text("utf-8").splitlines()
    comandos = [
        linea for linea in makefile if re.search(r"bandit|npm audit|pip-audit", linea)
    ]
    filtros = r"--audit-level|--severity-level|--confidence-level|\s-[li]+(\s|$)"
    configuracion = tomllib.loads((RAIZ / "pyproject.toml").read_text("utf-8"))

    assert comandos
    assert [linea for linea in comandos if re.search(filtros, linea)] == []
    assert "skips" not in configuracion["tool"]["bandit"]
    assert not (RAIZ / ".npmrc").exists()


def test_solo_los_pr_de_dependabot_omiten_sonarcloud():
    pasos = WORKFLOW["jobs"]["tests"]["steps"]
    sonar = next(paso for paso in pasos if paso.get("name") == "SonarCloud")

    assert sonar["if"] == "github.event.pull_request.user.login != 'dependabot[bot]'"


def test_la_complejidad_usa_los_limites_de_la_matriz():
    lineas = (RAIZ / "Makefile").read_text("utf-8").splitlines()
    comando = next(linea for linea in lineas if linea.startswith("\tlizard"))

    assert "-T nloc=50 -C 15" in comando
    assert "-w" in comando.split()


def test_el_tipado_exige_anotar_el_motor_y_la_api():
    configuracion = tomllib.loads((RAIZ / "pyproject.toml").read_text("utf-8"))
    mypy = configuracion["tool"]["mypy"]

    assert mypy["disallow_untyped_defs"] is True
    assert set(mypy["files"]) == {"src/core", "src/optimizado.py", "src/api.py"}
    # Una dependencia sin instalar dejaría de verificarse sin avisar.
    assert "ignore_missing_imports" not in mypy


def test_el_benchmark_compara_contra_el_primer_padre():
    # En un PR, HEAD es el merge: su primer padre es la rama base. Sin ese commit
    # no hay contra qué comparar.
    pasos = WORKFLOW["jobs"]["benchmark"]["steps"]
    benchmark = next(paso for paso in pasos if paso.get("run") == "make benchmark")

    assert benchmark["env"]["BENCHMARK_BASE"] == "HEAD^1"
    assert pasos[0]["with"]["fetch-depth"] >= 2


def test_la_memoria_se_mide_en_su_propio_paso_despues_del_benchmark():
    # tracemalloc encarece lo que mide: no puede compartir paso con los tiempos.
    comandos = [
        paso["run"] for paso in WORKFLOW["jobs"]["benchmark"]["steps"] if "run" in paso
    ]

    assert comandos.index("make benchmark") < comandos.index("make memoria")


def test_el_perfil_y_los_reportes_quedan_aunque_rechace_el_benchmark():
    pasos = WORKFLOW["jobs"]["benchmark"]["steps"]
    posteriores = pasos[
        [paso.get("run") for paso in pasos].index("make benchmark") + 1 :
    ]

    assert len(posteriores) == 3
    assert all("cancelled()" in paso["if"] for paso in posteriores)
