# Controles de calidad: el CI (.github/workflows/ci.yml) solo llama a estos
# objetivos, así que correrlos en local da el mismo resultado. Criterios de
# cada control en docs/matriz-controles.md.

PYTHON ?= python3

REQUIREMENTS = requirements.txt requirements-dev.txt requirements-perfilado.txt requirements-apm.txt requirements-informes.txt
PIP_AUDIT = pip-audit --require-hashes --disable-pip --progress-spinner off

# Se baja la versión fijada y se verifica contra scripts/gitleaks.sha256.
GITLEAKS_VERSION = 8.30.1
GITLEAKS_SISTEMA := $(shell uname -s | tr '[:upper:]' '[:lower:]')_$(shell uname -m | sed 's/x86_64/x64/; s/aarch64/arm64/')
GITLEAKS_ARCHIVO = gitleaks_$(GITLEAKS_VERSION)_$(GITLEAKS_SISTEMA).tar.gz
GITLEAKS = .herramientas/gitleaks

# Contra qué se compara el benchmark. En el CI, el primer padre del commit.
BENCHMARK_BASE ?= origin/master

.PHONY: instalar lock lint complejidad tipado seguridad secretos tests rendimiento benchmark docs enlaces diagrama controles resultado-final

instalar:
	$(PYTHON) -m pip install --require-hashes -r requirements-dev.txt

# Regenera los requirements*.txt, con hashes, a partir de los .in. Se editan los
# .in, nunca los .txt. El de desarrollo pide 3.12 porque Sphinx 9 lo exige; el
# resto, el mínimo del proyecto.
lock:
	uv pip compile --universal --generate-hashes --python-version 3.11 requirements.in -o requirements.txt
	uv pip compile --universal --generate-hashes --python-version 3.11 requirements-apm.in -o requirements-apm.txt
	uv pip compile --universal --generate-hashes --python-version 3.11 requirements-perfilado.in -o requirements-perfilado.txt
	uv pip compile --universal --generate-hashes --python-version 3.11 requirements-informes.in -o requirements-informes.txt
	uv pip compile --universal --generate-hashes --python-version 3.12 requirements-dev.in -o requirements-dev.txt

lint:
	ruff check .
	ruff format --check .

# El generador del informe queda afuera: sus funciones largas son el texto del
# documento, con complejidad 1.
complejidad:
	lizard src scripts -x "scripts/generar_informe_newrelic.py" -T nloc=50 -C 15 -w

# El alcance y las reglas están en pyproject.toml.
tipado:
	mypy

# Primero los reportes en JSON, sin frenar si hay hallazgos, para que existan
# aunque el control rechace. Después los mismos análisis, legibles, que deciden.
# pip-audit va de a un lock: rechaza un mismo paquete repetido entre archivos.
seguridad:
	mkdir -p reportes
	-bandit -c pyproject.toml -r . -q -f json -o reportes/bandit.json
	-for lock in $(REQUIREMENTS); do $(PIP_AUDIT) -r $$lock -f json -o reportes/pip-audit-$${lock%.txt}.json; done
	-npm audit --json > reportes/npm-audit.json
	bandit -c pyproject.toml -r .
	@estado=0; for lock in $(REQUIREMENTS); do echo "pip-audit $$lock"; $(PIP_AUDIT) -r $$lock || estado=1; done; exit $$estado
	npm audit

$(GITLEAKS):
	mkdir -p .herramientas
	curl -fsSL -o .herramientas/$(GITLEAKS_ARCHIVO) https://github.com/gitleaks/gitleaks/releases/download/v$(GITLEAKS_VERSION)/$(GITLEAKS_ARCHIVO)
	cd .herramientas && grep $(GITLEAKS_ARCHIVO) ../scripts/gitleaks.sha256 | shasum -a 256 -c -
	tar -xzf .herramientas/$(GITLEAKS_ARCHIVO) -C .herramientas gitleaks

# Todo el historial: un secreto en un commit viejo sigue expuesto. --redact oculta
# los valores en la salida y en el reporte, que se publica como artefacto.
secretos: $(GITLEAKS)
	mkdir -p reportes
	$(GITLEAKS) git --redact --no-banner --verbose --report-format json --report-path reportes/gitleaks.json .

# El umbral de cobertura (fail_under) está en pyproject.toml.
tests:
	pytest -m "not rendimiento" --cov --cov-report=term-missing --cov-report=xml --cov-report=html

# Aparte y sin cobertura: el tracing distorsiona los tiempos.
rendimiento:
	pytest -m rendimiento --no-cov -v

# -W: cualquier advertencia de Sphinx, incluido un enlace interno roto, rechaza.
# -E: relee todo, para no perder advertencias de páginas que no cambiaron.
# Los reportes quedan en reportes/.
benchmark:
	$(PYTHON) scripts/control_rendimiento.py benchmark --base $(BENCHMARK_BASE)

docs: node_modules
	sphinx-build -W --keep-going -E -b html docs docs/_build/html
	npx --no-install markdownlint-cli2 README.md "docs/**/*.md" "#docs/_build"

node_modules: package-lock.json
	npm ci
	touch node_modules

# El CI informa los enlaces externos sin bloquear: la caída de un sitio ajeno
# no debe frenar un cambio.
enlaces:
	sphinx-build -b linkcheck docs docs/_build/linkcheck

# Requiere Graphviz. El SVG se versiona, para que el CI no lo necesite.
diagrama:
	dot -Tsvg docs/diagramas/arquitectura.dot -o docs/diagramas/arquitectura.svg

controles: lint complejidad tipado seguridad secretos tests rendimiento docs benchmark

# Solo tiene sentido en el CI: lee los resultados de los jobs de RESULTADOS.
resultado-final:
	$(PYTHON) scripts/resultado_final.py
