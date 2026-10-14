"""
Tests de la lectura por bloques (``core.lectura``): leer un archivo por
partes tiene que dar exactamente los mismos términos que leerlo entero.
"""

from collections import Counter

import pytest

import concurrente
import optimizado
from core import lectura
from core.lectura import contar_terminos, leer_en_bloques
from core.procesamiento_texto import tokenizar


TEXTO = (
    "El algoritmo indexa los datos.\nCada documento tiene palabras, "
    "y la canción del niño habla de árboles y de redes   neuronales.\n"
    "Python   procesa   el corpus\tcon funciones y métodos.\n"
)

TAMANOS = [1, 2, 3, 7, 16, 64, 10_000]


@pytest.fixture
def archivo(tmp_path):
    ruta = tmp_path / "doc.txt"
    ruta.write_text(TEXTO, encoding="utf-8")
    return ruta


@pytest.mark.parametrize("tamano", TAMANOS)
def test_los_bloques_no_cortan_palabras(archivo, tamano):
    fragmentos = list(leer_en_bloques(archivo, tamano))

    # Ningún fragmento termina a mitad de una palabra que sigue en el
    # siguiente: tokenizar por partes da lo mismo que tokenizar el total.
    tokens = [token for fragmento in fragmentos for token in tokenizar(fragmento)]
    assert tokens == tokenizar(TEXTO)


@pytest.mark.parametrize("tamano", TAMANOS)
def test_contar_terminos_igual_que_leer_entero(archivo, tamano):
    assert contar_terminos(archivo, tamano) == Counter(tokenizar(TEXTO))


def test_palabra_mas_larga_que_el_bloque(tmp_path):
    ruta = tmp_path / "doc.txt"
    ruta.write_text("procesamiento algoritmo", encoding="utf-8")

    assert contar_terminos(ruta, 4) == Counter({"procesamiento": 1, "algoritmo": 1})


def test_archivo_vacio(tmp_path):
    ruta = tmp_path / "vacio.txt"
    ruta.write_bytes(b"")

    assert list(leer_en_bloques(ruta)) == []
    assert contar_terminos(ruta) == Counter()


def test_ruta_ilegible_lanza_oserror(tmp_path):
    (tmp_path / "carpeta.txt").mkdir()

    with pytest.raises(OSError):
        contar_terminos(tmp_path / "carpeta.txt")


@pytest.mark.parametrize(
    "construir",
    [optimizado.construir_indice, concurrente.construir_indice],
    ids=["secuencial", "concurrente"],
)
def test_indice_con_bloques_chicos_igual_al_de_bloques_grandes(
    tmp_path, monkeypatch, construir
):
    for numero in range(5):
        (tmp_path / f"doc_{numero}.txt").write_text(TEXTO * (numero + 1))

    indice_grande, _ = construir(tmp_path)

    # Con bloques de 5 bytes, casi todas las palabras cruzan un corte.
    monkeypatch.setattr(lectura, "TAMANO_BLOQUE", 5)
    indice_chico, _ = construir(tmp_path)

    assert indice_chico == indice_grande


def test_archivo_que_termina_justo_en_el_borde_de_un_bloque(tmp_path):
    ruta = tmp_path / "doc.txt"
    ruta.write_text("datos redes", encoding="utf-8")  # 11 bytes

    assert list(leer_en_bloques(ruta, 11)) == ["datos", "redes"]
    assert contar_terminos(ruta, 11) == Counter({"dato": 1, "red": 1})


def test_caracter_de_varios_bytes_partido_entre_bloques(tmp_path):
    ruta = tmp_path / "doc.txt"
    # "ñ" y "á" ocupan 2 bytes: con bloques de 1 byte siempre quedan partidos.
    ruta.write_text("niño árbol canción", encoding="utf-8")

    assert contar_terminos(ruta, 1) == Counter(tokenizar("niño árbol canción"))
