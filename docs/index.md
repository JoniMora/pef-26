# Buscador Eficiente de Información

Motor de búsqueda local (*full-text*) sobre una colección masiva de documentos de texto plano, implementado en Python. Una consulta sobre 50.000 documentos pasa de 2.345 ms con búsqueda secuencial a 8,27 ms con un índice invertido; esta documentación explica cómo se logró, cómo se midió y a qué costo.

Para empezar, [Instalación y ejecución](instalacion.md) tiene los comandos, y [Mantenimiento](mantenimiento.md) explica cómo correr en local los mismos controles que el CI.

```{toctree}
:maxdepth: 2
:caption: Documentación

descripcion-funcional
arquitectura
instalacion
diseno-tecnico
api-contratos
pruebas
rendimiento
seguridad
mantenimiento
```

```{toctree}
:maxdepth: 1
:caption: Calidad

matriz-controles
```

```{toctree}
:maxdepth: 2
:caption: Referencia del código

api/modules
```

## Índices

- {ref}`genindex`
- {ref}`modindex`
- {ref}`search`
