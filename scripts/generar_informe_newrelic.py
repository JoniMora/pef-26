"""
Genera el informe en PDF del monitoreo con New Relic.

Arma ``docs/informe-new-relic.pdf`` a partir de las capturas de
``docs/newrelic-capturas/``. Necesita las dependencias de
``requirements-informes.txt``::

    pip install -r requirements-informes.txt
    python scripts/generar_informe_newrelic.py
"""

from pathlib import Path

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image as ReportImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


DOCS = Path(__file__).resolve().parents[1] / "docs"
CAPTURES = DOCS / "newrelic-capturas"
OUTPUT = DOCS / "informe-new-relic.pdf"


def add_footer(canvas, document):
    """
    Dibuja el pie de página con el título del informe y el número de página.

    :param canvas: Lienzo de la página que se está generando.
    :type canvas: reportlab.pdfgen.canvas.Canvas
    :param document: Documento en construcción.
    :type document: reportlab.platypus.SimpleDocTemplate
    """
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawString(
        2 * cm, 1.2 * cm, "Buscador Eficiente - Informe de monitoreo con New Relic"
    )
    canvas.drawRightString(19 * cm, 1.2 * cm, f"Página {document.page}")
    canvas.restoreState()


def screenshot(filename, width=17.2 * cm):
    """
    Inserta una captura respetando su proporción.

    :param filename: Nombre del archivo dentro de ``docs/newrelic-capturas``.
    :type filename: str
    :param width: Ancho de la imagen en el PDF.
    :type width: float
    :return: La imagen lista para agregar al documento.
    :rtype: reportlab.platypus.Image
    """
    path = CAPTURES / filename
    with Image.open(path) as image:
        ratio = image.height / image.width
    return ReportImage(str(path), width=width, height=width * ratio)


styles = getSampleStyleSheet()
styles.add(
    ParagraphStyle(
        name="CoverTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontSize=24,
        leading=30,
        textColor=colors.HexColor("#17324D"),
        spaceAfter=18,
    )
)
styles.add(
    ParagraphStyle(
        name="CoverSubtitle",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontSize=14,
        leading=20,
        textColor=colors.HexColor("#3D566E"),
    )
)
styles.add(
    ParagraphStyle(
        name="Heading",
        parent=styles["Heading1"],
        textColor=colors.HexColor("#17324D"),
        spaceBefore=10,
        spaceAfter=8,
    )
)
styles.add(
    ParagraphStyle(
        name="Small",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
    )
)


def p(text, style="BodyText"):
    """
    Crea un párrafo con uno de los estilos del informe.

    :param text: Texto del párrafo; admite el marcado de ReportLab.
    :type text: str
    :param style: Nombre del estilo.
    :type style: str
    :return: El párrafo.
    :rtype: reportlab.platypus.Paragraph
    """
    return Paragraph(text, styles[style])


