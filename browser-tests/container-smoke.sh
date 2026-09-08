#!/usr/bin/env bash
# Disposable Docker boot verification. No ports, production volumes or secrets.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
NAME="jp-pr17-smoke-${GITHUB_RUN_ID:-local}-$$"
IMAGE="$NAME:verify"
VOLUME="$NAME-data"
OUT="${JP_BROWSER_EVIDENCE:-$ROOT/browser-evidence}/containers"
mkdir -p "$OUT"
CONF=$(mktemp -d)
cleanup() {
  code=$?
  docker logs "$NAME-api" > "$OUT/api.log" 2>&1 || :
  docker logs "$NAME-worker" > "$OUT/worker.log" 2>&1 || :
  docker rm -f "$NAME-api" "$NAME-worker" >/dev/null 2>&1 || :
  docker volume rm "$VOLUME" >/dev/null 2>&1 || :
  docker image rm "$IMAGE" >/dev/null 2>&1 || :
  rm -rf "$CONF"
  exit "$code"
}
trap cleanup EXIT
cat > "$CONF/personal.toml" <<'EOF'
[access]
mode="private_network"
allowed_private_cidrs=["127.0.0.0/8","::1/128"]
[features]
news_mode="off"
intraday_quotes=false
radar_enabled=true
EOF
chmod 755 "$CONF"; chmod 644 "$CONF/personal.toml"
docker build -f "$ROOT/backend/Dockerfile" -t "$IMAGE" "$ROOT" > "$OUT/build.log" 2>&1
docker volume create "$VOLUME" >/dev/null
COMMON=(--network none --read-only --cap-drop ALL --security-opt no-new-privileges:true
  --tmpfs /tmp:rw,noexec,nosuid,size=128m -v "$VOLUME:/data"
  -v "$CONF/personal.toml:/app/config/test.toml:ro"
  -e DATA_DIR=/data -e PERSONAL_CONFIG_PATH=/app/config/test.toml
  -e HOST_BIND=127.0.0.1 -e JQUANTS_API_KEY= -e OPENAI_API_KEY=)
docker run --rm "${COMMON[@]}" "$IMAGE" python -m app.tools.dev_fixture --days 140 > "$OUT/seed.json"
docker run -d --name "$NAME-worker" "${COMMON[@]}" "$IMAGE" python -m app.worker >/dev/null
docker run -d --name "$NAME-api" "${COMMON[@]}" "$IMAGE" >/dev/null
# Readiness is bounded; no actual supplier calls are possible with network=none.
ready=0
for _ in $(seq 1 45); do
  if docker exec "$NAME-api" python -c "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=1).status == 200" 2>/dev/null &&
     docker exec "$NAME-worker" python -m app.worker --healthcheck > "$OUT/worker-health.json" 2>/dev/null; then
    ready=1; break
  fi
  sleep 1
done
test "$ready" = 1
docker exec -i "$NAME-api" python - <<'PY' > "$OUT/assertions.json"
import json, os, sqlite3, urllib.request
from pathlib import Path
from app.repositories.core import CoreRepository
assert os.getuid() != 0
try:
    Path('/app/pr17-write-probe').write_text('must not work')
except OSError:
    pass
else:
    raise AssertionError('root filesystem unexpectedly writable')
repo = CoreRepository(Path('/data/jp-core.db'), read_only=True)
with repo.read() as con:
    assert con.execute('PRAGMA query_only').fetchone()[0] == 1
    assert con.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    try:
        con.execute('DELETE FROM strength_rows')
    except sqlite3.OperationalError:
        pass
    else:
        raise AssertionError('API read-only connection accepted a write')
body = json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/strength/scan?top=5'))
assert body['publication_id'] and body['stored_score_version'] and body['rows']
assert body['query_kind'] == 'filter'
print(json.dumps({'non_root': True, 'read_only_root': True, 'query_only': True,
                  'wal': True, 'publication_id': body['publication_id'],
                  'stored_score_version': body['stored_score_version']}))
PY
printf 'isolated image/API/worker/WAL/read-only checks passed\n'
