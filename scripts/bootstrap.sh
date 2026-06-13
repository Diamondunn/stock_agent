#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$ROOT_DIR"

echo "==> Preparing local stock_agent environment"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python command not found: $PYTHON_BIN" >&2
  echo "Install Python 3.11+ or set PYTHON_BIN=/path/to/python." >&2
  exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
  echo "==> Creating virtual environment at .venv"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

PY="$VENV_DIR/bin/python"

echo "==> Upgrading pip"
"$PY" -m pip install --upgrade pip

echo "==> Installing dependencies"
"$PY" -m pip install -r requirements.txt

if [[ ! -f ".env" ]]; then
  echo "==> Creating local .env from .env.example"
  cp .env.example .env
else
  echo "==> Keeping existing local .env"
fi

mkdir -p data logs cache

echo
echo "Bootstrap complete."
echo
echo "Next steps:"
echo "  source .venv/bin/activate"
echo "  edit .env"
echo "  uvicorn web.main:app --reload"
echo
echo "Dashboard:"
echo "  http://127.0.0.1:8000/portfolio/embed"
