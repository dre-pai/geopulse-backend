#!/usr/bin/env bash
# One-command local / deploy entrypoint for GeoPulse (backend + frontend).
#
# Usage:
#   ./up.sh              # development (hot reload)
#   ./up.sh prod         # production-like stack
#   ./up.sh down         # stop stack
#   ./up.sh logs         # follow logs
#   ./up.sh rebuild      # rebuild images then start (dev)
#   ./up.sh prod rebuild # rebuild images then start (prod)
#
# Expects geopulse-frontend as a sibling directory (or set FRONTEND_DIR).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

FRONTEND_DIR="${FRONTEND_DIR:-$ROOT/../geopulse-frontend}"
export FRONTEND_DIR

ENV_NAME="dev"
ACTION="up"
DETACHED=()
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
Usage: ./up.sh [dev|prod] [up|down|logs|rebuild|ps] [-- extra docker compose args]

Examples:
  ./up.sh
  ./up.sh prod
  ./up.sh down
  ./up.sh prod logs
  ./up.sh rebuild -- --no-cache
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    dev|development)
      ENV_NAME="dev"
      shift
      ;;
    prod|production)
      ENV_NAME="prod"
      shift
      ;;
    up|down|logs|rebuild|ps)
      ACTION="$1"
      shift
      ;;
    -d|--detach)
      DETACHED=(-d)
      shift
      ;;
    --)
      shift
      EXTRA_ARGS+=("$@")
      break
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ ! -d "$FRONTEND_DIR" ]]; then
  echo "error: frontend not found at $FRONTEND_DIR" >&2
  echo "Clone geopulse-frontend as a sibling, or set FRONTEND_DIR." >&2
  exit 1
fi

ensure_env() {
  if [[ ! -f "$ROOT/.env" ]]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    echo "Created $ROOT/.env from .env.example"
  fi
  if [[ ! -f "$FRONTEND_DIR/.env" && -f "$FRONTEND_DIR/.env.example" ]]; then
    cp "$FRONTEND_DIR/.env.example" "$FRONTEND_DIR/.env"
    echo "Created $FRONTEND_DIR/.env from .env.example"
  fi
}

compose() {
  if [[ "$ENV_NAME" == "prod" ]]; then
    docker compose -f docker-compose.yml -f docker-compose.prod.yml "$@"
  else
    # Loads docker-compose.yml + docker-compose.override.yml automatically
    docker compose "$@"
  fi
}

ensure_env

case "$ACTION" in
  up)
    echo "Starting GeoPulse ($ENV_NAME)…"
    echo "  frontend: $FRONTEND_DIR"
    compose up --build ${DETACHED[@]+"${DETACHED[@]}"} ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
    ;;
  rebuild)
    echo "Rebuilding GeoPulse ($ENV_NAME)…"
    compose build ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
    compose up ${DETACHED[@]+"${DETACHED[@]}"}
    ;;
  down)
    compose down ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
    ;;
  logs)
    compose logs -f ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
    ;;
  ps)
    compose ps ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
    ;;
  *)
    usage
    exit 1
    ;;
esac
