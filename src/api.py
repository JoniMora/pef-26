"""
API HTTP del buscador eficiente.

El índice se construye de forma diferida en la primera consulta y se
reutiliza para las siguientes. De esta manera el corpus no se vuelve a
leer por cada petición HTTP.

Para saber si el corpus cambió, cada consulta mira solo la fecha de
modificación del directorio, que cambia cuando se agregan, borran o
renombran archivos. Los cambios dentro de un archivo existente no la
alteran: para tomarlos está ``POST /reindexar``.

Para iniciar el servidor desde la raíz del repositorio::

    uvicorn api:app --app-dir src --reload

También se puede indicar otro corpus con la variable de entorno
``BUSCADOR_CORPUS``.
"""

import os
import time
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Query

from optimizado import DEFAULT_CORPUS, Buscador, construir_indice


class ServicioDeBusqueda:
    """
    Mantiene el índice en memoria y lo reconstruye cuando el corpus cambia.

    Un bloqueo evita que dos consultas simultáneas reconstruyan el índice
    a la vez: la segunda espera y reutiliza el de la primera.
    """

    def __init__(self, directorio):
        """
        Crea el servicio sin indexar: el índice se arma en la primera consulta.

        :param directorio: Directorio del corpus.
        :type directorio: str | pathlib.Path
        """
        self.directorio = Path(directorio)
        self._buscador = None
        self._version = None
        self._bloqueo = Lock()

    def version_corpus(self):
        """
        Devuelve la fecha de modificación del directorio del corpus.

        Es una sola consulta al sistema de archivos, sin importar cuántos
        documentos haya.

        :return: La fecha en nanosegundos, o ``None`` si el directorio no
            existe.
        :rtype: int | None
        """
        try:
            return self.directorio.stat().st_mtime_ns
        except OSError:
            return None

    def obtener_buscador(self):
        """
        Devuelve el buscador vigente y lo reconstruye si el corpus cambió.

        :return: El buscador sobre el índice del corpus actual.
        :rtype: optimizado.Buscador
        :raises fastapi.HTTPException: 503 si el directorio no existe.
        """
        if self._buscador is not None and self._version == self.version_corpus():
            return self._buscador

        with self._bloqueo:
            version = self.version_corpus()
            if self._buscador is not None and self._version == version:
                return self._buscador

            return self._indexar(version)

    def reindexar(self):
        """
        Reconstruye el índice aunque el directorio no haya cambiado.

        :return: El buscador sobre el índice nuevo.
        :rtype: optimizado.Buscador
        :raises fastapi.HTTPException: 503 si el directorio no existe.
        """
        with self._bloqueo:
            return self._indexar(self.version_corpus())

    def _indexar(self, version):
        """
        Construye el índice y lo deja en uso. Se llama con el bloqueo tomado.

        :param version: Fecha de modificación del directorio al indexar.
        :type version: int | None
        :return: El buscador sobre el índice nuevo.
        :rtype: optimizado.Buscador
        :raises fastapi.HTTPException: 503 si el directorio no existe.
        """
        if not self.directorio.is_dir():
            raise HTTPException(
                status_code=503,
                detail=f"No existe el directorio del corpus: {self.directorio}",
            )

        indice, archivos = construir_indice(self.directorio)
        self._buscador = Buscador(indice, archivos)
        self._version = version

        return self._buscador


def create_app(corpus_dir=None):
    """
    Crea la aplicación HTTP para un directorio de corpus.

    :param corpus_dir: Directorio con archivos ``.txt``. Si no se indica,
        usa ``BUSCADOR_CORPUS`` o el corpus predeterminado del proyecto.
    :type corpus_dir: str | pathlib.Path | None
    :return: Aplicación FastAPI configurada.
    :rtype: fastapi.FastAPI
    """
    servicio = ServicioDeBusqueda(
        corpus_dir or os.environ.get("BUSCADOR_CORPUS") or DEFAULT_CORPUS
    )

    app = FastAPI(
        title="Buscador eficiente",
        description="API de búsqueda sobre un índice invertido TF-IDF.",
        version="1.0.0",
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

        buscador = servicio.obtener_buscador()
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

    @app.post("/reindexar")
    def reindexar():
        """
        Reconstruye el índice aunque el directorio no haya cambiado.

        Es la forma de tomar cambios dentro de archivos existentes, que no
        alteran la fecha de modificación del directorio.
        """
        inicio = time.perf_counter()
        buscador = servicio.reindexar()

        return {
            "documentos": len(buscador.archivos),
            "terminos": len(buscador.indice),
            "segundos": round(time.perf_counter() - inicio, 3),
        }

    return app


app = create_app()
