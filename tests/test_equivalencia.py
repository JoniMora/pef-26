"""
Equivalencia funcional: la versión optimizada debe encontrar
exactamente los mismos documentos que la búsqueda secuencial.
"""

from baseline import busqueda_secuencial
from optimizado import Buscador


def test_misma_cantidad_de_resultados(corpus_dir, indice_y_archivos):
    indice, archivos = indice_y_archivos

    resultados_baseline = busqueda_secuencial(str(corpus_dir), "algoritmo")
    total_optimizado, _ = Buscador(indice, archivos).buscar("algoritmo")

    # Evita que el test pase en falso con 0 == 0 si el corpus quedó vacío.
    assert len(resultados_baseline) > 0
    assert total_optimizado == len(resultados_baseline)
