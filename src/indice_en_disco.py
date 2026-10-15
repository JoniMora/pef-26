"""
Índice invertido guardado en disco, por lotes.

Construir el índice de 50.000 documentos lleva varios segundos. Para no
repetirlo cada vez que arranca el programa, se guarda en disco y la
próxima vez se carga.

El guardado aprovecha el MapReduce de :mod:`concurrente`: cada lote se
escribe en su propio archivo JSON apenas termina, mientras los demás
lotes se siguen procesando. Al final se escribe un manifiesto con la
lista de documentos y una firma del corpus; si el corpus cambió, el
índice guardado se descarta y se reconstruye.

Estructura del directorio::

    manifiesto.json    corpus, firma, documentos y números de lote
    lote_000.json      término -> [doc_ids, frecuencias]
    lote_001.json
    ...

Se eligió JSON frente a pickle (carga en 0,69 s contra 0,49 s, con los
16 lotes del corpus de prueba) porque leerlo no puede ejecutar código y
se puede inspeccionar a mano.
"""

import json
import os
from pathlib import Path

import concurrente


# Cambia si cambia la estructura de los archivos: un índice guardado con
# otro formato se descarta y se reconstruye.
FORMATO = 2
MANIFIESTO = "manifiesto.json"


def _archivo_de_lote(numero):
    """
    Devuelve el nombre del archivo de un lote.

    El manifiesto guarda solo números de lote, y el nombre se arma acá: así
    un manifiesto alterado no puede hacer leer archivos fuera del índice.

    :param numero: Número de lote.
    :type numero: int
    :return: El nombre del archivo, por ejemplo ``lote_003.json``.
    :rtype: str
    :raises ValueError: Si ``numero`` no es un entero.
    """
    return f"lote_{int(numero):03}.json"


def directorio_indice_para(corpus_dir):
    """
    Devuelve dónde se guarda por defecto el índice de un corpus.

    Es un directorio hermano del corpus (``data/corpus`` →
    ``data/indice_corpus``). No puede estar adentro: escribir ahí cambiaría
    la fecha de modificación del corpus, que es lo que indica que cambió.

    :param corpus_dir: Directorio del corpus.
    :type corpus_dir: str | pathlib.Path
    :return: El directorio del índice.
    :rtype: pathlib.Path
    """
    corpus = Path(corpus_dir).resolve()
    return corpus.parent / f"indice_{corpus.name}"


def firma_corpus(corpus_dir):
    """
    Resume el estado del corpus para saber si el índice guardado sigue valiendo.

    :param corpus_dir: Directorio del corpus.
    :type corpus_dir: str | pathlib.Path
    :return: La fecha de modificación del directorio, que cambia al agregar,
        borrar o renombrar archivos, y la cantidad de documentos.
    :rtype: dict[str, int]
    """
    corpus = Path(corpus_dir)
    return {
        "mtime_ns": corpus.stat().st_mtime_ns,
        "documentos": sum(1 for _ in corpus.glob("*.txt")),
    }


