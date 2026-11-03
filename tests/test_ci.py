"""
Protege las reglas del pipeline que se pueden romper sin que ningún job
falle: un job nuevo que no bloquea porque nadie lo sumó a "Resultado final",
o un comando suelto en el YAML que deja de coincidir con el local.
"""

import re
from pathlib import Path

import pytest
import yaml


RAIZ = Path(__file__).resolve().parents[1]
JOB_FINAL = "resultado-final"

WORKFLOW = yaml.safe_load((RAIZ / ".github/workflows/ci.yml").read_text("utf-8"))
OBJETIVOS = re.findall(
    r"^([a-z][a-z-]*):", (RAIZ / "Makefile").read_text("utf-8"), flags=re.MULTILINE
)
PASOS = [
    paso for job in WORKFLOW["jobs"].values() for paso in job["steps"] if "run" in paso
]


def test_resultado_final_depende_de_todos_los_jobs():
    job_final = WORKFLOW["jobs"][JOB_FINAL]

    assert set(job_final["needs"]) == set(WORKFLOW["jobs"]) - {JOB_FINAL}


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
