#!/usr/bin/env bash
# ビルド → 起動 → 準備完了確認までの最小デプロイ。
set -Eeuo pipefail
cd "$(dirname "$0")/.."
umask 077

command -v docker >/dev/null || { echo "docker が必要です" >&2; exit 1; }
[ -f machine.env ] || { echo "machine.env がありません" >&2; exit 1; }
[ -f secrets.env ] && chmod 600 secrets.env machine.env 2>/dev/null || true

APP_COMMIT="$(git rev-parse HEAD 2>/dev/null || echo local)"
APP_VERSION="${APP_COMMIT:0:12}"
export APP_COMMIT APP_VERSION

./scripts/compose.sh config -q
./scripts/compose.sh build backend
./scripts/compose.sh up -d --no-build --force-recreate --remove-orphans --wait --wait-timeout 180

PORT_VALUE="$(grep -E '^PORT=' machine.env | cut -d= -f2 || echo 2100)"
HOST_VALUE="$(grep -E '^HOST_BIND=' machine.env | cut -d= -f2 || echo 127.0.0.1)"
echo "readiness check http://${HOST_VALUE}:${PORT_VALUE}/ready"
for _ in $(seq 1 30); do
  if curl -fsS "http://${HOST_VALUE}:${PORT_VALUE}/ready" >/dev/null 2>&1; then
    echo "deploy OK (${APP_COMMIT})"
    exit 0
  fi
  sleep 2
done
echo "readiness check failed" >&2
./scripts/compose.sh logs --tail 100 backend worker >&2
exit 1
