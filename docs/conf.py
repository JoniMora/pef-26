"""Configuración de Sphinx para la documentación del buscador."""

import sys
from pathlib import Path


# Los módulos de src/ no forman un paquete y se importan entre sí como
# top-level (`from optimizado import ...`): autodoc necesita src/ en el path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# -- Información del proyecto ------------------------------------------------

project = "Buscador Eficiente de Información"
copyright = "2026, JoniMora, Jorge"
author = "JoniMora, Jorge"

# -- Configuración general ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
]

# Documenta el constructor junto con la clase y respeta el orden del código.
autoclass_content = "both"
autodoc_member_order = "bysource"
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
    # Configuración interna de Pydantic en los modelos de respuesta de la API.
    "exclude-members": "model_config",
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

language = "es"

# -- Salida HTML -------------------------------------------------------------

html_theme = "alabaster"
html_static_path = ["_static"]
