"""
Tiempo de las operaciones representativas del motor y de la API.

No aprueban ni rechazan por sí solos: ``make benchmark`` compara lo que miden
contra la rama base (ver docs/rendimiento.md).
"""

import concurrente
from baseline import busqueda_secuencial
from core.lectura import contar_terminos
from core.procesamiento_texto import tokenizar
from indice_en_disco import cargar_indice
from optimizado import Buscador, construir_indice


CONSULTA = "algoritmo"
VARIOS_TERMINOS = "algoritmo datos memoria"


def test_tokenizar(benchmark, corpus_dir):
    texto = (corpus_dir / "doc_000000.txt").read_text(encoding="utf-8")

    benchmark(tokenizar, texto)


def test_contar_terminos(benchmark, corpus_dir):
    benchmark(contar_terminos, corpus_dir / "doc_000000.txt")


def test_indexar_secuencial(benchmark, corpus_dir):
    benchmark(construir_indice, corpus_dir)


def test_indexar_en_paralelo(benchmark, corpus_dir):
    benchmark(concurrente.construir_indice, corpus_dir)


def test_cargar_indice_de_disco(benchmark, corpus_dir, indice_guardado):
    benchmark(cargar_indice, corpus_dir, indice_guardado)


def test_busqueda_secuencial(benchmark, corpus_dir):
    benchmark(busqueda_secuencial, str(corpus_dir), CONSULTA)


def test_consulta_de_un_termino(benchmark, indice_y_archivos):
    indice, archivos = indice_y_archivos

    # Un Buscador nuevo por corrida: si no, se mediría un acierto de la caché.
    benchmark(lambda: Buscador(indice, archivos).buscar(CONSULTA))


def test_consulta_de_varios_terminos(benchmark, indice_y_archivos):
    indice, archivos = indice_y_archivos

    benchmark(lambda: Buscador(indice, archivos).buscar(VARIOS_TERMINOS))


def test_consulta_con_cache_caliente(benchmark, indice_y_archivos):
    buscador = Buscador(*indice_y_archivos)
    buscador.buscar(CONSULTA)

    benchmark(buscador.buscar, CONSULTA)


def test_api_buscar(benchmark, cliente):
    cliente.get("/buscar", params={"q": CONSULTA})

    benchmark(cliente.get, "/buscar", params={"q": CONSULTA})