def construir_contenido():
    """
    Arma, en orden, todos los elementos del informe.

    :return: Párrafos, tablas, capturas y saltos de página del informe.
    :rtype: list
    """
    story = []

    story.extend(
        [
            Spacer(1, 3.5 * cm),
            p("Informe de monitoreo de una API FastAPI con New Relic", "CoverTitle"),
            p("Buscador eficiente de documentos", "CoverSubtitle"),
            Spacer(1, 1.2 * cm),
            p("Trabajo práctico para presentación en clase", "CoverSubtitle"),
            p(
                "Evidencias obtenidas durante las pruebas del 14 de octubre de 2026",
                "CoverSubtitle",
            ),
            Spacer(1, 5 * cm),
            p(
                "<b>Aplicación observada:</b> Buscador Eficiente - PEF<br/>"
                "<b>Tecnologías:</b> Python, FastAPI, Uvicorn y agente New Relic "
                "Python<br/>"
                "<b>Endpoint principal:</b> GET /buscar",
                "CoverSubtitle",
            ),
            PageBreak(),
        ]
    )

    story.extend(
        [
            p("1. Resumen ejecutivo", "Heading"),
            p(
                "Se instrumentó la API del buscador de documentos con el agente New "
                "Relic para "
                "observar su comportamiento mientras recibía solicitudes HTTP reales. "
                "La aplicación "
                "se inició mediante <b>newrelic-admin.exe run-program</b>, se "
                "configuró una License "
                "Key válida y se registró en APM con el nombre <b>Buscador Eficiente - "
                "PEF</b>."
            ),
            p(
                "Las capturas muestran que New Relic recibió solicitudes del endpoint "
                "<b>/buscar</b>, registró transacciones web, calculó tiempos de "
                "respuesta, "
                "contabilizó el throughput, generó trazas distribuidas y almacenó "
                "logs. La "
                "respuesta funcional de la API fue HTTP 200 y una consulta de ejemplo "
                "devolvió "
                "957 documentos para el término <b>algoritmo</b>."
            ),
            p(
                "Conclusión principal: la integración con New Relic quedó operativa y "
                "permitió "
                "analizar el rendimiento de la API desde el punto de vista de una "
                "aplicación en ejecución."
            ),
            p("2. Objetivos", "Heading"),
            p(
                "• Instrumentar la API FastAPI sin modificar su lógica de "
                "búsqueda.<br/>"
                "• Registrar solicitudes HTTP y medir sus tiempos de respuesta.<br/>"
                "• Analizar throughput, errores, transacciones, trazas y logs.<br/>"
                "• Relacionar las métricas observadas con el funcionamiento del "
                "buscador.<br/>"
                "• Obtener evidencias visuales para explicar el trabajo en clase."
            ),
            p("3. Configuración y metodología", "Heading"),
            p(
                "La aplicación se ejecutó desde el entorno virtual del proyecto con "
                "Python 3.13, "
                "Uvicorn y el agente New Relic Python 14.0.0. El servidor quedó "
                "disponible en "
                "<b>http://127.0.0.1:8002</b>. La ejecución instrumentada tuvo esta "
                "estructura:"
            ),
            p(
                "<font name='Courier'>newrelic-admin.exe run-program python.exe -m "
                "uvicorn "
                "api:app --app-dir src --port 8002</font>"
            ),
            p(
                "Luego se realizaron consultas al endpoint con términos como "
                "<b>algoritmo</b>, <b>python</b> y <b>archivo</b>. Se conservaron las "
                "capturas "
                "que aportaban información medible y se descartaron duplicados y una "
                "vista sin "
                "actividad suficiente."
            ),
            PageBreak(),
        ]
    )

    story.extend(
        [
            p("4. Traducción de los principales indicadores", "Heading"),
            Table(
                [
                    ["Indicador original", "Traducción", "Qué representa"],
                    ["Summary", "Resumen", "Vista general del servicio."],
                    [
                        "Web transactions time",
                        "Tiempo de transacciones web",
                        "Duración de las solicitudes HTTP.",
                    ],
                    [
                        "Throughput",
                        "Rendimiento / solicitudes por minuto",
                        "Cantidad de solicitudes recibidas.",
                    ],
                    [
                        "Error rate",
                        "Tasa de errores",
                        "Porcentaje de solicitudes con error.",
                    ],
                    [
                        "Apdex score",
                        "Índice Apdex",
                        "Satisfacción del usuario según el tiempo de respuesta.",
                    ],
                    [
                        "Transactions",
                        "Transacciones",
                        "Operaciones web agrupadas por nombre.",
                    ],
                    [
                        "Distributed tracing",
                        "Trazas distribuidas",
                        "Recorrido interno de una solicitud.",
                    ],
                    [
                        "Logs",
                        "Registros",
                        "Mensajes emitidos por la aplicación o el servidor.",
                    ],
                    [
                        "Response time",
                        "Tiempo de respuesta",
                        "Tiempo empleado para atender una operación.",
                    ],
                ],
                colWidths=[4.2 * cm, 5 * cm, 8 * cm],
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B8C4CE")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#EEF3F7")],
                        ),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                ),
            ),
            p("5. Evidencia 1: resumen de rendimiento", "Heading"),
            screenshot("01-resumen.png"),
            p(
                "<b>Interpretación:</b> el gráfico de tiempo de transacción muestra "
                "picos "
                "cercanos a 41 ms y 27 ms. El throughput presenta varias solicitudes "
                "alrededor "
                "de las 16:40 y 16:45. El error rate queda prácticamente en cero "
                "durante el "
                "intervalo observado. El Apdex alcanza valores cercanos a 0,9, lo que "
                "indica "
                "una experiencia satisfactoria para las solicitudes registradas.",
                "Small",
            ),
            PageBreak(),
        ]
    )

    story.extend(
        [
            p("6. Evidencia 2: transacciones web", "Heading"),
            screenshot("02-transacciones.png"),
            p(
                "<b>Datos visibles:</b> la transacción principal "
                "<font name='Courier'>api:create_app.&lt;locals&gt;.buscar</font> "
                "concentra "
                "el 98,48 % del tiempo consumido. La transacción del middleware de "
                "excepciones "
                "representa el 1,52 % restante. El tiempo de respuesta promedio más "
                "lento "
                "observado es de 68,4 ms; el throughput máximo registrado es 0,200 rpm "
                "y la "
                "tasa máxima de error indicada es 0 %."
            ),
            p(
                "<b>Interpretación:</b> el procesamiento está concentrado en el "
                "handler "
                "<b>buscar</b>, que es exactamente el punto funcional que interesa "
                "analizar. "
                "La presencia del middleware no implica un fallo: forma parte de la "
                "cadena "
                "normal de atención de la solicitud."
            ),
            p("7. Evidencia 3: errores", "Heading"),
            screenshot("03-errores.png"),
            p(
                "La vista de errores no encuentra errores aplicacionales dentro del "
                "rango "
                "seleccionado. El pequeño registro de tasa de errores observado en "
                "otras "
                "capturas coincide con solicitudes a rutas no definidas, como <b>/</b> "
                "o "
                "<b>/favicon.ico</b>, que responden 404. No debe confundirse un 404 de "
                "una "
                "ruta auxiliar con un fallo del endpoint principal <b>/buscar</b>, que "
                "respondió "
                "200 durante las pruebas."
            ),
            PageBreak(),
        ]
    )

    story.extend(
        [
            p("8. Evidencia 4: trazas distribuidas", "Heading"),
            screenshot("04-trazas.png"),
            p(
                "New Relic registró cuatro trazas en el período mostrado. La traza "
                "principal "
                "corresponde a la transacción del buscador y presenta una duración de "
                "hasta "
                "aproximadamente 41,55 ms en el percentil 95 mostrado. También aparece "
                "la "
                "traza del middleware de excepciones, con una duración aproximada de "
                "2,10 ms "
                "en su percentil indicado. El error rate de las trazas es 0."
            ),
            p(
                "<b>Utilidad:</b> una métrica indica cuánto tarda una operación, "
                "mientras que "
                "una traza ayuda a entender por dónde pasó la solicitud. En este caso, "
                "la "
                "traza confirma que la mayor parte del tiempo está asociada al handler "
                "del "
                "buscador y no al middleware."
            ),
            p("9. Evidencia 5: logs de las solicitudes", "Heading"),
            screenshot("05-logs.png"),
            p(
                "Los registros muestran cuatro solicitudes concretas: tres consultas "
                "válidas "
                "al endpoint <b>/buscar</b> con respuestas HTTP 200 y una solicitud a "
                "<b>/favicon.ico</b> con respuesta 404. Las consultas registradas "
                "fueron "
                "<b>algoritmo</b>, <b>python</b> y <b>archivo</b>. Esta captura es una "
                "de las "
                "evidencias más importantes porque relaciona las métricas de New Relic "
                "con "
                "acciones concretas realizadas sobre la API."
            ),
            PageBreak(),
        ]
    )

    story.extend(
        [
            p("10. Análisis técnico del comportamiento", "Heading"),
            p(
                "La primera consulta puede presentar un costo mayor porque la API "
                "construye "
                "o actualiza el índice del corpus antes de responder. Una vez que el "
                "índice "
                "queda disponible, las consultas siguientes reutilizan esa estructura "
                "y "
                "evitan repetir todo el trabajo de lectura e indexación. Por ese "
                "motivo, "
                "es esperable observar una primera medición más alta y luego tiempos "
                "menores."
            ),
            p(
                "Las capturas de New Relic complementan el análisis de Scalene. "
                "Scalene permite "
                "estudiar el costo de líneas de código y diferenciar CPU Python, CPU "
                "nativo y "
                "memoria. New Relic observa el servicio funcionando: solicitudes, "
                "transacciones, "
                "errores, trazas y logs. Usadas juntas, ambas herramientas permiten "
                "relacionar "
                "el hotspot interno con el efecto visible para el usuario."
            ),
            p("11. Limitaciones y observaciones", "Heading"),
            p(
                "• La prueba tuvo pocas solicitudes y se realizó en un entorno local, "
                "por lo que "
                "no representa una carga de producción.<br/>"
                "• Los gráficos de New Relic dependen del rango temporal seleccionado "
                "y pueden "
                "mostrar 0 rpm aunque hayan existido solicitudes aisladas.<br/>"
                "• La vista de errores incluye rutas auxiliares no implementadas, como "
                "favicon, "
                "pero el endpoint funcional respondió correctamente.<br/>"
                "• Las capturas fueron tomadas en inglés; este informe traduce los "
                "indicadores "
                "y conserva los nombres técnicos originales cuando son necesarios para "
                "ubicarlos "
                "en la interfaz."
            ),
            p("12. Conclusiones", "Heading"),
            p(
                "La integración con New Relic fue exitosa: el agente Python 14.0.0 "
                "aceptó la "
                "License Key, registró el servicio <b>Buscador Eficiente - PEF</b> y "
                "comenzó "
                "a reportar datos. El endpoint <b>/buscar</b> generó transacciones "
                "web, logs "
                "con respuestas 200 y trazas sin errores. El tiempo observado fue "
                "bajo, con "
                "picos de aproximadamente 27 a 41 ms en el resumen y un máximo "
                "promedio "
                "indicado de 68,4 ms en la vista de transacciones."
            ),
            p(
                "El resultado permite defender técnicamente que el sistema funciona y "
                "que "
                "New Relic es útil para observar el comportamiento real de una API, "
                "mientras "
                "que Scalene aporta el diagnóstico detallado del código que produce "
                "ese comportamiento."
            ),
            p("13. Guion breve para la exposición", "Heading"),
            p(
                "“Instrumenté mi API FastAPI con el agente New Relic Python y la "
                "ejecuté mediante "
                "newrelic-admin. Realicé tres búsquedas sobre el endpoint /buscar. New "
                "Relic "
                "registró las solicitudes como transacciones web, mostró los tiempos "
                "de respuesta, "
                "el throughput y el Apdex. Las trazas indican que la mayor parte del "
                "tiempo se "
                "consume en el handler del buscador. Los logs confirman tres "
                "respuestas HTTP 200 "
                "y un 404 correspondiente al favicon. Por lo tanto, la aplicación "
                "funciona "
                "correctamente y el monitoreo permite observar su rendimiento desde el "
                "punto de "
                "vista del usuario.”"
            ),
        ]
    )

    return story


def main():
    """Genera el PDF en ``docs/informe-new-relic.pdf`` e imprime su ruta."""
    story = construir_contenido()

    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=1.7 * cm,
        bottomMargin=1.8 * cm,
        title="Informe de monitoreo con New Relic - Buscador Eficiente",
        author="PEF",
    )
    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
    print(OUTPUT)


if __name__ == "__main__":
    main()
