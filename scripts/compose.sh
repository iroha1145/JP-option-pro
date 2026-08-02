#!/usr/bin/env bash
# Docker Compose の唯一の入り口。環境ファイルの読み込み順を固定する。
set -Eeuo pipefail
cd "$(dirname "$0")/.."

for flag in "$@"; do
  case "$flag" in
    --env-file|--env-file=*|-f|--file|--file=*|--project-directory|--project-directory=*)
      echo "compose.sh: $flag は使用禁止（構成が固定されています）" >&2
      exit 2
      ;;
  esac
done

[ -f machine.env ] || { echo "machine.env がありません（machine.env.example をコピー）" >&2; exit 1; }

export COMPOSE_FILE="docker-compose.yml"
export COMPOSE_ENV_FILES="machine.env"
export OPTIXJP_COMPOSE_ENTRYPOINT="scripts/compose.sh"
exec docker compose "$@"
