#!/usr/bin/env bash
# Perfila con py-spy la API real bajo carga (etapa 4, punto 8).
#
# Levanta la API sin New Relic, le aplica la carga del escenario 3 de la
# campaña (20 usuarios y una recarga del índice cada 30 s) y la muestrea con
# py-spy, incluidos los procesos que reconstruyen el índice. Deja el
# flamegraph en profiles/pyspy-api.svg, para abrir en el navegador.
#
# En macOS py-spy necesita sudo para leer la memoria de otro proceso: el
# script pide la contraseña al empezar. La API corre con el usuario normal.
#
# Uso, desde la raíz del repositorio y con el entorno virtual activado:
#     bash scripts/perfilar_pyspy.sh [segundos]
set -euo pipefail

SEGUNDOS=${1:-90}
PUERTO=8010
URL="http://127.0.0.1:$PUERTO"
SALIDA=profiles/pyspy-api.svg
PYSPY=$(command -v py-spy) || {
    echo "No se encontró py-spy: pip install -r requirements-perfilado.txt" >&2
    exit 1
}

sudo -v  # pide la contraseña antes de levantar nada

# Sin licencia de New Relic, para no perfilar también al agente.
env -u NEW_RELIC_LICENSE_KEY python src/servidor.py --port "$PUERTO" \
    > profiles/pyspy-servidor.log 2>&1 &
SERVIDOR=$!
CARGA=""
trap 'kill $SERVIDOR $CARGA 2>/dev/null || true' EXIT

echo "Esperando la API (la primera vez construye el índice)..."
until curl -s -o /dev/null --max-time 120 "$URL/buscar?q=python"; do
    kill -0 "$SERVIDOR" 2>/dev/null || {
        echo "La API no arrancó: ver profiles/pyspy-servidor.log" >&2
        exit 1
    }
    sleep 1
done

python src/generar_trafico.py --url "$URL" --duracion "$SEGUNDOS" \
    --concurrencia 20 --reindexar-cada 30 --salida profiles/pyspy-trafico.json &
CARGA=$!

echo "Perfilando la API (proceso $SERVIDOR) durante $SEGUNDOS s..."
# En macOS, --subprocesses puede abortar con "No such process" al recorrer
# los procesos hijos. Si pasa, se perfila solo el proceso de la API: se
# pierden los procesos de la recarga, pero no las búsquedas.
if ! sudo "$PYSPY" record --pid "$SERVIDOR" --subprocesses \
    --duration "$SEGUNDOS" --output "$SALIDA"; then
    echo "py-spy falló con --subprocesses; se reintenta sin los hijos." >&2
    sudo "$PYSPY" record --pid "$SERVIDOR" --duration "$SEGUNDOS" \
        --output "$SALIDA"
fi
sudo chown "$(id -u):$(id -g)" "$SALIDA"

wait "$CARGA"
echo "Flamegraph en $SALIDA"
