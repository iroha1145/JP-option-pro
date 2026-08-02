#!/usr/bin/env bash
# 開発プレビュー: フィクスチャ DB + ビルド済みフロントで API サーバーを起動
set -Eeuo pipefail
cd "$(dirname "$0")/../backend"
export DATA_DIR="${DATA_DIR:-/tmp/jp-dev}"
export PYTHONPATH=.
exec ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 2100
