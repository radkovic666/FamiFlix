#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi

if ! python3 -c "import uvicorn" >/dev/null 2>&1; then
  echo "Installing dependencies from requirements.txt..."
  python3 -m pip install -r requirements.txt
fi

exec python3 -m uvicorn server:app --host 0.0.0.0 --port 5050
