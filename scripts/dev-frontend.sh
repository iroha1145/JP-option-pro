#!/usr/bin/env bash
# フロントだけを HMR で回す。API はデフォルトで本番（読み取り専用の公開
# エンドポイント）に向ける —— ローカルのフィクスチャ DB には実データが
# 入っていないので、見た目の確認には本物の応答が要る。
#
#   OPTIXJP_API_PROXY=http://127.0.0.1:2100 scripts/dev-frontend.sh
#
# でローカル API に切り替えられる。
set -Eeuo pipefail
cd "$(dirname "$0")/../frontend-src"
export OPTIXJP_API_PROXY="${OPTIXJP_API_PROXY:-https://jp-option.openweb-ui.xyz}"
exec npx vite --host 127.0.0.1 --port 2101
