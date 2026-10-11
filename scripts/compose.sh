#!/usr/bin/env bash
# Japan defaults; explicit Docker Compose flags can override files or project.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
export COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-jp-option-pro}"
if [ -f machine.env ]; then
  export COMPOSE_ENV_FILES="${COMPOSE_ENV_FILES:-machine.env}"
fi
exec docker compose "$@"
