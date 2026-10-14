Buscador Eficiente de Información
=================================

Documentación técnica del motor de búsqueda local sobre una colección de
documentos de texto plano. Se genera automáticamente a partir de los
docstrings del código fuente (``src/``) con ``sphinx.ext.autodoc``.

El proyecto se compone de estos módulos:

- :mod:`baseline`: búsqueda secuencial por fuerza bruta, la línea base.
- :mod:`core.procesamiento_texto`: normalización, *stemming* y tokenización
  que comparten la versión optimizada y la concurrente.
- :mod:`optimizado`: índice invertido, ranking TF-IDF con *heap* y caché de
  consultas.
- :mod:`concurrente`: construcción del índice en paralelo, como un MapReduce
  sobre procesos.
- :mod:`core.lectura`: lectura de documentos por bloques de tamaño fijo, sin
  cargar cada archivo entero en memoria.
- :mod:`indice_en_disco`: guarda el índice en disco por lotes y lo carga al
  arrancar.
- :mod:`api`: API web con FastAPI: ``GET /buscar`` y ``POST /reindexar``.
- :mod:`perfilado`: arnés de medición y perfilado de las cinco versiones.

.. toctree::
   :maxdepth: 2
   :caption: Contenido:

   api/modules

Índices
-------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
