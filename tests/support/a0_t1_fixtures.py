"""Shared constructors for A0/T1 production-path tests. No extracted clones."""

from __future__ import annotations

import importlib
from datetime import date, datetime, timedelta
from pathlib import Path

from app.domain.timeutil import JST
from app.repositories.core import CoreRepository
from app.services.algorithm_modes import A0_ALGORITHM, PRODUCTION_ALGORITHM
from app.services.publication import OUTCOME_PUBLISHED
from app.services.strength_scan import STRENGTH_SCORE_VERSION


SESSION = date(2026, 3, 16)  # Monday
SESSION_ISO = SESSION.isoformat()


def jst(hour: int, minute: int = 0, day: date | None = None) -> datetime:
    return datetime.combine(day or SESSION, datetime.min.time(), tzinfo=JST).replace(
        hour=hour, minute=minute
    )


def dense_calendar(start: date, end: date) -> list[dict[str, str]]:
    rows = []
    cursor = start
    while cursor <= end:
        rows.append(
            {
                "calendar_date": cursor.isoformat(),
                "holiday_division": "1" if cursor.weekday() < 5 else "0",
            }
        )
        cursor += timedelta(days=1)
    return rows


def seed_calendar(repo: CoreRepository, *, start: date, end: date) -> None:
    repo.upsert_trading_days(dense_calendar(start, end))


def init_repo(path: Path) -> CoreRepository:
    repo = CoreRepository(path)
    repo.initialize()
    seed_calendar(repo, start=date(2025, 1, 1), end=date(2026, 12, 31))
    return repo


def prior_weekdays(session: date, count: int) -> list[date]:
    days: list[date] = []
    cursor = session - timedelta(days=1)
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


def t1_bar(
    code: str,
    day: date | str,
    *,
    open_: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.0,
    volume: float = 1_000_000,
    turnover_value: float | None = None,
    adj_factor: float = 1.0,
) -> dict:
    trade_date = day.isoformat() if isinstance(day, date) else day
    return {
        "canonical_code": code,
        "trade_date": trade_date,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "adj_open": open_,
        "adj_high": high,
        "adj_low": low,
        "adj_close": close,
        "volume": volume,
        "adj_volume": volume,
        "turnover_value": turnover_value if turnover_value is not None else volume * close,
        "adjustment_factor": adj_factor,
        "upper_limit": 0,
    }


def met_session_bar(code: str, day: date | str = SESSION) -> dict:
    return t1_bar(code, day, open_=100.0, high=106.0, low=99.0, close=105.8, volume=2_000_000)


def history_plus_session(
    code: str,
    session: date = SESSION,
    *,
    session_bar: dict | None = None,
    prior_volume: float = 1_000_000,
) -> list[dict]:
    bars = [
        t1_bar(code, day, volume=prior_volume)
        for day in prior_weekdays(session, 20)
    ]
    bars.append(session_bar or met_session_bar(code, session))
    return bars


def insert_security(repo: CoreRepository, code: str, *, name: str | None = None) -> None:
    existing = []
    with repo.read() as connection:
        rows = connection.execute("SELECT * FROM securities WHERE active = 1").fetchall()
        existing = [dict(row) for row in rows]
    by_code = {item["canonical_code"]: item for item in existing}
    by_code[code] = {
        "canonical_code": code,
        "name_ja": name or code,
        "market_code": "0111",
        "sector33_code": "3650",
        "sector33_name": "電気機器",
    }
    repo.replace_security_master(list(by_code.values()), as_of_date=SESSION_ISO)


