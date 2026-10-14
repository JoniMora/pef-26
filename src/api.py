"""
API HTTP del buscador eficiente.

El índice se construye de forma diferida en la primera consulta y se
reutiliza para las siguientes. De esta manera el corpus no se vuelve a
leer por cada petición HTTP.

Para iniciar el servidor desde la raíz del repositorio::

    uvicorn api:app --app-dir src --reload

También se puede indicar otro corpus con la variable de entorno
``BUSCADOR_CORPUS``.
"""

import os
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Query

from optimizado import DEFAULT_CORPUS, Buscador, construir_indice


def create_app(corpus_dir=None):
    """
    Crea la aplicación HTTP para un directorio de corpus.

    :param corpus_dir: Directorio con archivos ``.txt``. Si no se indica,
        usa ``BUSCADOR_CORPUS`` o el corpus predeterminado del proyecto.
    :type corpus_dir: str | pathlib.Path | None
    :return: Aplicación FastAPI configurada.
    :rtype: fastapi.FastAPI
    """
    directorio = Path(corpus_dir or os.environ.get("BUSCADOR_CORPUS") or DEFAULT_CORPUS)
    estado = {"buscador": None, "firma_corpus": None}
    bloqueo = Lock()

    app = FastAPI(
        title="Buscador eficiente",
        description="API de búsqueda sobre un índice invertido TF-IDF.",
        version="1.0.0",
    )

    def obtener_buscador():
        """Construye o actualiza el buscador de forma segura."""
        firma_corpus = _firma_corpus()
        if estado["buscador"] is not None and estado["firma_corpus"] == firma_corpus:
            return estado["buscador"]

        with bloqueo:
            firma_corpus = _firma_corpus()
            if (
                estado["buscador"] is not None
                and estado["firma_corpus"] == firma_corpus
            ):
                return estado["buscador"]

            if not directorio.is_dir():
                raise HTTPException(
                    status_code=503,
                    detail=f"No existe el directorio del corpus: {directorio}",
                )

            indice, archivos = construir_indice(directorio)
            estado["buscador"] = Buscador(indice, archivos)
            estado["firma_corpus"] = firma_corpus

        return estado["buscador"]

    def _firma_corpus():
        """Devuelve una firma barata para detectar cambios en el corpus."""
        if not directorio.is_dir():
            return None

        archivos = directorio.glob("*.txt")
        return tuple(
            (archivo.name, archivo.stat().st_mtime_ns, archivo.stat().st_size)
            for archivo in sorted(archivos)
        )

    @app.get("/buscar")
    def buscar(
        q: str = Query(..., min_length=1, description="Texto a buscar"),
        top_k: int = Query(
            10,
            ge=1,
            le=100,
            description="Cantidad máxima de resultados",
        ),
    ):
        """Devuelve los documentos más relevantes para ``q``."""
        consulta = q.strip()
        if not consulta:
            raise HTTPException(
                status_code=422,
                detail="La consulta no puede estar vacía",
            )

        buscador = obtener_buscador()
        total, resultados = buscador.buscar(consulta, top_k)

        return {
            "consulta": consulta,
            "total": total,
            "resultados": [
                {
                    "documento": buscador.archivos[doc_id].name,
                    "score": score,
                }
                for doc_id, score in resultados
            ],
        }

    return app


app = create_app()
