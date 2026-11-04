"""
Protege que la instalación sea reproducible: cada versión pedida en un .in
tiene que estar en su lock, con hash, y un cambio a medias no puede pasar.
"""

import json
import re
from pathlib import Path

import pytest
import yaml


RAIZ = Path(__file__).resolve().parents[1]
ENTRADAS = sorted(RAIZ.glob("requirements*.in"))
LOCKS = sorted(RAIZ.glob("requirements*.txt"))
PIN = re.compile(r"^([A-Za-z0-9._-]+)(?:\[[^\]]*\])?==([^\s;\\]+)")


def _nombre(paquete):
    return re.sub(r"[-_.]+", "-", paquete).lower()


def _pines(ruta):
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    coincidencias = (PIN.match(linea) for linea in lineas)

    return {_nombre(pin[1]): pin[2] for pin in coincidencias if pin}


def _requisitos_del_lock(ruta):
    # Une cada paquete con sus líneas de continuación (los hashes).
    texto = ruta.read_text(encoding="utf-8").replace("\\\n", " ")

    return [linea for linea in texto.splitlines() if PIN.match(linea)]


def test_cada_entrada_tiene_su_lock():
    assert [ruta.stem for ruta in ENTRADAS] == [ruta.stem for ruta in LOCKS]


@pytest.mark.parametrize("entrada", ENTRADAS, ids=lambda ruta: ruta.name)
def test_el_lock_tiene_las_versiones_pedidas(entrada):
    pines = _pines(entrada.with_suffix(".txt"))

    faltan = {
        paquete: version
        for paquete, version in _pines(entrada).items()
        if pines.get(paquete) != version
    }

    assert faltan == {}, "Falta correr `make lock`"


@pytest.mark.parametrize("lock", LOCKS, ids=lambda ruta: ruta.name)
def test_cada_paquete_del_lock_tiene_hash(lock):
    requisitos = _requisitos_del_lock(lock)

    assert requisitos
    assert [req for req in requisitos if "--hash=sha256:" not in req] == []


@pytest.mark.parametrize("lock", LOCKS, ids=lambda lock: lock.name)
def test_el_lock_tiene_una_sola_version_de_cada_paquete(lock):
    # Dependabot compara cada paquete con su primera línea en el lock. Con dos
    # versiones, cree que perdió hashes y fallan todas las actualizaciones de Python
    # (docs/mantenimiento.md).
    nombres = [_nombre(PIN.match(req)[1]) for req in _requisitos_del_lock(lock)]

    assert sorted({nombre for nombre in nombres if nombres.count(nombre) > 1}) == []


def test_la_instalacion_exige_los_hashes():
    makefile = (RAIZ / "Makefile").read_text("utf-8")

    assert "pip install --require-hashes -r requirements-dev.txt" in makefile


def test_la_auditoria_cubre_todos_los_locks():
    makefile = (RAIZ / "Makefile").read_text("utf-8")
    auditados = re.search(r"^REQUIREMENTS = (.*)$", makefile, flags=re.MULTILINE)

    assert sorted(auditados[1].split()) == [ruta.name for ruta in LOCKS]


def test_dependabot_cubre_todos_los_ecosistemas():
    config = yaml.safe_load((RAIZ / ".github/dependabot.yml").read_text("utf-8"))

    assert {
        actualizacion["package-ecosystem"] for actualizacion in config["updates"]
    } == {
        "uv",
        "npm",
        "github-actions",
    }


def test_el_lock_de_node_fija_lo_que_pide_package_json():
    pedidos = json.loads((RAIZ / "package.json").read_text("utf-8"))
    lock = json.loads((RAIZ / "package-lock.json").read_text("utf-8"))

    for paquete, version in pedidos["devDependencies"].items():
        assert lock["packages"][f"node_modules/{paquete}"]["version"] == version


def test_los_hashes_de_gitleaks_son_de_la_version_fijada():
    makefile = (RAIZ / "Makefile").read_text("utf-8")
    version = re.search(r"^GITLEAKS_VERSION = (.*)$", makefile, flags=re.MULTILINE)[1]
    hashes = (RAIZ / "scripts/gitleaks.sha256").read_text("utf-8").splitlines()

    assert hashes
    assert all(f"gitleaks_{version}_" in linea for linea in hashes)
