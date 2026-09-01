#!/usr/bin/env bash
# Cloud Agent install: idempotent repository bootstrap.
#   - Python 3.12 backend venv (FastAPI + uvicorn) + pytest
#   - Frontend npm install and production build (populates ./frontend, served by the API)
# No secrets are required: the app runs on a synthetic fixture DB (see .cursor/environment.json
# terminals) and never contacts J-Quants or OpenAI in this mode.
set -Eeuo pipefail
cd "$(dirname "$0")/.."

# python3.12 ships in the base image but its venv/ensurepip module does not.
if ! python3.12 -m venv --help >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3.12-venv
fi

# Backend virtualenv (idempotent: venv creation is safe to repeat).
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r backend/requirements.txt pytest -q

# Frontend dependencies + production build (output lands in ./frontend for the API to serve).
cd frontend-src
npm ci --ignore-scripts --no-audit --no-fund
npm run build
