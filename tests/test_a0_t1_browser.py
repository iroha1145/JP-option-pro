"""Playwright E2E against a real FastAPI + fixture publication + production frontend."""

from __future__ import annotations

import os
import shutil
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


@pytest.fixture(scope="module")
def live_app(tmp_path_factory):
    from app.tools.dev_fixture import build_fixture

    data_dir = tmp_path_factory.mktemp("a0-t1-browser")
    fixture = build_fixture(str(data_dir), days=320)
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "DATA_DIR": str(data_dir),
            "FRONTEND_DIR": str(REPO / "frontend"),
            "PYTHONPATH": str(REPO / "backend"),
        }
    )
    env.pop("JQUANTS_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(REPO / "backend"),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError(proc.stdout.read()[-2000:] if proc.stdout else "uvicorn died")
        try:
            if httpx.get(f"{base}/ready", timeout=0.5).status_code == 200:
                break
        except Exception:
            time.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError("uvicorn not ready")
    yield {"base": base, "fixture": fixture, "proc": proc, "data_dir": data_dir}
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_production_frontend_serves_screener_bundle(live_app):
    page = httpx.get(f"{live_app['base']}/screener", timeout=10)
    assert page.status_code == 200
    assert "选股扫描" in page.text or "screener" in page.text.lower() or "root" in page.text
    production = httpx.get(
        f"{live_app['base']}/api/strength/scan?top=5&ranking_algorithm=production", timeout=10
    )
    scan = httpx.get(f"{live_app['base']}/api/strength/scan?top=5&ranking_algorithm=a0", timeout=10)
    assert scan.status_code == 200
    body = scan.json()
    assert body["effective_algorithm"] == "a0_mid_long"
    assert body["a0_status"] == "active"
    assert body["rows"][0]["a0_available"] is True
    assert production.json()["rows"][0]["canonical_code"]
    assert body["publication_id"] == production.json()["publication_id"]


def test_playwright_switches_algorithm_and_recovers_after_navigation(live_app):
    if shutil.which("playwright") is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            pytest.fail(
                "Playwright is required for the A0/T1 browser gate. "
                "Install with: pip install playwright && python -m playwright install chromium"
            )
    else:
        from playwright.sync_api import sync_playwright

    artifacts = Path("/opt/cursor/artifacts")
    artifacts.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            reduced_motion="reduce",
            locale="zh-CN",
        )
        context.add_init_script("localStorage.setItem('optixjp:locale', 'zh');")
        page = context.new_page()
        console_errors = []
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.goto(f"{live_app['base']}/screener", wait_until="networkidle")
        page.get_by_role("heading", name="选股扫描").wait_for()
        page.get_by_role("tab", name="A0 中长期").click()
        page.get_by_test_id("screener-apply-filters").click()
        page.get_by_test_id("screener-algorithm-status").wait_for()
        status = page.get_by_test_id("screener-algorithm-status").inner_text()
        assert "a0_mid_long" in status
        assert page.get_by_test_id("screener-a0-unavailable").count() == 0
        page.screenshot(path=str(artifacts / "screener-a0-1440.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(artifacts / "screener-a0-390.png"))
        page.goto(f"{live_app['base']}/radar", wait_until="networkidle")
        page.get_by_role("tab", name="T1 日线优先").click()
        page.screenshot(path=str(artifacts / "radar-t1-390.png"))
        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(f"{live_app['base']}/screener", wait_until="networkidle")
        page.get_by_test_id("screener-algorithm-status").wait_for()
        unexplained = [item for item in console_errors if "favicon" not in item.lower()]
        assert unexplained == []
        browser.close()
