# Buscador Eficiente de Información

Motor de búsqueda local (*full-text*) sobre una colección masiva de documentos de texto plano. Implementación en **Python 3.11+**.

Una consulta sobre 50.000 documentos pasa de 2.345 ms con búsqueda secuencial a 8,27 ms con un índice invertido. El proyecto documenta cómo se logró, cómo se midió y a qué costo.

## Documentación

El sitio se publica en <https://jonimora.github.io/pef-26/> al integrar en `master`. Las mismas páginas se pueden leer acá:

| Sección | Contenido |
| :--- | :--- |
| [Descripción funcional](docs/descripcion-funcional.md) | Problema, alcance y requisitos. |
| [Arquitectura](docs/arquitectura.md) | Módulos, responsabilidades, dependencias y diagrama de componentes. |
| [Instalación y ejecución](docs/instalacion.md) | Dependencias, configuración y comandos. |
| [Diseño técnico](docs/diseno-tecnico.md) | Estructuras de datos, algoritmos y decisiones de implementación. |
| [API y contratos](docs/api-contratos.md) | Entradas, salidas, errores y ejemplos. |
| [Pruebas](docs/pruebas.md) | Estrategia, casos y resultados. |
| [Rendimiento](docs/rendimiento.md) | Benchmarks, perfilado, complejidad y memoria. |
| [Seguridad](docs/seguridad.md) | Riesgos, dependencias vulnerables, política de bloqueo y excepciones. |
| [Mantenimiento](docs/mantenimiento.md) | Cómo contribuir, correr los controles y resolver fallos del pipeline. |
| [Matriz de controles](docs/matriz-controles.md) | Herramienta, comando, reporte y criterio de rechazo de cada control. |

## Inicio rápido

```bash
git clone https://github.com/JoniMora/pef-26.git
cd pef-26
python3 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate

python3 src/baseline.py --generar --num-docs 50000     # genera el corpus
python3 src/optimizado.py --query "algoritmo" --top-k 10

pip install -r requirements.txt
uvicorn api:app --app-dir src          # documentación interactiva en http://127.0.0.1:8000/docs
```

Para correr los mismos controles que el CI:

```bash
make instalar
make controles
```

## Pendientes

Verificaciones en GitHub que quedan para después:

- **Quality gate de SonarCloud caído:** solo se vio el caso aprobado. Probarlo deja en SonarCloud una rama de prueba, que se borra desde su panel.
- **Performance Gate en rojo en GitHub:** solo se verificó en local, con un límite imposible. En el CI corre después de SonarCloud, así que probarlo dispara un análisis.
- **Corridas de prueba de "Resultado final":** las [6 corridas en rojo](https://github.com/JoniMora/pef-26/actions?query=event%3Aworkflow_dispatch) (Ruff, Bandit, pip-audit, un test roto, cobertura baja y una cancelada) quedan visibles como evidencia. Falta decidir si se usan en la entrega o se borran.
