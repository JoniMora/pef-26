"""
Protege lo que la construcción de Sphinx no ve: que estén las secciones
exigidas, que los enlaces absolutos al repositorio apunten a archivos que
existen y que ningún módulo ni objetivo de make quede sin documentar.
"""

import re
from pathlib import Path

import pytest


RAIZ = Path(__file__).resolve().parents[1]
DOCS = RAIZ / "docs"

SECCIONES = {
    "descripcion-funcional": "Descripción funcional",
    "arquitectura": "Arquitectura",
    "instalacion": "Instalación y ejecución",
    "diseno-tecnico": "Diseño técnico",
    "api-contratos": "API y contratos",
    "pruebas": "Pruebas",
    "rendimiento": "Rendimiento",
    "seguridad": "Seguridad",
    "mantenimiento": "Mantenimiento",
}
ENLACE_AL_REPOSITORIO = re.compile(
    r"https://github\.com/JoniMora/pef-26/(?:blob|tree)/master/([^)#\s]+)"
)
PAGINAS = [RAIZ / "README.md", *sorted(DOCS.glob("*.md"))]


def _leer(ruta):
    return ruta.read_text(encoding="utf-8")


@pytest.mark.parametrize("pagina,titulo", SECCIONES.items())
def test_la_seccion_existe_con_su_titulo(pagina, titulo):
    assert _leer(DOCS / f"{pagina}.md").splitlines()[0] == f"# {titulo}"


def test_el_indice_incluye_todas_las_secciones():
    lineas = _leer(DOCS / "index.md").splitlines()

    assert [pagina for pagina in SECCIONES if pagina not in lineas] == []


@pytest.mark.parametrize("pagina", PAGINAS, ids=lambda pagina: pagina.name)
def test_los_enlaces_al_repositorio_apuntan_a_archivos_que_existen(pagina):
    enlaces = ENLACE_AL_REPOSITORIO.findall(_leer(pagina))

    assert [ruta for ruta in enlaces if not (RAIZ / ruta).exists()] == []


def test_la_arquitectura_documenta_todos_los_modulos():
    texto = _leer(DOCS / "arquitectura.md")
    fuentes = RAIZ / "src"
    modulos = [
        ruta.relative_to(fuentes).as_posix()
        for ruta in fuentes.rglob("*.py")
        if ruta.name != "__init__.py"
    ]

    assert [modulo for modulo in modulos if f"`{modulo}`" not in texto] == []


def test_la_arquitectura_documenta_todos_los_scripts():
    texto = _leer(DOCS / "arquitectura.md")
    scripts = [
        ruta.relative_to(RAIZ).as_posix() for ruta in (RAIZ / "scripts").glob("*.py")
    ]

    assert scripts
    assert [script for script in scripts if f"`{script}`" not in texto] == []


def test_mantenimiento_explica_cada_objetivo_de_make():
    texto = _leer(DOCS / "mantenimiento.md")
    objetivos = re.findall(
        r"^([a-z][a-z-]*):", _leer(RAIZ / "Makefile"), flags=re.MULTILINE
    )

    assert objetivos
    assert [obj for obj in objetivos if f"make {obj}" not in texto] == []
