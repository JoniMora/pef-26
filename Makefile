# Controles de calidad: el CI (.github/workflows/ci.yml) solo llama a estos
# objetivos, así que correrlos en local da el mismo resultado. Criterios de
# cada control en docs/matriz-controles.md.

PYTHON ?= python3

.PHONY: instalar lint seguridad tests rendimiento docs enlaces diagrama controles resultado-final

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
	pytest -m "not rendimiento" --cov --cov-report=term-missing --cov-report=xml --cov-report=html

# Aparte y sin cobertura: el tracing distorsiona los tiempos.
rendimiento:
	pytest -m rendimiento --no-cov -v

# -W: cualquier advertencia de Sphinx, incluido un enlace interno roto, rechaza.
# -E: relee todo, para no perder advertencias de páginas que no cambiaron.
docs:
	sphinx-build -W --keep-going -E -b html docs docs/_build/html
	npx --yes markdownlint-cli2@0.24.0 README.md "docs/**/*.md" "#docs/_build"

# El CI informa los enlaces externos sin bloquear: la caída de un sitio ajeno
# no debe frenar un cambio.
enlaces:
	sphinx-build -b linkcheck docs docs/_build/linkcheck

# Requiere Graphviz. El SVG se versiona, para que el CI no lo necesite.
diagrama:
	dot -Tsvg docs/diagramas/arquitectura.dot -o docs/diagramas/arquitectura.svg

controles: lint seguridad tests rendimiento docs

# Solo tiene sentido en el CI: lee los resultados de los jobs de RESULTADOS.
resultado-final:
	$(PYTHON) scripts/resultado_final.py