def insert_radar_event(
    repo: CoreRepository,
    *,
    event_id: str,
    code: str,
    signal_type: str = "base_breakout",
    discovered: str = SESSION_ISO,
    priority: float = 80.0,
    resistance_high: float | None = 100.0,
    state: str = "triggered",
    freeze_anchor: bool = True,
    last_scanned: str | None = None,
) -> None:
    features: dict = {}
    if resistance_high is not None:
        features["structure"] = {"base": {"resistance_high": resistance_high}}
        if freeze_anchor:
            features["t1_anchor"] = {
                "event_id": event_id,
                "session_date": discovered,
                "platform_id": None,
                "resistance_high": resistance_high,
                "data_convention": "jp_adj_ohlcv_v1",
                "version": 1,
                "source": "first_publish",
            }
    events = [
        {
            "event_id": event_id,
            "canonical_code": code,
            "signal_type": signal_type,
            "state": state,
            "discovered_date": discovered,
            "pivot_price": resistance_high,
            "trigger_price": (resistance_high or 0) + 5,
            "state_changed_date": discovered,
            "last_scanned_date": last_scanned or discovered,
            "alert_priority": priority,
            "scores": {"alert_priority": priority},
            "features": features,
        }
    ]
    repo.upsert_radar_events(events)
    if freeze_anchor and resistance_high is not None:
        repo.save_t1_anchors(events)
    repo.record_sync_success("radar_scan", data_through=last_scanned or discovered)


def publish_strength_rows(repo: CoreRepository, rows: list[dict], *, trade_date: str = SESSION_ISO):
    result = repo.replace_strength_rows(
        rows,
        trade_date=trade_date,
        regime={
            "score": 60,
            "label": "中立",
            "dims": {
                "index_trend": 60,
                "momentum": 60,
                "breadth": 60,
                "volume": 60,
                "risk_appetite": 60,
                "risk_on_spread": 60,
            },
        },
        score_version=STRENGTH_SCORE_VERSION,
        expected_trade_date=trade_date,
        input_data_through=trade_date,
        coverage={"allows_complete_publish": True, "expected": len(rows), "valid": len(rows)},
        input_fingerprint=f"a0-t1:{trade_date}:{len(rows)}",
        today=trade_date,
    )
    assert result.outcome == OUTCOME_PUBLISHED
    return result


def strength_row(
    code: str,
    *,
    intrinsic: float,
    mid: float | None,
    long: float | None,
    close: float = 1000.0,
    turnover: float = 5e8,
    sector: str = "3650",
) -> dict:
    return {
        "canonical_code": code,
        "trade_date": SESSION_ISO,
        "intrinsic_score": intrinsic,
        "confidence": 0.9,
        "score_short": 50.0,
        "score_mid": mid,
        "score_long": long,
        "trend_score": 50.0,
        "breakout_quality_score": 50.0,
        "price_action_score": 50.0,
        "close": close,
        "change_pct": 1.0,
        "avg_turnover_20d": turnover,
        "turnover_ratio": 1.0,
        "atr_pct": 2.0,
        "market_code": "0111",
        "sector33_code": sector,
        "details": {"name_ja": code, "sector33_name": "電気機器", "market_name": "プライム"},
    }


def diverging_pool() -> list[dict]:
    """Production champion 72030; A0 champion 99840; 67580 is outside production top-2."""

    return [
        strength_row("72030", intrinsic=95.0, mid=40.0, long=40.0, close=2000.0),
        strength_row("67580", intrinsic=88.0, mid=50.0, long=50.0, close=1500.0),
        strength_row("99840", intrinsic=55.0, mid=96.0, long=94.0, close=800.0),
        strength_row("83010", intrinsic=50.0, mid=90.0, long=88.0, close=700.0),
        strength_row("45020", intrinsic=40.0, mid=None, long=80.0, close=600.0),
    ]


def api_client(data_dir: Path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    import app.access as access_module
    import app.api.deps as deps
    import app.config as config_module
    import app.main as main_module

    deps.reset_dependencies_for_tests()
    config_module.reset_settings_for_tests()
    access_module.reset_access_runtime_for_tests()
    main_module = importlib.reload(main_module)

    class _Loopback:
        def __init__(self, inner):
            self._inner = inner

        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http":
                scope = {**scope, "client": ("127.0.0.1", 40001)}
            await self._inner(scope, receive, send)

    from starlette.testclient import TestClient

    return TestClient(_Loopback(main_module.app), base_url="http://testserver")


__all__ = [
    "A0_ALGORITHM",
    "PRODUCTION_ALGORITHM",
    "SESSION",
    "SESSION_ISO",
    "api_client",
    "diverging_pool",
    "history_plus_session",
    "init_repo",
    "insert_radar_event",
    "insert_security",
    "jst",
    "met_session_bar",
    "prior_weekdays",
    "publish_strength_rows",
    "seed_calendar",
    "strength_row",
    "t1_bar",
]
