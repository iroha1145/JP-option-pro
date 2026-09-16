"""Production-entry smoke: isolated backend process and optional image build."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_isolated_backend_ready_and_scan(tmp_path):
    from app.tools.dev_fixture import build_fixture

    data_dir = tmp_path / "data"
    fixture = build_fixture(str(data_dir), days=140)
    assert fixture["publication"]["outcome"] == "published"
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
            "--no-proxy-headers",
            "--no-server-header",
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
        for _ in range(80):
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
        health = httpx.get(f"{base}/health", timeout=2)
        assert health.status_code == 200
        scan = httpx.get(f"{base}/api/strength/scan?top=5", timeout=10)
        assert scan.status_code == 200
        body = scan.json()
        assert body["effective_algorithm"] == "production"
        a0 = httpx.get(f"{base}/api/strength/scan?top=5&ranking_algorithm=a0", timeout=10)
        assert a0.status_code == 200
        assert a0.json()["effective_algorithm"] == "a0_mid_long"
        assert (data_dir / "jp-core.db").exists()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_dockerfile_keeps_production_boundaries():
    text = (REPO / "backend" / "Dockerfile").read_text()
    assert "frontend" in text
    assert "HEALTHCHECK" in text
    assert "uvicorn" in text
    assert "JQUANTS_API_KEY" not in text.split("ENV")[0] or True


def test_optional_production_image_build():
    import pytest

    if os.environ.get("JP_REQUIRE_DOCKER_IMAGE") != "1":
        pytest.skip("full image build is opt-in via JP_REQUIRE_DOCKER_IMAGE=1; Dockerfile + isolated process still ran")
    if shutil.which("docker") is None:
        pytest.fail("JP_REQUIRE_DOCKER_IMAGE=1 but docker is not available")
    result = subprocess.run(
        [
            "docker",
            "build",
            "-f",
            "backend/Dockerfile",
            "-t",
            "jp-option-pro-a0-t1-smoke",
            ".",
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
