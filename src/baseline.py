"""
Línea Base (Baseline) — Buscador Eficiente de Información
------------------------------------------------------------
Búsqueda secuencial por fuerza bruta. Complejidad O(n * m):
n = cantidad de documentos, m = tamaño promedio de cada documento.

Prohibido intencionalmente en este script: índices invertidos,
diccionarios como caché, estructuras set, generadores (yield),
concurrencia/paralelismo y librerías de optimización.

Comandos para correr el script (desde cualquier directorio;
el corpus siempre se genera/lee en <repo>/data/corpus):
    python3 src/baseline.py --generar --num-docs 50000
    python3 src/baseline.py --query "algoritmo"
"""

import argparse
import os
import random
import time

# Directorio raíz del repositorio (padre de src/), calculado a partir de la
# ubicación del propio archivo. Así el corpus siempre se genera/busca en
# <repo>/data/corpus sin importar desde qué directorio se invoque el script.
DIRECTORIO_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRECTORIO_CORPUS_DEFAULT = os.path.join(DIRECTORIO_RAIZ, "data", "corpus")

VOCABULARIO = [
    "programacion", "eficiente", "algoritmo", "estructura", "datos",
    "busqueda", "secuencial", "indice", "documento", "consulta",
    "sistema", "memoria", "tiempo", "ejecucion", "python",
    "funcion", "variable", "lista", "texto", "archivo",
    "corpus", "proceso", "resultado", "analisis", "rendimiento",
    "computadora", "software", "codigo", "modulo", "prueba",
    "red", "servidor", "cliente", "usuario", "dato",
    "vector", "matriz", "objeto", "clase", "metodo",
]


def generar_corpus_prueba(num_docs, directorio=DIRECTORIO_CORPUS_DEFAULT):
    """
    Genera num_docs archivos .txt con texto aleatorio ficticio
    dentro de 'directorio', para disponer de volumen de datos
    de prueba.
    """
    if not os.path.exists(directorio):
        os.makedirs(directorio)

    for i in range(num_docs):
        nombre_archivo = "doc_" + str(i).zfill(6) + ".txt"
        ruta_completa = os.path.join(directorio, nombre_archivo)

        cantidad_palabras = random.randint(50, 300)
        palabras_documento = []
        for _ in range(cantidad_palabras):
            palabra = random.choice(VOCABULARIO)
            palabras_documento.append(palabra)

        contenido = " ".join(palabras_documento)

        archivo = open(ruta_completa, "w", encoding="utf-8")
        archivo.write(contenido)
        archivo.close()

        if (i + 1) % 1000 == 0:
            print("Generados " + str(i + 1) + " / " + str(num_docs) + " documentos")

    print("Corpus de prueba generado en '" + directorio + "' (" + str(num_docs) + " documentos)")


def busqueda_secuencial(directorio, query):
    """
    Recorre secuencialmente todos los archivos del directorio.
    Por cada archivo, lee TODO su contenido en memoria, lo pasa
    a minúsculas y verifica si la query está presente.
    Devuelve la lista de nombres de archivo donde hubo coincidencia.
    """
    resultados = []
    query_minuscula = query.lower()

    nombres_archivos = os.listdir(directorio)

    for nombre_archivo in nombres_archivos:
        if not nombre_archivo.endswith(".txt"):
            continue

        ruta_completa = os.path.join(directorio, nombre_archivo)

        archivo = open(ruta_completa, "r", encoding="utf-8")
        contenido = archivo.read()
        archivo.close()

        contenido_minuscula = contenido.lower()

        if contenido_minuscula.find(query_minuscula) != -1:
            resultados.append(nombre_archivo)

    return resultados


def main():
    parser = argparse.ArgumentParser(description="Buscador secuencial (Línea Base)")
    parser.add_argument("--generar", action="store_true", help="genera el corpus de prueba")
    parser.add_argument("--num-docs", type=int, default=10000, help="cantidad de documentos a generar")
    parser.add_argument("--directorio", type=str, default=DIRECTORIO_CORPUS_DEFAULT, help="directorio del corpus")
    parser.add_argument("--query", type=str, default=None, help="consulta a buscar en el corpus")
    args = parser.parse_args()

    if args.generar:
        generar_corpus_prueba(args.num_docs, args.directorio)

    if args.query is not None:
        inicio = time.perf_counter()
        resultados = busqueda_secuencial(args.directorio, args.query)
        fin = time.perf_counter()

        tiempo_ms = (fin - inicio) * 1000

        print("Tiempo de ejecucion: " + str(round(tiempo_ms, 3)) + " ms")
        print("Documentos encontrados: " + str(len(resultados)))


if __name__ == "__main__":
    main()
