"""Owner HTTP → persistent queue → independent worker → production scan read-back.

This is not a browser test. It does start a real uvicorn process and a
separate worker process. Vendor I/O is synthetic; mapping/clean/score/publish
use production modules against a temporary SQLite fixture.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_ready(base: str, proc: subprocess.Popen) -> None:
    last_error = None
    for _ in range(80):
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"process exited {proc.returncode}: {output[-2000:]}")
        try:
            response = httpx.get(f"{base}/ready", timeout=0.5)
            if response.status_code == 200:
                return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"uvicorn did not become ready: {last_error}")


def _spawn(data_dir: Path, *, engine: str) -> dict:
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "DATA_DIR": str(data_dir),
            "FRONTEND_DIR": str(REPO / "frontend"),
            "PYTHONPATH": str(REPO / "backend"),
            "HOST_BIND": "127.0.0.1",
            "JP_TEST_ENGINE": engine,
            "JP_TEST_TARGET": "2026-09-08",
        }
    )
    env.pop("JQUANTS_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    api = subprocess.Popen(
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
    worker = subprocess.Popen(
        [sys.executable, str(REPO / "tests/support/synthetic_worker.py")],
        cwd=str(REPO),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_ready(base, api)
    except Exception:
        api.kill()
        worker.kill()
        raise
    return {"base": base, "api": api, "worker": worker}


def _stop(bundle: dict) -> None:
    for key in ("worker", "api"):
        proc = bundle.get(key)
        if proc is None:
            continue
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


def _poll_action(client: httpx.Client, action_id: int, *, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        response = client.get(f"/api/worker/actions/{action_id}")
        if response.status_code == 200:
            last = response.json()
            if last.get("status") in {"completed", "failed"}:
                return last
        time.sleep(0.2)
    return last


@pytest.fixture()
def fixture_dir(tmp_path):
    from app.tools.dev_fixture import build_fixture

    data_dir = tmp_path / "data"
    fixture = build_fixture(str(data_dir), days=140, end_date=date(2026, 9, 8))
    return data_dir, fixture


def test_h03_owner_queue_independent_worker_readback(fixture_dir):
    data_dir, fixture = fixture_dir
    old_id = fixture["publication"]["publication_id"]
    bundle = _spawn(data_dir, engine="ok")
    try:
        with httpx.Client(base_url=bundle["base"], timeout=5.0) as client:
            scan = client.get("/api/strength/scan?top=5")
            assert scan.status_code == 200
            before = scan.json()
            accepted = client.post(
                "/api/worker/actions/post_close_batch",
                json={},
                headers={"X-Optix-Action": "1", "Origin": bundle["base"]},
            )
            assert accepted.status_code == 202
            action_id = accepted.json()["action_id"]
            finished = _poll_action(client, action_id)
            assert finished.get("status") == "completed"
            outcome = (finished.get("result") or {}).get("outcome")
            assert outcome in {"published", "already_current"}
            promised = ((finished.get("result") or {}).get("radar") or {}).get("publication") or {}
            after = client.get("/api/strength/scan?top=5").json()
            assert after["query_kind"] == "filter"
            assert after["publication_id"]
            if promised.get("publication_id"):
                assert after["publication_id"] == promised["publication_id"]
            if outcome == "already_current":
                assert after["publication_id"] == old_id
            assert after["publication_id"] == before["publication_id"] or outcome == "published"
    finally:
        _stop(bundle)


def test_h03_vendor_bar_failure_keeps_previous_publication(fixture_dir):
    data_dir, fixture = fixture_dir
    old_id = fixture["publication"]["publication_id"]
    bundle = _spawn(data_dir, engine="fail_bars")
    try:
        with httpx.Client(base_url=bundle["base"], timeout=5.0) as client:
            accepted = client.post(
                "/api/worker/actions/post_close_batch",
                json={},
                headers={"X-Optix-Action": "1", "Origin": bundle["base"]},
            )
            assert accepted.status_code == 202
            finished = _poll_action(client, accepted.json()["action_id"])
            assert finished.get("status") == "failed"
            assert (finished.get("result") or {}).get("outcome") == "failed"
            after = client.get("/api/strength/scan?top=5").json()
            assert after["publication_id"] == old_id
    finally:
        _stop(bundle)


def test_h03_not_published_is_waiting_not_success(fixture_dir):
    data_dir, fixture = fixture_dir
    old_id = fixture["publication"]["publication_id"]
    bundle = _spawn(data_dir, engine="not_published")
    try:
        with httpx.Client(base_url=bundle["base"], timeout=5.0) as client:
            accepted = client.post(
                "/api/worker/actions/post_close_batch",
                json={},
                headers={"X-Optix-Action": "1", "Origin": bundle["base"]},
            )
            assert accepted.status_code == 202
            finished = _poll_action(client, accepted.json()["action_id"])
            assert finished.get("status") == "completed"
            assert (finished.get("result") or {}).get("outcome") == "waiting_input"
            after = client.get("/api/strength/scan?top=5").json()
            assert after["publication_id"] == old_id
    finally:
        _stop(bundle)
