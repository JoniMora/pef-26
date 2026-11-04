"""
El job "Resultado final" es la barrera de integración: estos tests corren
el script como lo hace el CI y verifican que no apruebe un control que
falló, se omitió o se canceló.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "resultado_final.py"


def _correr(resultados, tmp_path):
    resumen = tmp_path / "resumen.md"

    proceso = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env={"RESULTADOS": resultados, "GITHUB_STEP_SUMMARY": str(resumen)},
        capture_output=True,
        text=True,
        check=False,
    )

    return proceso, resumen


def _needs(**resultados):
    return json.dumps(
        {
            job: {"result": resultado, "outputs": {}}
            for job, resultado in resultados.items()
        }
    )


def test_aprueba_si_todos_los_jobs_terminan_bien(tmp_path):
    proceso, resumen = _correr(_needs(lint="success", tests="success"), tmp_path)

    assert proceso.returncode == 0
    assert "Resultado final: Aprobado" in resumen.read_text(encoding="utf-8")


@pytest.mark.parametrize("resultado", ["failure", "cancelled", "skipped"])
def test_rechaza_si_un_job_no_termina_bien(tmp_path, resultado):
    proceso, resumen = _correr(_needs(lint="success", tests=resultado), tmp_path)

    assert proceso.returncode == 1
    assert "tests" in proceso.stderr
    assert "lint" not in proceso.stderr
    assert "Resultado final: Rechazado" in resumen.read_text(encoding="utf-8")


@pytest.mark.parametrize("contexto", ["", "{}", "no es json", "[]", '{"lint": {}}'])
def test_rechaza_un_contexto_sin_resultados(tmp_path, contexto):
    proceso, _ = _correr(contexto, tmp_path)

    assert proceso.returncode == 1
    assert "no es un contexto needs" in proceso.stderr
