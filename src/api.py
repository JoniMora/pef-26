"""
API HTTP del buscador eficiente.

El índice se prepara en la primera consulta y se reutiliza para las
siguientes. Si hay un índice guardado en disco que todavía corresponde al
corpus, se carga en lugar de construirse (ver :mod:`indice_en_disco`);
si no, se construye en paralelo y se guarda para el próximo arranque.

Para saber si el corpus cambió, cada consulta mira solo la fecha de
modificación del directorio, que cambia cuando se agregan, borran o
renombran archivos. Los cambios dentro de un archivo existente no la
alteran: para tomarlos está ``POST /reindexar``.

Para iniciar el servidor desde la raíz del repositorio::

    uvicorn api:app --app-dir src --reload

Variables de entorno opcionales: ``BUSCADOR_CORPUS`` (otro corpus) y
``BUSCADOR_INDICE`` (dónde guardar el índice; por defecto, un directorio
hermano del corpus).
"""

import os
import time
from pathlib import Path
from threading import Lock
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

import indice_en_disco
from optimizado import DEFAULT_CORPUS, Buscador


class Resultado(BaseModel):
    """Un documento del ranking."""

    documento: str = Field(description="Nombre del archivo del corpus.")
    score: float = Field(description="Puntaje TF-IDF; mayor es más relevante.")


class RespuestaBusqueda(BaseModel):
    """Respuesta de ``GET /buscar``."""

    consulta: str = Field(description="La consulta, sin espacios de más.")
    total: int = Field(
        description="Documentos que contienen todos los términos de la consulta."
    )
    resultados: list[Resultado] = Field(
        description="Los mejores documentos, de mayor a menor score."
    )


class RespuestaReindexado(BaseModel):
    """Respuesta de ``POST /reindexar``."""

    documentos: int = Field(description="Documentos indexados.")
    terminos: int = Field(description="Términos distintos en el índice.")
    segundos: float = Field(description="Lo que tardó la reconstrucción.")


# Respuesta de error documentada en Swagger para los dos endpoints.
SIN_CORPUS = {503: {"description": "No existe el directorio del corpus."}}


class ServicioDeBusqueda:
    """
    Mantiene el índice en memoria y lo reconstruye cuando el corpus cambia.

    Un bloqueo evita que dos consultas simultáneas reconstruyan el índice
    a la vez: la segunda espera y reutiliza el de la primera.
    """

    def __init__(self, directorio, directorio_indice=None):
        """
        Crea el servicio sin indexar: el índice se arma en la primera consulta.

        :param directorio: Directorio del corpus.
        :type directorio: str | pathlib.Path
        :param directorio_indice: Dónde se guarda el índice; por defecto,
            :func:`indice_en_disco.directorio_indice_para`.
        :type directorio_indice: str | pathlib.Path | None
        """
        self.directorio = Path(directorio)
        self.directorio_indice = Path(
            directorio_indice or indice_en_disco.directorio_indice_para(directorio)
        )
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
            return self._indexar(self.version_corpus(), forzar=True)

    def _indexar(self, version, forzar=False):
        """
        Carga o construye el índice y lo deja en uso. Requiere el bloqueo.

        :param version: Fecha de modificación del directorio al indexar.
        :type version: int | None
        :param forzar: Si es verdadero, reconstruye aunque haya un índice
            guardado válido.
        :type forzar: bool
        :return: El buscador sobre el índice nuevo.
        :rtype: optimizado.Buscador
        :raises fastapi.HTTPException: 503 si el directorio no existe.
        """
        if not self.directorio.is_dir():
            raise HTTPException(
                status_code=503,
                detail=f"No existe el directorio del corpus: {self.directorio}",
            )

        indice, archivos, _ = indice_en_disco.obtener_indice(
            self.directorio, self.directorio_indice, forzar=forzar
        )
        self._buscador = Buscador(indice, archivos)
        self._version = version

        return self._buscador


def create_app(corpus_dir=None, indice_dir=None):
    """
    Crea la aplicación HTTP para un directorio de corpus.

    :param corpus_dir: Directorio con archivos ``.txt``. Si no se indica,
        usa ``BUSCADOR_CORPUS`` o el corpus predeterminado del proyecto.
    :type corpus_dir: str | pathlib.Path | None
    :param indice_dir: Dónde guardar el índice. Si no se indica, usa
        ``BUSCADOR_INDICE`` o un directorio hermano del corpus.
    :type indice_dir: str | pathlib.Path | None
    :return: Aplicación FastAPI configurada.
    :rtype: fastapi.FastAPI
    """
    servicio = ServicioDeBusqueda(
        corpus_dir or os.environ.get("BUSCADOR_CORPUS") or DEFAULT_CORPUS,
        indice_dir or os.environ.get("BUSCADOR_INDICE"),
    )

    app = FastAPI(
        title="Buscador eficiente",
        description="API de búsqueda sobre un índice invertido TF-IDF.",
        version="1.0.0",
    )

    @app.get(
        "/buscar",
        response_model=RespuestaBusqueda,
        responses=SIN_CORPUS,
        summary="Buscar documentos",
        description=(
            "Devuelve los documentos que contienen todos los términos de la "
            "consulta, ordenados por relevancia (TF-IDF)."
        ),
    )
    def buscar(
        q: Annotated[str, Query(min_length=1, description="Términos a buscar.")],
        top_k: Annotated[
            int, Query(ge=1, le=100, description="Cantidad máxima de resultados.")
        ] = 10,
    ) -> RespuestaBusqueda:
        """
        Devuelve los documentos más relevantes para ``q``.

        :param q: Términos a buscar.
        :type q: str
        :param top_k: Cantidad máxima de resultados, entre 1 y 100.
        :type top_k: int
        :return: El total de coincidencias y el ranking.
        :rtype: RespuestaBusqueda
        """
        consulta = q.strip()
        if not consulta:
            raise HTTPException(
                status_code=422,
                detail="La consulta no puede estar vacía",
            )

        buscador = servicio.obtener_buscador()
        total, resultados = buscador.buscar(consulta, top_k)

        return RespuestaBusqueda(
            consulta=consulta,
            total=total,
            resultados=[
                Resultado(documento=buscador.archivos[doc_id].name, score=score)
                for doc_id, score in resultados
            ],
        )

    @app.post(
        "/reindexar",
        response_model=RespuestaReindexado,
        responses=SIN_CORPUS,
        summary="Reconstruir el índice",
        description=(
            "Reconstruye y vuelve a guardar el índice aunque el directorio del "
            "corpus no haya cambiado. Sirve para tomar cambios dentro de "
            "archivos existentes, que no alteran la fecha del directorio."
        ),
    )
    def reindexar() -> RespuestaReindexado:
        """
        Reconstruye el índice aunque el directorio no haya cambiado.

        Es la forma de tomar cambios dentro de archivos existentes, que no
        alteran la fecha de modificación del directorio.

        :return: Cuántos documentos y términos quedaron, y cuánto tardó.
        :rtype: RespuestaReindexado
        """
        inicio = time.perf_counter()
        buscador = servicio.reindexar()

        return RespuestaReindexado(
            documentos=len(buscador.archivos),
            terminos=len(buscador.indice),
            segundos=round(time.perf_counter() - inicio, 3),
        )

    return app


app = create_app()
