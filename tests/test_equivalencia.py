"""
Equivalencia funcional: la versión optimizada debe encontrar
exactamente los mismos documentos que la búsqueda secuencial.
"""

import pytest

from baseline import busqueda_secuencial
from optimizado import Buscador, buscar, normalizar_consulta


# Consultas cuyo término no cambia con el stemming: para ellas las dos
# semánticas tienen que coincidir. "datos" queda afuera a propósito: la
# versión optimizada la reduce a "dato" y encuentra también los documentos
# que solo dicen "dato", que la línea base no ve (ver "Validación de
# equivalencia" en el README).
CONSULTAS_INVARIANTES = ("algoritmo", "indice", "python")


@pytest.mark.parametrize("consulta", CONSULTAS_INVARIANTES)
def test_mismas_coincidencias(corpus_dir, indice_y_archivos, consulta):
    indice, archivos = indice_y_archivos

    documentos_baseline = set(busqueda_secuencial(str(corpus_dir), consulta))
    documentos_optimizado = {
        archivos[doc_id].name
        for doc_id in buscar(indice, normalizar_consulta(consulta))
    }
    total_optimizado, _ = Buscador(indice, archivos).buscar(consulta)

    # Evita que el test pase en falso con dos conjuntos vacíos.
    assert documentos_baseline
    assert documentos_optimizado == documentos_baseline
    assert total_optimizado == len(documentos_baseline)
