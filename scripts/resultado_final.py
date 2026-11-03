"""
Decide el resultado final del pipeline de CI.

Lo corre el job "Resultado final", el único check obligatorio para integrar
en ``master``: falla si algún job del que depende no terminó bien y deja la
tabla de controles en el resumen de la corrida. Recibe en ``RESULTADOS`` el
contexto ``needs`` de GitHub Actions::

    RESULTADOS='{"lint": {"result": "success"}}' python scripts/resultado_final.py
"""

import json
import os
import sys
from pathlib import Path


def leer_resultados(contexto):
    """
    Obtiene el resultado de cada job a partir del contexto ``needs``.

    :param contexto: Contexto ``needs`` de GitHub Actions, en JSON.
    :type contexto: str
    :return: Job -> resultado (``success``, ``failure``, ``cancelled`` o
        ``skipped``).
    :rtype: dict[str, str]
    :raises ValueError: Si el contexto no es JSON o no trae ningún job.
    """
    needs = json.loads(contexto)

    if not needs:
        raise ValueError("el contexto no trae ningún job")

    return {job: datos["result"] for job, datos in needs.items()}


def jobs_rechazados(resultados):
    """
    Lista los jobs que rechazan el cambio.

    Solo ``success`` aprueba: un job omitido o cancelado no verificó nada.

    :param resultados: Job -> resultado.
    :type resultados: dict[str, str]
    :return: Jobs que no terminaron en ``success``.
    :rtype: list[str]
    """
    return [job for job, resultado in resultados.items() if resultado != "success"]


def armar_resumen(resultados):
    """
    Arma la tabla de controles en Markdown.

    :param resultados: Job -> resultado.
    :type resultados: dict[str, str]
    :return: Resumen de la corrida, con el veredicto y un job por fila.
    :rtype: str
    """
    veredicto = "Rechazado" if jobs_rechazados(resultados) else "Aprobado"
    filas = [f"| {job} | {resultado} |" for job, resultado in resultados.items()]

    return "\n".join(
        [f"## Resultado final: {veredicto}", "", "| Job | Resultado |", "| --- | --- |"]
        + filas
    )


def main():
    """Imprime el veredicto, lo agrega al resumen y sale con error si rechaza."""
    try:
        resultados = leer_resultados(os.environ.get("RESULTADOS", ""))
    except (ValueError, AttributeError, KeyError, TypeError) as error:
        sys.exit(f"RESULTADOS no es un contexto needs válido: {error}")

    resumen = armar_resumen(resultados)
    print(resumen)

    destino = os.environ.get("GITHUB_STEP_SUMMARY")

    if destino:
        with Path(destino).open("a", encoding="utf-8") as archivo:
            archivo.write(resumen + "\n")

    rechazados = jobs_rechazados(resultados)

    if rechazados:
        sys.exit(f"Jobs que rechazan el cambio: {', '.join(rechazados)}")


if __name__ == "__main__":
    main()