def construir_y_guardar(corpus_dir, directorio, workers=None):
    """
    Construye el índice en paralelo y lo guarda en disco, un archivo por lote.

    El manifiesto se escribe al final y de forma atómica: si la escritura
    se interrumpe, no hay manifiesto y la próxima carga reconstruye.

    :param corpus_dir: Directorio del corpus.
    :type corpus_dir: str | pathlib.Path
    :param directorio: Directorio donde se guarda el índice.
    :type directorio: str | pathlib.Path
    :param workers: Cantidad de procesos; por defecto, ``os.cpu_count()``.
    :type workers: int | None
    :return: Tupla ``(indice, archivos)``, igual que
        :func:`concurrente.construir_indice`.
    :rtype: tuple[dict[str, dict[int, int]], list[pathlib.Path]]
    """
    corpus = Path(corpus_dir).resolve()
    destino = Path(directorio)
    destino.mkdir(parents=True, exist_ok=True)

    # Se borra el índice anterior antes de empezar: sin manifiesto, un
    # guardado a medias nunca se confunde con uno válido.
    (destino / MANIFIESTO).unlink(missing_ok=True)
    for viejo in destino.glob("lote_*.json"):
        viejo.unlink()

    # La firma se toma antes de indexar: si el corpus cambia durante la
    # construcción, la próxima carga lo detecta.
    firma = firma_corpus(corpus)
    lotes = []

    def guardar_lote(numero, parcial):
        """
        Escribe un lote apenas termina, mientras los demás siguen en proceso.

        :param numero: Número de lote.
        :type numero: int
        :param parcial: Índice parcial del lote.
        :type parcial: dict[str, dict[int, int]]
        """
        nombre = _archivo_de_lote(numero)
        datos = {
            termino: [list(postings), list(postings.values())]
            for termino, postings in parcial.items()
        }
        (destino / nombre).write_text(
            json.dumps(datos, separators=(",", ":")), encoding="utf-8"
        )
        lotes.append(numero)

    indice, archivos = concurrente.construir_indice(
        corpus, workers, al_completar_lote=guardar_lote
    )

    manifiesto = {
        "formato": FORMATO,
        "corpus": str(corpus),
        "firma": firma,
        "archivos": [archivo.name for archivo in archivos],
        "lotes": sorted(lotes),
    }
    temporal = destino / (MANIFIESTO + ".tmp")
    temporal.write_text(json.dumps(manifiesto), encoding="utf-8")
    os.replace(temporal, destino / MANIFIESTO)

    return indice, archivos


def cargar_indice(corpus_dir, directorio):
    """
    Carga el índice guardado, si todavía corresponde al corpus.

    :param corpus_dir: Directorio del corpus.
    :type corpus_dir: str | pathlib.Path
    :param directorio: Directorio donde está guardado el índice.
    :type directorio: str | pathlib.Path
    :return: Tupla ``(indice, archivos)``, o ``None`` si no hay un índice
        guardado, es de otro corpus o de otro formato, el corpus cambió o
        algún archivo está dañado.
    :rtype: tuple[dict[str, dict[int, int]], list[pathlib.Path]] | None
    """
    corpus = Path(corpus_dir).resolve()
    destino = Path(directorio)

    try:
        manifiesto = json.loads((destino / MANIFIESTO).read_text(encoding="utf-8"))

        if (
            manifiesto["formato"] != FORMATO
            or manifiesto["corpus"] != str(corpus)
            or manifiesto["firma"] != firma_corpus(corpus)
        ):
            return None

        indice = {}
        for numero in manifiesto["lotes"]:
            archivo = destino / _archivo_de_lote(numero)
            datos = json.loads(archivo.read_text(encoding="utf-8"))
            concurrente.fusionar(
                indice,
                {
                    termino: dict(zip(doc_ids, frecuencias, strict=True))
                    for termino, (doc_ids, frecuencias) in datos.items()
                },
            )
    except (OSError, ValueError, KeyError, TypeError):
        return None

    return indice, [corpus / nombre for nombre in manifiesto["archivos"]]


def obtener_indice(corpus_dir, directorio, forzar=False):
    """
    Carga el índice guardado o, si no sirve, lo construye y lo guarda.

    :param corpus_dir: Directorio del corpus.
    :type corpus_dir: str | pathlib.Path
    :param directorio: Directorio del índice guardado.
    :type directorio: str | pathlib.Path
    :param forzar: Si es verdadero, reconstruye aunque haya un índice válido.
    :type forzar: bool
    :return: Tupla ``(indice, archivos, desde_disco)``; ``desde_disco``
        indica si se cargó o se construyó.
    :rtype: tuple[dict[str, dict[int, int]], list[pathlib.Path], bool]
    """
    if not forzar:
        cargado = cargar_indice(corpus_dir, directorio)

        if cargado is not None:
            return (*cargado, True)

    return (*construir_y_guardar(corpus_dir, directorio), False)
