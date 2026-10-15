"""
Lectura de documentos por bloques de tamaño fijo.

En lugar de cargar cada archivo entero con ``read()``, lo lee de a
bloques de ``TAMANO_BLOQUE`` bytes. La memoria que usa la lectura queda
acotada por el tamaño del bloque, no por el del archivo, así que el
índice se puede construir sobre documentos de cualquier tamaño.

Un bloque puede cortar dos cosas, y las dos se resuelven:

- **Un carácter de varios bytes** (``á``, ``ñ``): el decodificador
  incremental de UTF-8 guarda los bytes incompletos y los completa con
  el bloque siguiente.
- **Una palabra:** cada bloque se procesa hasta su último espacio en
  blanco, y lo que queda después se antepone al bloque siguiente.
"""

import codecs
from collections import Counter

from core.procesamiento_texto import tokenizar


# Bytes por bloque. Los documentos del corpus de prueba pesan alrededor
# de 1,4 KB, así que cada uno se lee en un solo bloque.
TAMANO_BLOQUE = 64 * 1024


def leer_en_bloques(ruta, tamano_bloque=None):
    """
    Lee un archivo de texto por bloques sin cortar caracteres ni palabras.

    Cada fragmento termina en un espacio en blanco, salvo el último. Una
    palabra más larga que el bloque se acumula hasta encontrar un espacio,
    así que nunca se parte.

    :param ruta: Archivo a leer, en UTF-8. Los bytes inválidos se ignoran.
    :type ruta: str | pathlib.Path
    :param tamano_bloque: Bytes por lectura; por defecto, ``TAMANO_BLOQUE``.
    :type tamano_bloque: int | None
    :return: Los fragmentos del texto, en orden.
    :rtype: collections.abc.Iterator[str]
    :raises OSError: Si el archivo no se puede abrir.
    """
    tamano = tamano_bloque or TAMANO_BLOQUE
    decodificador = codecs.getincrementaldecoder("utf-8")(errors="ignore")
    pendiente = ""

    with open(ruta, "rb") as archivo:
        while datos := archivo.read(tamano):
            # Un bloque más corto que lo pedido es el último del archivo:
            # no hay nada después que pueda continuar una palabra. Así un
            # documento que entra en un bloque se procesa de una sola vez.
            ultimo = len(datos) < tamano
            texto = pendiente + decodificador.decode(datos, final=ultimo)
            pendiente = ""

            if ultimo:
                break

            # Si el bloque termina en un espacio (o quedó vacío porque solo
            # traía parte de un carácter), ninguna palabra quedó cortada.
            if not texto or texto[-1].isspace():
                if texto:
                    yield texto
                continue

            partes = texto.rsplit(None, 1)

            # Sin espacios no hay un corte seguro: se sigue acumulando.
            if len(partes) == 1:
                pendiente = texto
                continue

            yield partes[0]
            pendiente = partes[1]
        else:
            # El archivo terminó justo en el borde de un bloque.
            texto = pendiente + decodificador.decode(b"", final=True)

    if texto:
        yield texto


def contar_terminos(ruta, tamano_bloque=None):
    """
    Cuenta los términos de un documento leyéndolo por bloques.

    :param ruta: Archivo a leer.
    :type ruta: str | pathlib.Path
    :param tamano_bloque: Bytes por lectura; por defecto, ``TAMANO_BLOQUE``.
    :type tamano_bloque: int | None
    :return: Frecuencia de cada término normalizado del documento.
    :rtype: collections.Counter
    :raises OSError: Si el archivo no se puede abrir.
    """
    frecuencias = Counter()

    for fragmento in leer_en_bloques(ruta, tamano_bloque):
        frecuencias.update(tokenizar(fragmento))

    return frecuencias
