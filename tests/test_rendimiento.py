"""
Performance Gate: la consulta optimizada debe responder por debajo
de un límite fijo. Si un cambio introduce una regresión de
rendimiento, este test falla y el pipeline bloquea el merge.

Se corre en un paso aparte del CI y sin cobertura: el tracing de
coverage agrega overhead por línea y distorsionaría la medición.

    pytest -m rendimiento --no-cov -v
    LIMITE_CONSULTA_S=0.0001 pytest -m rendimiento --no-cov   # forzar el fallo
"""

import os
import time

import pytest

from baseline import busqueda_secuencial
from optimizado import Buscador


pytestmark = pytest.mark.rendimiento

LIMITE_CONSULTA_S = float(os.environ.get("LIMITE_CONSULTA_S", "0.5"))
CONSULTA = "algoritmo"
REPETICIONES = 5


def _mejor_tiempo(funcion):
    """
    Mínimo de varias corridas: el ruido de un runner compartido
    (otros procesos, GC, caché de disco) solo puede sumar tiempo,
    así que el mínimo es la estimación más estable del costo real.
    """

    tiempos = []

    for _ in range(REPETICIONES):
        inicio = time.perf_counter()
        funcion()
        tiempos.append(time.perf_counter() - inicio)

    return min(tiempos)


def _consulta_optimizada(indice, archivos):
    # Un Buscador nuevo por corrida: si se reutilizara, a partir de la
    # segunda vuelta se mediría un hit de QueryCache y no la consulta.
    return Buscador(indice, archivos).buscar(CONSULTA)


def test_consulta_optimizada_bajo_el_limite(indice_y_archivos):
    indice, archivos = indice_y_archivos

    tiempo = _mejor_tiempo(lambda: _consulta_optimizada(indice, archivos))

    assert tiempo < LIMITE_CONSULTA_S, (
        f"Regresión de rendimiento: la consulta '{CONSULTA}' tardó "
        f"{tiempo:.4f} s (límite {LIMITE_CONSULTA_S} s, "
        f"{len(archivos)} documentos)"
    )


def test_optimizada_mas_rapida_que_baseline(corpus_dir, indice_y_archivos):
    """
    Chequeo relativo, independiente del hardware del runner: aunque la
    máquina sea lenta, el índice invertido tiene que ganarle al barrido
    secuencial sobre el mismo corpus.
    """

    indice, archivos = indice_y_archivos

    tiempo_optimizado = _mejor_tiempo(
        lambda: _consulta_optimizada(indice, archivos)
    )
    tiempo_baseline = _mejor_tiempo(
        lambda: busqueda_secuencial(str(corpus_dir), CONSULTA)
    )

    assert tiempo_optimizado < tiempo_baseline, (
        f"La versión optimizada ({tiempo_optimizado:.4f} s) no supera a la "
        f"línea base ({tiempo_baseline:.4f} s)"
    )
