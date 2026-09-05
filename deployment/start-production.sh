#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPOSITORY_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PYTHON=${PYTHON:-"$REPOSITORY_ROOT/backend/.venv/bin/python"}

if [ "${PORT+x}" = "x" ]; then
    if [ -z "$PORT" ]; then
        echo "PORT must not be empty" >&2
        exit 1
    fi
else
    PORT=8000
fi

case "$PORT" in
    ''|*[!0-9]*)
        echo "PORT must be an integer between 1 and 65535" >&2
        exit 1
        ;;
esac

if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    echo "PORT must be an integer between 1 and 65535" >&2
    exit 1
fi

if [ ! -x "$PYTHON" ]; then
    echo "Production Python executable is missing or not executable: $PYTHON" >&2
    exit 1
fi

cd "$REPOSITORY_ROOT/backend"

# Deployment contract: one service instance starts one Uvicorn worker.
exec "$PYTHON" -m uvicorn app.main:app \
    --host 127.0.0.1 \
    --port "$PORT" \
    --workers 1 \
    --no-access-log \
    --proxy-headers \
    --forwarded-allow-ips 127.0.0.1
