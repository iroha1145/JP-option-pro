"""H03/F01: production frontend build + real local API process.

This starts the committed frontend directory through the real ASGI app.
Vendor calls are not made; scan is read-only against a fixture publication.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture()
def dual_service(tmp_path, monkeypatch):
    from app.tools.dev_fixture import build_fixture

    data_dir = tmp_path / "data"
    fixture = build_fixture(str(data_dir), days=140)
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "DATA_DIR": str(data_dir),
            "FRONTEND_DIR": str(REPO / "frontend"),
            "PYTHONPATH": str(REPO / "backend"),
            "HOST_BIND": "127.0.0.1",
        }
    )
    env.pop("JQUANTS_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(REPO / "backend"),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        last_error = None
        for _ in range(50):
            if proc.poll() is not None:
                output = proc.stdout.read() if proc.stdout else ""
                raise RuntimeError(f"uvicorn exited {proc.returncode}: {output[-2000:]}")
            try:
                response = httpx.get(f"{base}/ready", timeout=0.5)
                if response.status_code == 200:
                    break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
            time.sleep(0.1)
        else:
            raise RuntimeError(f"uvicorn did not become ready: {last_error}")
        yield {"base": base, "fixture": fixture, "proc": proc}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_h03_f01_production_frontend_serves_filter_not_update(dual_service):
    base = dual_service["base"]
    fixture = dual_service["fixture"]
    html = httpx.get(f"{base}/screener", timeout=5)
    assert html.status_code == 200
    assert "text/html" in html.headers.get("content-type", "")
    scan = httpx.get(f"{base}/api/strength/scan?top=10", timeout=10)
    assert scan.status_code == 200
    body = scan.json()
    assert body["query_kind"] == "filter"
    assert body["publication_id"] == fixture["publication"]["publication_id"]
    assert body["stored_score_version"]
    # HTTP 200 + 旧/当前快照都不是「新的日线计算」。
    assert body.get("queried_at")
    js = (REPO / "frontend").read_text() if False else ""
    bundle = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (REPO / "frontend" / "assets").glob("Screener-*.js")
    )
    assert "更新日线与评分" in bundle
    assert "盘中价较新不等于日线评分已更新" in bundle
    assert "快照日期早于当前目标交易日" in bundle
    assert js == ""


def test_g07_g08_bundle_keeps_quote_and_score_copy():
    pair = (REPO / "frontend-src" / "src" / "components" / "screener" / "quotePair.ts").read_text()
    assert "live_change_pct" in pair
    assert "change_pct" in pair
    bundle = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (REPO / "frontend" / "assets").glob("Screener-*.js")
    )
    assert "盘中价较新不等于日线评分已更新" in bundle
