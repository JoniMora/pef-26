"""
Protege las reglas del pipeline que se pueden romper sin que ningún job
falle: un job nuevo que no bloquea porque nadie lo sumó a "Resultado final",
o un comando suelto en el YAML que deja de coincidir con el local.
"""

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
