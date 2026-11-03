# Controles de calidad: el CI (.github/workflows/ci.yml) solo llama a estos
# objetivos, así que correrlos en local da el mismo resultado. Criterios de
# cada control en docs/matriz-controles.md.

PYTHON ?= python3

.PHONY: instalar lint seguridad tests rendimiento controles

instalar:
	$(PYTHON) -m pip install -r requirements-dev.txt

lint:
	ruff check .
	ruff format --check .

# pip-audit también revisa las dependencias de la API, que
# requirements-dev.txt trae con -r requirements.txt.
seguridad:
	bandit -c pyproject.toml -r .
	pip-audit -r requirements-dev.txt --progress-spinner off

# El umbral de cobertura (fail_under) está en pyproject.toml.
tests:
	pytest -m "not rendimiento" --cov --cov-report=term-missing --cov-report=xml

# Aparte y sin cobertura: el tracing distorsiona los tiempos.
rendimiento:
	pytest -m rendimiento --no-cov -v

controles: lint seguridad tests rendimiento
