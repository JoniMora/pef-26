"""
Smoke tests de las interfaces de línea de comandos: cada script
arranca, procesa sus argumentos e imprime el resumen esperado.
"""

import sys

import pytest

import baseline
import concurrente
import optimizado


@pytest.fixture
def corpus_chico(tmp_path):
    textos = [
        "algoritmo datos algoritmo",
        "algoritmo estructura",
        "memoria tiempo",
    ]

    for numero, texto in enumerate(textos):
        (tmp_path / f"doc_{numero}.txt").write_text(texto, encoding="utf-8")

    return tmp_path


def _correr(monkeypatch, modulo, *argumentos):
    monkeypatch.setattr(sys, "argv", [modulo.__name__, *argumentos])
    modulo.main()


def test_baseline_genera_y_busca(monkeypatch, capsys, tmp_path):
    destino = tmp_path / "nuevo"

    _correr(
        monkeypatch, baseline,
        "--generar", "--num-docs", "3",
        "--directorio", str(destino),
        "--query", "algoritmo",
    )

    salida = capsys.readouterr().out
    assert "Corpus de prueba generado" in salida
    assert "Documentos encontrados:" in salida


@pytest.mark.parametrize("modulo", [optimizado, concurrente])
def test_muestra_top_k(modulo, monkeypatch, capsys, corpus_chico):
    _correr(
        monkeypatch, modulo,
        "--directorio", str(corpus_chico),
        "--query", "algoritmo",
        "--top-k", "1",
    )

    salida = capsys.readouterr().out
    assert "Documentos encontrados: 2 (se muestran los 1 mejores)" in salida
    assert "1. doc_0.txt" in salida


@pytest.mark.parametrize("modulo", [optimizado, concurrente])
def test_consulta_sin_resultados(modulo, monkeypatch, capsys, corpus_chico):
    _correr(
        monkeypatch, modulo,
        "--directorio", str(corpus_chico),
        "--query", "inexistente",
    )

    salida = capsys.readouterr().out
    assert "Documentos encontrados: 0" in salida
    assert "No se encontraron documentos." in salida


@pytest.mark.parametrize("modulo", [optimizado, concurrente])
def test_solo_indexa_sin_query(modulo, monkeypatch, capsys, corpus_chico):
    _correr(monkeypatch, modulo, "--directorio", str(corpus_chico))

    salida = capsys.readouterr().out
    assert "Documentos indexados: 3" in salida
    assert "Tiempo de búsqueda" not in salida


@pytest.mark.parametrize("modulo", [optimizado, concurrente])
def test_directorio_inexistente(modulo, monkeypatch, capsys, tmp_path):
    _correr(monkeypatch, modulo, "--directorio", str(tmp_path / "no-existe"))

    assert "Error: no existe el directorio" in capsys.readouterr().out


def test_concurrente_compara_con_secuencial(monkeypatch, capsys, corpus_chico):
    _correr(
        monkeypatch, concurrente,
        "--directorio", str(corpus_chico),
        "--workers", "1",
        "--comparar",
    )

    assert "Índices idénticos: True" in capsys.readouterr().out
