"""
Mide de qué se compone una recarga del índice (etapa 4, punto 8).

cProfile no ve el trabajo de los procesos hijos que reconstruyen el
índice, y en Python 3.14 mezcla en el árbol de la recarga los hilos
internos del pool. Este script reparte el tiempo de otra forma:

- Cronometra, sin perfilador, listar y ordenar las rutas del corpus, como
  lo hace :func:`concurrente.construir_indice`.
- Hace la misma recarga que ``POST /reindexar`` y cronometra lo que corre
  en el proceso padre: la firma del corpus, guardar cada lote en JSON y
  fusionarlo, y cuándo llega cada lote de los procesos hijos.
- Perfila con cProfile un lote del MapReduce procesado en el proceso
  padre, para ver en qué se va el trabajo de los procesos hijos.

La recarga se guarda en un directorio temporal: no toca el índice que usa
la API. Comando (desde la raíz del repositorio)::

    python scripts/medir_recarga.py --repeticiones 3
"""

import argparse
import contextlib
import cProfile
import os
import pstats
import sys
import tempfile
import time
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Estos imports van después del sys.path.insert: el script se ejecuta
# directamente y necesita src/ en el path para encontrar los módulos.
import concurrente  # noqa: E402
import indice_en_disco  # noqa: E402
from api import ServicioDeBusqueda  # noqa: E402
from optimizado import DEFAULT_CORPUS  # noqa: E402


def sumar(tiempos, clave, inicio):
    """
    Suma a una fase los segundos transcurridos desde ``inicio``.

    :param tiempos: Acumulador de segundos por fase; se completa en el lugar.
    :type tiempos: dict[str, float]
    :param clave: Nombre de la fase.
    :type clave: str
    :param inicio: Instante de inicio, de :func:`time.perf_counter`.
    :type inicio: float
    """
    tiempos[clave] = tiempos.get(clave, 0.0) + time.perf_counter() - inicio


def cronometrada(funcion, tiempos, clave):
    """
    Envuelve una función para que sume su duración a una fase.

    :param funcion: Función a cronometrar.
    :type funcion: collections.abc.Callable
    :param tiempos: Acumulador de segundos por fase.
    :type tiempos: dict[str, float]
    :param clave: Nombre de la fase.
    :type clave: str
    :return: La función envuelta.
    :rtype: collections.abc.Callable
    """

    def envoltura(*args, **kwargs):
        """Llama a la función original y suma su duración a la fase."""
        inicio = time.perf_counter()
        try:
            return funcion(*args, **kwargs)
        finally:
            sumar(tiempos, clave, inicio)

    return envoltura


@contextlib.contextmanager
def reemplazar(modulo, nombre, nueva):
    """
    Reemplaza una función de un módulo mientras dura el bloque.

    :param modulo: Módulo que contiene la función.
    :type modulo: types.ModuleType
    :param nombre: Nombre de la función dentro del módulo.
    :type nombre: str
    :param nueva: Función que la reemplaza.
    :type nueva: collections.abc.Callable
    """
    original = getattr(modulo, nombre)
    setattr(modulo, nombre, nueva)
    try:
        yield
    finally:
        setattr(modulo, nombre, original)


def medir_rutas(corpus):
    """
    Cronometra listar las rutas del corpus y ordenarlas de dos formas.

    :param corpus: Directorio del corpus.
    :type corpus: pathlib.Path
    :return: Segundos de cada paso y la cantidad de documentos.
    :rtype: dict[str, float]
    """
    inicio = time.perf_counter()
    rutas = list(corpus.glob("*.txt"))
    listar = time.perf_counter() - inicio

    inicio = time.perf_counter()
    sorted(rutas)
    como_path = time.perf_counter() - inicio

    inicio = time.perf_counter()
    sorted(rutas, key=lambda ruta: ruta.name)
    por_nombre = time.perf_counter() - inicio

    return {
        "documentos": len(rutas),
        "listar": listar,
        "ordenar como Path": como_path,
        "ordenar por nombre": por_nombre,
    }


