#!/usr/bin/env bash
# ==============================================================================
# Script Name:   run.sh
# Description:   Run AP Monitor straight from a source checkout on macOS or Linux.
# Author:        Mai Tan Duc <ducmai.network@gmail.com>
# Created:       2026-10-10
# Version:       1.0.0
# License:       MIT
# ==============================================================================
# Usage:         ./scripts/run.sh [--no-open]
# Notes:         Python 3.10+ required; virtualenv created automatically.
# ==============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${AP_MONITOR_HOST:-127.0.0.1}"
PORT="${AP_MONITOR_PORT:-8766}"
if [[ -z "${PYTHON:-}" ]]; then
  if command -v python3.13 >/dev/null 2>&1; then PY="python3.13"
  elif command -v python3.12 >/dev/null 2>&1; then PY="python3.12"
  else PY="python3"
  fi
else
  PY="$PYTHON"
fi
OPEN=true
for arg in "$@"; do
  case "$arg" in
    --no-open) OPEN=false ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

command -v "$PY" >/dev/null 2>&1 || { echo "Python 3.10+ is required ('$PY' not found)." >&2; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || { echo "Python 3.10 or newer is required." >&2; exit 1; }

if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info < (3, 14) else 1)'; then
  echo "Note: Python 3.14+ may lack wheels for the pinned dependencies; if installing fails, use Python 3.12 or 3.13 (PYTHON=python3.12 ./scripts/run.sh)." >&2
fi

cd "$ROOT_DIR/backend"
VENV=".venv"

# A venv is tied to the OS that created it. One carried over in a zip from
# another machine (a Mac's venv opened on Linux, or the other way round) cannot
# run here, so rebuild it rather than failing with a confusing error.
if [[ -d "$VENV" ]] && ! "$VENV/bin/python" -c 'import sys' >/dev/null 2>&1; then
  echo "==> The existing .venv was made on another system - recreating it"
  rm -rf "$VENV"
fi
if [[ ! -d "$VENV" ]]; then
  echo "==> Creating virtual environment"
  "$PY" -m venv "$VENV"
fi

STAMP="$VENV/.deps-installed"
if [[ ! -f "$STAMP" || requirements.txt -nt "$STAMP" ]]; then
  echo "==> Installing dependencies (needs internet the first time)"
  "$VENV/bin/python" -m pip install -q --upgrade pip
  "$VENV/bin/python" -m pip install -q -r requirements.txt
  touch "$STAMP"
fi

if [[ ! -f "$ROOT_DIR/frontend/dist/index.html" ]]; then
  if command -v npm >/dev/null 2>&1; then
    echo "==> Building the dashboard"
    (cd "$ROOT_DIR/frontend" && npm install --no-audit --no-fund && npm run build)
  else
    echo "==> frontend/dist is missing and npm is not installed: the API will run but there is no dashboard UI." >&2
    echo "    Install Node.js 18+ and re-run, or build on another machine and copy frontend/dist here." >&2
  fi
fi

URL="http://$HOST:$PORT"
if [[ "$OPEN" == true ]]; then
  (
    sleep 2
    if command -v open >/dev/null 2>&1; then open "$URL"
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
    fi
  ) &
fi

echo "==> AP Monitor running at $URL  (Ctrl+C to stop)"
exec "$VENV/bin/python" -m uvicorn app.main:app --host "$HOST" --port "$PORT"
