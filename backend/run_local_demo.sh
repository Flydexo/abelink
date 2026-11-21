#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ ! -x "$SCRIPT_DIR/.venv/bin/uvicorn" ]]; then
  echo "Environnement Python manquant dans $SCRIPT_DIR/.venv" >&2
  exit 1
fi

export DEMO_MODE="${DEMO_MODE:-true}"
export ALLOW_DEMO_AUTH="${ALLOW_DEMO_AUTH:-true}"

if [[ -n "${LINKCS_DATA_PATH:-}" ]]; then
  echo "Dataset LinkCS actif : $LINKCS_DATA_PATH"
else
  echo "Astuce : passez LINKCS_DATA_PATH=/chemin/vers/linkcs_amis.json pour charger la base LinkCS."
fi

cleanup() {
  if [[ -n "${BACK_PID:-}" ]]; then
    kill "$BACK_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "Démarrage du backend FastAPI sur http://127.0.0.1:8000 ..."
(
  cd "$SCRIPT_DIR"
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
) &
BACK_PID=$!

echo "Démarrage du frontend Vite sur http://127.0.0.1:5173/app ..."
cd "$REPO_ROOT"
npm run dev
