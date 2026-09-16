"""Playwright E2E against a real FastAPI + fixture publication + production frontend."""

from __future__ import annotations

import json
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


def _force_diverging_champions(data_dir: Path, fixture: dict) -> None:
    from app.repositories.core import CoreRepository
    from app.services.radar.t1_priority import T1_MET

    repo = CoreRepository(data_dir / "jp-core.db")
    trade_date = str(fixture.get("target_date") or "")
    with repo.write() as connection:
        rows = connection.execute(
            "SELECT canonical_code FROM strength_rows ORDER BY intrinsic_score DESC, canonical_code"
        ).fetchall()
        codes = [row[0] for row in rows]
        if len(codes) >= 2:
            production = codes[0]
            a0 = codes[1]
            connection.execute(
                "UPDATE strength_rows SET intrinsic_score=99.0, score_mid=10.0, score_long=10.0 WHERE canonical_code=?",
                (production,),
            )
            connection.execute(
                "UPDATE strength_rows SET intrinsic_score=11.0, score_mid=98.0, score_long=97.0 WHERE canonical_code=?",
                (a0,),
            )
        scan = connection.execute(
            "SELECT data_through FROM sync_state WHERE dataset='radar_scan'"
        ).fetchone()
        scan_date = (scan[0] if scan else None) or trade_date
        connection.execute("DELETE FROM radar_events")
        events = [
            (
                "evt-prod-lead",
                codes[0] if codes else "72030",
                "high_break_60",
                99.0,
                scan_date,
            ),
            (
                "evt-t1-lead",
                codes[1] if len(codes) > 1 else "99840",
                "base_breakout",
                12.0,
                scan_date,
            ),
        ]
        now = "2026-03-16T09:00:00Z"
        for event_id, code, signal, priority, day in events:
            connection.execute(
                """
                INSERT INTO radar_events(
                    event_id, canonical_code, signal_type, state, discovered_date,
                    pivot_price, trigger_price, state_changed_date, last_scanned_date,
                    alert_priority, scores_json, features_json, transitions_json,
                    created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event_id, code, signal, "triggered", day, 100, 105, day, day, priority,
                    "{}",
                    json.dumps({
                        "t1_anchor": {
                            "event_id": event_id,
                            "session_date": day,
                            "resistance_high": 100,
                            "data_convention": "jp_adj_ohlcv_v1",
                            "version": 1,
                            "source": "first_publish",
                        }
                    }) if signal == "base_breakout" else "{}",
                    "[]", now, now,
                ),
            )
        connection.execute(
            """
            INSERT OR REPLACE INTO radar_t1_current(event_id, eval_version, identity_hash, status, first_known_at, published_at)
            VALUES(?,?,?,?,?,?)
            """,
            ("evt-t1-lead", 1, "browser-t1", T1_MET, now, now),
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO radar_t1_evaluations(
                event_id, eval_version, identity_hash, status, first_known_at,
                known_at, computed_at, published_at, payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                "evt-t1-lead", 1, "browser-t1", T1_MET, now, now, now, now,
                json.dumps({
                    "status": T1_MET,
                    "identity_hash": "browser-t1",
                    "clv": 0.8,
                    "rvol_daily_20med": 2.2,
                    "upper_shadow_ratio": 0.1,
                    "breakout_distance_atr": 2.5,
                    "eval_version": 1,
                    "computed_at": now,
                    "known_at": now,
                }),
            ),
        )
        if "radar_t1_anchors" in {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }:
            connection.execute(
                """
                INSERT OR IGNORE INTO radar_t1_anchors(
                    event_id, session_date, platform_id, resistance_high,
                    data_convention, version, source, created_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                ("evt-t1-lead", scan_date, None, 100, "jp_adj_ohlcv_v1", 1, "first_publish", now),
            )
    repo.record_sync_success("radar_scan", data_through=scan_date)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def live_app(tmp_path_factory):
    from app.tools.dev_fixture import build_fixture

    data_dir = tmp_path_factory.mktemp("a0-t1-browser")
    fixture = build_fixture(str(data_dir), days=320)
    _force_diverging_champions(data_dir, fixture)
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
    assert production.json()["rows"][0]["canonical_code"] != body["rows"][0]["canonical_code"]
    assert body["publication_id"] == production.json()["publication_id"]
    radar_prod = httpx.get(f"{live_app['base']}/api/radar/current?sort_algorithm=production&limit=5", timeout=10)
    radar_t1 = httpx.get(f"{live_app['base']}/api/radar/current?sort_algorithm=t1&limit=5", timeout=10)
    assert radar_prod.json()["events"][0]["event_id"] != radar_t1.json()["events"][0]["event_id"]


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
        production_first = httpx.get(
            f"{live_app['base']}/api/strength/scan?top=5&ranking_algorithm=production", timeout=10
        ).json()["rows"][0]["canonical_code"]
        a0_first = httpx.get(
            f"{live_app['base']}/api/strength/scan?top=5&ranking_algorithm=a0", timeout=10
        ).json()["rows"][0]["canonical_code"]
        radar_prod = httpx.get(
            f"{live_app['base']}/api/radar/current?sort_algorithm=production&limit=5", timeout=10
        ).json()["events"][0]
        radar_t1 = httpx.get(
            f"{live_app['base']}/api/radar/current?sort_algorithm=t1&limit=5", timeout=10
        ).json()["events"][0]
        assert production_first != a0_first
        assert radar_prod["event_id"] != radar_t1["event_id"]

        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            reduced_motion="reduce",
            locale="ja-JP",
        )
        context.add_init_script("localStorage.setItem('optixjp:locale', 'ja');")
        page = context.new_page()
        console_errors = []
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        first_row = page.locator("[data-testid=screener-first-row]").first
        page.goto(f"{live_app['base']}/screener", wait_until="networkidle")
        page.get_by_role("heading", name="銘柄スキャン").wait_for()
        first_row.wait_for()
        prod_code = first_row.get_attribute("data-canonical-code")
        assert prod_code == production_first
        page.get_by_role("tab", name="A0 中長期").click()
        page.get_by_test_id("screener-apply-filters").click()
        page.get_by_test_id("screener-algorithm-status").wait_for()
        status = page.get_by_test_id("screener-algorithm-status").inner_text()
        assert "a0_mid_long" in status
        assert page.get_by_test_id("screener-a0-unavailable").count() == 0
        page.wait_for_function(
            "code => document.querySelector('[data-testid=screener-first-row]')?.getAttribute('data-canonical-code') === code",
            arg=a0_first,
        )
        assert first_row.get_attribute("data-canonical-code") == a0_first
        stored = page.evaluate(
            """() => {
              const out = {};
              for (const key of Object.keys(localStorage)) {
                if (key.includes('algorithmPreferences')) {
                  out[key] = JSON.parse(localStorage.getItem(key) || 'null');
                }
              }
              return out;
            }"""
        )
        assert any(
            (value or {}).get("screenerRankingAlgorithm") == "a0_mid_long"
            for value in stored.values()
        ), stored
        page.screenshot(path=str(artifacts / "screener-a0-1440.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.locator("[data-testid=screener-first-row]").nth(1).get_attribute("data-canonical-code") == a0_first
        page.screenshot(path=str(artifacts / "screener-a0-390.png"))

        page.goto(f"{live_app['base']}/radar", wait_until="networkidle")
        page.get_by_test_id("radar-first-event").wait_for()
        assert page.get_by_test_id("radar-first-event").get_attribute("data-event-id") == radar_prod["event_id"]
        page.get_by_role("tab", name="T1 日足優先").click()
        page.wait_for_function(
            "id => document.querySelector('[data-testid=radar-first-event]')?.getAttribute('data-event-id') === id",
            arg=radar_t1["event_id"],
        )
        assert page.get_by_test_id("radar-first-event").get_attribute("data-event-id") == radar_t1["event_id"]
        page.screenshot(path=str(artifacts / "radar-t1-390.png"))

        page.set_viewport_size({"width": 1440, "height": 900})
        stored_after_radar = page.evaluate(
            """() => {
              const out = {};
              for (const key of Object.keys(localStorage)) {
                if (key.includes('algorithmPreferences')) {
                  out[key] = JSON.parse(localStorage.getItem(key) || 'null');
                }
              }
              return out;
            }"""
        )
        scan_urls = []
        page.on("request", lambda request: scan_urls.append(request.url) if "strength/scan" in request.url else None)
        page.goto(f"{live_app['base']}/screener", wait_until="networkidle")
        page.get_by_test_id("screener-algorithm-status").wait_for()
        stored_after_remount = page.evaluate(
            """() => {
              const out = {};
              for (const key of Object.keys(localStorage)) {
                if (key.includes('algorithmPreferences')) {
                  out[key] = JSON.parse(localStorage.getItem(key) || 'null');
                }
              }
              return out;
            }"""
        )
        status_text = page.get_by_test_id("screener-algorithm-status").inner_text()
        assert "a0_mid_long" in status_text, (
            f"status={status_text!r} after_radar={stored_after_radar!r} "
            f"after_remount={stored_after_remount!r} scans={scan_urls!r}"
        )
        page.wait_for_function(
            "code => document.querySelector('[data-testid=screener-first-row]')?.getAttribute('data-canonical-code') === code",
            arg=a0_first,
        )
        assert page.locator("[data-testid=screener-first-row]").first.get_attribute("data-canonical-code") == a0_first

        page.route(
            "**/api/view-preferences",
            lambda route: route.fulfill(status=503, content_type="application/json", body='{"code":"unavailable"}')
            if route.request.method == "PUT"
            else route.continue_(),
        )
        page.get_by_role("tab", name="従来の総合").click()
        page.get_by_test_id("screener-apply-filters").click()
        page.get_by_test_id("screener-pref-unsynced").wait_for()
        page.wait_for_function(
            "code => document.querySelector('[data-testid=screener-first-row]')?.getAttribute('data-canonical-code') === code",
            arg=production_first,
        )
        unexplained = [
            item
            for item in console_errors
            if "favicon" not in item.lower()
            and "503" not in item
            and "service unavailable" not in item.lower()
        ]
        assert unexplained == []
        browser.close()
