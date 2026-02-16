#!/usr/bin/env bash
# One-click dev runner: backend + frontend
# Usage: ./scripts/dev.sh

set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
export NEXT_PUBLIC_API_BASE="http://localhost:$BACKEND_PORT"

# Check venv
if [[ ! -d .venv ]]; then
  echo "No .venv found. Run: make setup"
  exit 1
fi

# Port in use?
check_port() {
  if lsof -i ":$1" >/dev/null 2>&1; then
    echo "Port $1 is in use. Stop the process or set ${2}=<port>"
    exit 1
  fi
}
check_port "$BACKEND_PORT" "BACKEND_PORT"
check_port "$FRONTEND_PORT" "FRONTEND_PORT"

echo ""
echo "  Backend:  http://localhost:$BACKEND_PORT/docs"
echo "  Frontend: http://localhost:$FRONTEND_PORT"
echo ""

# Run both (trap to kill children on exit)
trap 'kill $(jobs -p) 2>/dev/null' EXIT
(cd pdf_processor && ../.venv/bin/uvicorn server.app:app --reload --host 0.0.0.0 --port "$BACKEND_PORT") &
(cd "$ROOT/frontend" && NEXT_PUBLIC_API_BASE="$NEXT_PUBLIC_API_BASE" npm run dev -- -p "$FRONTEND_PORT") &
wait