def medir_recarga(corpus, directorio_indice):
    """
    Hace una recarga como ``POST /reindexar`` y cronometra sus fases.

    :param corpus: Directorio del corpus.
    :type corpus: pathlib.Path
    :param directorio_indice: Dónde se guarda el índice reconstruido.
    :type directorio_indice: pathlib.Path
    :return: Segundos por fase, el total y cuándo llegó cada lote, en
        segundos desde que empezó :func:`concurrente.construir_indice`.
    :rtype: dict
    """
    tiempos = {}
    llegadas = []
    construir_original = concurrente.construir_indice

    def construir(corpus_dir, workers=None, al_completar_lote=None, **kwargs):
        """Construye el índice registrando cuándo llega y se guarda cada lote."""
        inicio = time.perf_counter()

        def guardar(numero, parcial):
            """Registra la llegada del lote y cronometra su guardado."""
            llegadas.append(time.perf_counter() - inicio)
            guardado = time.perf_counter()
            al_completar_lote(numero, parcial)
            sumar(tiempos, "guardar los lotes en JSON", guardado)

        try:
            return construir_original(
                corpus_dir, workers, al_completar_lote=guardar, **kwargs
            )
        finally:
            tiempos["construir_indice"] = time.perf_counter() - inicio

    servicio = ServicioDeBusqueda(corpus, directorio_indice)

    firma = cronometrada(indice_en_disco.firma_corpus, tiempos, "firma del corpus")
    fusionar = cronometrada(concurrente.fusionar, tiempos, "fusionar los lotes")

    with (
        reemplazar(indice_en_disco, "firma_corpus", firma),
        reemplazar(concurrente, "fusionar", fusionar),
        reemplazar(concurrente, "construir_indice", construir),
    ):
        inicio = time.perf_counter()
        servicio.reindexar()
        total = time.perf_counter() - inicio

    return {"total": total, "fases": tiempos, "llegadas": llegadas}


def perfilar_lote(corpus, procesos):
    """
    Procesa un lote del MapReduce en el proceso padre, sin y con cProfile.

    El lote es el primero de la misma partición que usa
    :func:`concurrente.construir_indice` con ``procesos`` procesos.

    :param corpus: Directorio del corpus.
    :type corpus: pathlib.Path
    :param procesos: Cantidad de procesos de la recarga.
    :type procesos: int
    :return: Tamaño del lote, cantidad de lotes, segundos sin perfilador y
        la parte del tiempo perfilado que se va en tokenizar y en leer.
    :rtype: dict
    """
    rutas = sorted(corpus.glob("*.txt"))
    tareas = [(doc_id, str(ruta)) for doc_id, ruta in enumerate(rutas)]
    lotes = concurrente._lotes_equitativos(
        tareas, procesos * concurrente.LOTES_POR_PROCESO
    )
    lote = lotes[0]

    inicio = time.perf_counter()
    concurrente._procesar_lote(lote)
    segundos = time.perf_counter() - inicio

    perfil = cProfile.Profile()
    perfil.runcall(concurrente._procesar_lote, lote)
    acumulado = {
        funcion: datos[3]
        for (_, _, funcion), datos in pstats.Stats(perfil).stats.items()
    }
    total = acumulado["_procesar_lote"]

    return {
        "documentos": len(lote),
        "lotes": len(lotes),
        "segundos": segundos,
        "tokenizar": acumulado["tokenizar"] / total,
        "leer": acumulado["leer_en_bloques"] / total,
    }


def imprimir_recarga(numero, recarga):
    """
    Imprime las fases de una recarga.

    :param numero: Número de repetición.
    :type numero: int
    :param recarga: Resultado de :func:`medir_recarga`.
    :type recarga: dict
    """
    fases = recarga["fases"]
    llegadas = recarga["llegadas"]
    print(f"\nRecarga {numero}: {recarga['total']:.2f} s")
    for fase in ("firma del corpus", "guardar los lotes en JSON", "fusionar los lotes"):
        print(f"  {fase}: {fases.get(fase, 0.0):.2f} s")
    print(
        f"  construir_indice: {fases['construir_indice']:.2f} s "
        f"({len(llegadas)} lotes: el primero a los {llegadas[0]:.2f} s, "
        f"el último a los {llegadas[-1]:.2f} s)"
    )


def main():
    """Mide las rutas, las recargas y un lote, e imprime los resultados."""
    parser = argparse.ArgumentParser(
        description="Mide de qué se compone una recarga del índice"
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=os.environ.get("BUSCADOR_CORPUS") or DEFAULT_CORPUS,
    )
    parser.add_argument("--repeticiones", type=int, default=3)
    args = parser.parse_args()

    corpus = Path(args.corpus).resolve()
    procesos = os.cpu_count() or 1

    rutas = medir_rutas(corpus)
    print(f"Corpus: {corpus} ({rutas['documentos']} documentos), {procesos} procesos")
    print("\nRutas, sin perfilador:")
    for paso in ("listar", "ordenar como Path", "ordenar por nombre"):
        print(f"  {paso}: {rutas[paso]:.2f} s")

    with tempfile.TemporaryDirectory() as temporal:
        for numero in range(1, args.repeticiones + 1):
            imprimir_recarga(numero, medir_recarga(corpus, Path(temporal)))

    lote = perfilar_lote(corpus, procesos)
    print(f"\nUn lote de {lote['documentos']} documentos, en el proceso padre:")
    print(
        f"  sin perfilador: {lote['segundos']:.2f} s "
        f"({lote['lotes']} lotes: {lote['segundos'] * lote['lotes']:.1f} s de CPU)"
    )
    print(
        f"  con cProfile: tokenizar {lote['tokenizar']:.0%}, "
        f"leer los archivos {lote['leer']:.0%}"
    )


# La guarda es obligatoria: la recarga crea procesos con el método de
# arranque spawn, que vuelve a importar este script.
if __name__ == "__main__":
    main()
