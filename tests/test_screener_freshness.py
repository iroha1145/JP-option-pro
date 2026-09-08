"""JP-01/02/03: cleaned input dates, coverage, and publication outcomes.

These tests import production modules only. They must fail on the old
behavior (yesterday's bars labeled as today's target date; partial pools
replacing complete snapshots; record_sync_success after a zero write).
"""

from __future__ import annotations

from app.personal_config import RadarConfig
from app.providers.jquants.mapping import map_daily_bar
from app.repositories.core import CoreRepository
from app.services.publication import (
    OUTCOME_ALREADY_CURRENT,
    OUTCOME_PUBLISHED,
    OUTCOME_RETAINED,
    OUTCOME_WAITING_INPUT,
    classify_equity_input,
    clip_rows_through,
    evaluate_freshness,
    expected_trade_date,
)
from app.services.radar.engine import RadarEngine
from app.services.radar.features import MIN_BARS_FOR_FEATURES
from app.services.strength_scan import STRENGTH_SCORE_VERSION, build_strength_rows
from app.worker.tasks import TaskContext, _run_radar_and_screener


def _bar(code: str, day: str, close: float | None, **extra) -> dict:
    high = extra.pop("high", close * 1.01 if close else None)
    low = extra.pop("low", close * 0.99 if close else None)
    open_ = extra.pop("open", close)
    return {
        "canonical_code": code,
        "trade_date": day,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "adj_open": open_,
        "adj_high": high,
        "adj_low": low,
        "adj_close": close,
        "turnover_value": extra.pop("turnover_value", 5e8),
        "volume": 1e6,
        "upper_limit": 0,
        **extra,
    }


def _history(code: str, last_day: str, n: int = 80, last_close: float = 100.0) -> list[dict]:
    """Build n-1 prior bars plus last_day. Dates count backwards in calendar days."""

    year, month, day = (int(part) for part in last_day.split("-"))
    rows = []
    closes = [last_close - (n - 1 - i) * 0.1 for i in range(n)]
    # Simple unique increasing dates ending at last_day.
    from datetime import date, timedelta

    end = date(year, month, day)
    for index in range(n):
        current = end - timedelta(days=n - 1 - index)
        rows.append(_bar(code, current.isoformat(), closes[index]))
    return rows


def _seed(tmp_path, codes: list[str], last_day: str, *, last_bars: dict[str, dict] | None = None):
    repo = CoreRepository(tmp_path / "core.db")
    repo.initialize()
    master = []
    all_dates: set[str] = set()
    for code in codes:
        bars = _history(code, last_day)
        if last_bars and code in last_bars:
            bars[-1] = {**bars[-1], **last_bars[code]}
        repo.upsert_daily_bars(bars)
        all_dates.update(bar["trade_date"] for bar in bars)
        master.append(
            {
                "canonical_code": code,
                "name_ja": code,
                "market_code": "0111",
                "sector33_code": "3650",
                "sector33_name": "電気機器",
            }
        )
    repo.replace_security_master(master, as_of_date=last_day)
    repo.upsert_trading_days(
        [{"calendar_date": day, "holiday_division": "1"} for day in sorted(all_dates)]
    )
    for day in sorted(all_dates):
        repo.upsert_index_bars([{"index_code": "0000", "trade_date": day, "close": 2700.0}])
    return repo


def _config(**overrides) -> RadarConfig:
    values = dict(min_avg_turnover_jpy=0.0, min_listed_days=30, market_codes=("0111",))
    values.update(overrides)
    return RadarConfig(**values)


def test_a01_valid_last_bar_uses_target_date(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-08")
    engine = RadarEngine(repo, _config())
    summary = engine.scan("2026-09-08", lookback_start="2026-01-01")
    assert summary["coverage"]["valid"] == 1
    assert summary["coverage"]["allows_complete_publish"] is True
    features = summary["features_by_code"]["72030"]
    assert features["trade_date"] == "2026-09-08"
    rows = build_strength_rows(
        trade_date="2026-09-08",
        features_by_code=summary["features_by_code"],
        structure_by_code=summary["structure_by_code"],
        securities={"72030": repo.get_security("72030")},
        topix_return_63d=None,
    )
    assert rows[0]["trade_date"] == "2026-09-08"


def test_a02_empty_close_via_vendor_mapping_does_not_label_yesterday_as_today(tmp_path):
    mapped = map_daily_bar(
        {
            "Date": "2026-09-08",
            "Code": "72030",
            "O": 100,
            "H": 110,
            "L": 90,
            "C": "",
            "Vo": 1000,
            "Va": 100000,
            "AdjC": "",
            "AdjO": 100,
            "AdjH": 110,
            "AdjL": 90,
        }
    )
    assert mapped is not None and mapped["close"] is None

    repo = _seed(tmp_path, ["72030"], "2026-09-08")
    repo.upsert_daily_bars([mapped])
    engine = RadarEngine(repo, _config())
    before = repo.open_radar_events(terminal_states=["failed", "expired"])
    summary = engine.scan("2026-09-08", lookback_start="2026-01-01")
    assert "72030" not in summary["features_by_code"]
    assert summary["coverage"]["invalid"] == 1
    assert summary["coverage"]["allows_complete_publish"] is False
    assert summary["persist_events"] is False
    after = repo.open_radar_events(terminal_states=["failed", "expired"])
    assert len(after) == len(before)


def test_a03_bad_high_low_is_rechecked_after_clean(tmp_path):
    repo = _seed(
        tmp_path,
        ["72030"],
        "2026-09-08",
        last_bars={"72030": {"high": 90.0, "low": 110.0, "close": 100.0, "adj_high": 90.0, "adj_low": 110.0}},
    )
    engine = RadarEngine(repo, _config())
    summary = engine.scan("2026-09-08", lookback_start="2026-01-01")
    assert summary["coverage"]["invalid"] == 1
    assert "72030" not in summary["features_by_code"]


def test_a04_non_finite_and_short_history(tmp_path):
    repo = _seed(
        tmp_path,
        ["72030"],
        "2026-09-08",
        last_bars={"72030": {"close": float("nan"), "adj_close": float("nan")}},
    )
    engine = RadarEngine(repo, _config())
    summary = engine.scan("2026-09-08", lookback_start="2026-01-01")
    assert summary["coverage"]["invalid"] == 1
    short = [_bar("1", f"2026-09-{i:02d}", 100.0) for i in range(1, 6)]
    bucket, _, reason = classify_equity_input(short, "2026-09-05", min_feature_bars=MIN_BARS_FOR_FEATURES)
    assert bucket == "excluded" and reason == "insufficient_history"


def test_a05_future_bars_are_clipped_for_replay():
    rows = [
        _bar("1", "2026-09-07", 100.0),
        _bar("1", "2026-09-08", 101.0),
        _bar("1", "2026-09-09", 102.0),
    ]
    clipped = clip_rows_through(rows, "2026-09-08")
    assert [row["trade_date"] for row in clipped] == ["2026-09-07", "2026-09-08"]


def test_a07_stale_index_is_recorded(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-08")
    with repo.write() as connection:
        connection.execute("DELETE FROM index_bars WHERE trade_date = '2026-09-08'")
    engine = RadarEngine(repo, _config())
    summary = engine.scan("2026-09-08", lookback_start="2026-01-01")
    assert summary["coverage"]["index_stale"] is True
    assert summary["coverage"]["index_input_date"] != "2026-09-08"


def test_b03_partial_same_day_retains_complete_publication(tmp_path):
    repo = _seed(tmp_path, ["72030", "67580", "99840"], "2026-09-07")
    engine = RadarEngine(repo, _config())
    first = engine.scan("2026-09-07", lookback_start="2026-01-01")
    rows = build_strength_rows(
        trade_date="2026-09-07",
        features_by_code=first["features_by_code"],
        structure_by_code=first["structure_by_code"],
        securities={code: repo.get_security(code) for code in first["features_by_code"]},
        topix_return_63d=None,
    )
    published = repo.replace_strength_rows(
        rows,
        trade_date="2026-09-07",
        regime={"label": "ok"},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=first["coverage"],
        input_fingerprint=first["input_fingerprint"],
        input_data_through="2026-09-07",
    )
    assert published.outcome == OUTCOME_PUBLISHED
    assert published.rows_written == 3

    # Only one name has 2026-09-08.
    repo.upsert_daily_bars(_history("72030", "2026-09-08")[-1:])
    repo.upsert_index_bars([{"index_code": "0000", "trade_date": "2026-09-08", "close": 2710.0}])
    repo.upsert_trading_days([{"calendar_date": "2026-09-08", "holiday_division": "1"}])
    second = engine.scan("2026-09-08", lookback_start="2026-01-01")
    assert second["coverage"]["valid"] == 1
    assert second["coverage"]["unknown_missing"] == 2
    assert second["coverage"]["allows_complete_publish"] is False
    retained = repo.replace_strength_rows(
        build_strength_rows(
            trade_date="2026-09-08",
            features_by_code=second["features_by_code"],
            structure_by_code=second["structure_by_code"],
            securities={code: repo.get_security(code) for code in second["features_by_code"]},
            topix_return_63d=None,
        ),
        trade_date="2026-09-08",
        regime={"label": "partial"},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=second["coverage"],
        input_fingerprint=second["input_fingerprint"],
        input_data_through="2026-09-08",
        today="2026-09-08",
    )
    assert retained.outcome == OUTCOME_RETAINED
    assert repo.strength_meta()["trade_date"] == "2026-09-07"
    assert len(repo.strength_rows_all()) == 3
    assert repo.sync_state("strength_snapshot") is None or (
        repo.sync_state("strength_snapshot") or {}
    ).get("data_through") != "2026-09-08"


def test_b01_shorter_view_is_not_a_coverage_failure(tmp_path):
    repo = _seed(tmp_path, ["72030", "67580"], "2026-09-08")
    engine = RadarEngine(repo, _config())
    summary = engine.scan("2026-09-08", lookback_start="2026-01-01")
    assert summary["coverage"]["allows_complete_publish"] is True
    # Business filter that drops one name still leaves complete *input*.
    tight = RadarEngine(repo, _config(min_avg_turnover_jpy=1e18))
    filtered = tight.scan("2026-09-08", lookback_start="2026-01-01")
    assert filtered["coverage"]["valid"] == 2
    assert filtered["coverage"]["filtered"] == 2
    assert filtered["coverage"]["allows_complete_publish"] is True
    assert filtered["features_by_code"] == {}


def test_c01_empty_write_does_not_advance_sync_success(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-07")
    engine = RadarEngine(repo, _config())
    first = engine.scan("2026-09-07", lookback_start="2026-01-01")
    pub = repo.replace_strength_rows(
        build_strength_rows(
            trade_date="2026-09-07",
            features_by_code=first["features_by_code"],
            structure_by_code=first["structure_by_code"],
            securities={"72030": repo.get_security("72030")},
            topix_return_63d=None,
        ),
        trade_date="2026-09-07",
        regime={},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=first["coverage"],
        input_fingerprint=first["input_fingerprint"],
        input_data_through="2026-09-07",
    )
    repo.record_sync_success("strength_snapshot", rows_total=pub.rows_written, data_through="2026-09-07")
    empty = repo.replace_strength_rows([], trade_date="2026-09-08", regime={})
    assert empty.outcome == OUTCOME_RETAINED
    assert repo.strength_meta()["trade_date"] == "2026-09-07"
    assert repo.sync_state("strength_snapshot")["data_through"] == "2026-09-07"


def test_c08_identical_inputs_are_already_current(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-08")
    engine = RadarEngine(repo, _config())
    summary = engine.scan("2026-09-08", lookback_start="2026-01-01")
    rows = build_strength_rows(
        trade_date="2026-09-08",
        features_by_code=summary["features_by_code"],
        structure_by_code=summary["structure_by_code"],
        securities={"72030": repo.get_security("72030")},
        topix_return_63d=None,
    )
    first = repo.replace_strength_rows(
        rows,
        trade_date="2026-09-08",
        regime={"x": 1},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=summary["coverage"],
        input_fingerprint=summary["input_fingerprint"],
        input_data_through="2026-09-08",
    )
    second = repo.replace_strength_rows(
        rows,
        trade_date="2026-09-08",
        regime={"x": 1},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=summary["coverage"],
        input_fingerprint=summary["input_fingerprint"],
        input_data_through="2026-09-08",
    )
    assert first.outcome == OUTCOME_PUBLISHED
    assert second.outcome == OUTCOME_ALREADY_CURRENT
    assert second.publication_id == first.publication_id
    assert second.built_at == first.built_at


def test_c06_older_input_cannot_overwrite_newer(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-08")
    engine = RadarEngine(repo, _config())
    summary = engine.scan("2026-09-08", lookback_start="2026-01-01")
    rows = build_strength_rows(
        trade_date="2026-09-08",
        features_by_code=summary["features_by_code"],
        structure_by_code=summary["structure_by_code"],
        securities={"72030": repo.get_security("72030")},
        topix_return_63d=None,
    )
    repo.replace_strength_rows(
        rows,
        trade_date="2026-09-08",
        regime={},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=summary["coverage"],
        input_fingerprint=summary["input_fingerprint"],
        input_data_through="2026-09-08",
    )
    older = engine.scan("2026-09-07", lookback_start="2026-01-01")
    older_rows = build_strength_rows(
        trade_date="2026-09-07",
        features_by_code=older["features_by_code"],
        structure_by_code=older["structure_by_code"],
        securities={"72030": repo.get_security("72030")},
        topix_return_63d=None,
    )
    result = repo.replace_strength_rows(
        older_rows,
        trade_date="2026-09-07",
        regime={},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=older["coverage"],
        input_fingerprint=older["input_fingerprint"],
        input_data_through="2026-09-07",
        today="2026-09-08",
    )
    assert result.outcome == OUTCOME_RETAINED
    assert repo.strength_meta()["trade_date"] == "2026-09-08"


def test_run_radar_waiting_when_no_target_bars(tmp_path, monkeypatch):
    repo = _seed(tmp_path, ["72030"], "2026-09-07")

    class _Ctx:
        config = type(
            "C",
            (),
            {
                "features": type("F", (), {"radar_enabled": True})(),
                "radar": _config(),
            },
        )()
        repository = repo

    result = _run_radar_and_screener(_Ctx(), "2026-09-08")
    assert result["outcome"] == OUTCOME_WAITING_INPUT
    assert result["reason"] == "bars_not_current"
    state = repo.sync_state("strength_snapshot")
    assert state is not None
    assert state.get("last_success_at") is None
    assert state.get("data_through") is None


def test_g02_expected_trade_date_uses_configured_boundary():
    days = {"2026-09-07": "2026-09-07", "2026-09-08": "2026-09-08"}

    def latest(day: str) -> str:
        return days[day]

    from datetime import datetime
    from zoneinfo import ZoneInfo

    jst = ZoneInfo("Asia/Tokyo")
    before = expected_trade_date(
        today="2026-09-08",
        now=datetime(2026, 9, 8, 16, 50, tzinfo=jst),
        batch_hhmm="17:00",
        latest_trading_day=latest,
    )
    after = expected_trade_date(
        today="2026-09-08",
        now=datetime(2026, 9, 8, 17, 0, tzinfo=jst),
        batch_hhmm="17:00",
        latest_trading_day=latest,
    )
    late_boundary = expected_trade_date(
        today="2026-09-08",
        now=datetime(2026, 9, 8, 17, 30, tzinfo=jst),
        batch_hhmm="17:45",
        latest_trading_day=latest,
    )
    assert before == "2026-09-07"
    assert after == "2026-09-08"
    assert late_boundary == "2026-09-07"


def test_a06_missing_print_is_unknown_not_inferred_halt():
    rows = [_bar("72030", "2026-09-04", 100.0)]
    bucket, _, reason = classify_equity_input(
        rows, "2026-09-05", min_feature_bars=MIN_BARS_FOR_FEATURES
    )
    assert bucket == "unknown_missing"
    assert "halt" not in reason


def test_a08_same_day_correction_is_a_new_publication(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-08")
    engine = RadarEngine(repo, _config())
    first_scan = engine.scan("2026-09-08", lookback_start="2026-01-01")
    first_rows = build_strength_rows(
        trade_date="2026-09-08",
        features_by_code=first_scan["features_by_code"],
        structure_by_code=first_scan["structure_by_code"],
        securities={"72030": repo.get_security("72030")},
        topix_return_63d=None,
    )
    first = repo.replace_strength_rows(
        first_rows,
        trade_date="2026-09-08",
        regime={},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=first_scan["coverage"],
        input_fingerprint=first_scan["input_fingerprint"],
        input_data_through="2026-09-08",
    )
    repo.upsert_daily_bars([_bar("72030", "2026-09-08", 123.4)])
    second_scan = engine.scan("2026-09-08", lookback_start="2026-01-01")
    second = repo.replace_strength_rows(
        build_strength_rows(
            trade_date="2026-09-08",
            features_by_code=second_scan["features_by_code"],
            structure_by_code=second_scan["structure_by_code"],
            securities={"72030": repo.get_security("72030")},
            topix_return_63d=None,
        ),
        trade_date="2026-09-08",
        regime={},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=second_scan["coverage"],
        input_fingerprint=second_scan["input_fingerprint"],
        input_data_through="2026-09-08",
    )
    assert first.outcome == OUTCOME_PUBLISHED
    assert second.outcome == OUTCOME_PUBLISHED
    assert second.publication_id != first.publication_id
    assert second_scan["input_fingerprint"] != first_scan["input_fingerprint"]


def test_b04_coverage_sees_names_outside_the_top_n(tmp_path):
    repo = _seed(tmp_path, ["72030", "67580", "99840"], "2026-09-07")
    engine = RadarEngine(repo, _config())
    first = engine.scan("2026-09-07", lookback_start="2026-01-01")
    repo.replace_strength_rows(
        build_strength_rows(
            trade_date="2026-09-07",
            features_by_code=first["features_by_code"],
            structure_by_code=first["structure_by_code"],
            securities={code: repo.get_security(code) for code in first["features_by_code"]},
            topix_return_63d=None,
        ),
        trade_date="2026-09-07",
        regime={},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=first["coverage"],
        input_fingerprint=first["input_fingerprint"],
        input_data_through="2026-09-07",
    )
    repo.upsert_daily_bars(_history("72030", "2026-09-08")[-1:])
    repo.upsert_index_bars([{"index_code": "0000", "trade_date": "2026-09-08", "close": 2710.0}])
    repo.upsert_trading_days([{"calendar_date": "2026-09-08", "holiday_division": "1"}])
    second = engine.scan("2026-09-08", lookback_start="2026-01-01")
    assert second["coverage"]["expected"] == 3
    assert second["coverage"]["valid"] == 1
    assert second["coverage"]["unknown_missing"] == 2
    assert second["coverage"]["allows_complete_publish"] is False


def test_b07_empty_input_does_not_wipe_or_advance_success(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-07")
    engine = RadarEngine(repo, _config())
    first = engine.scan("2026-09-07", lookback_start="2026-01-01")
    pub = repo.replace_strength_rows(
        build_strength_rows(
            trade_date="2026-09-07",
            features_by_code=first["features_by_code"],
            structure_by_code=first["structure_by_code"],
            securities={"72030": repo.get_security("72030")},
            topix_return_63d=None,
        ),
        trade_date="2026-09-07",
        regime={},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=first["coverage"],
        input_fingerprint=first["input_fingerprint"],
        input_data_through="2026-09-07",
    )
    repo.record_sync_success("strength_snapshot", rows_total=pub.rows_written, data_through="2026-09-07")
    empty = repo.replace_strength_rows([], trade_date="2026-09-08", regime={})
    assert empty.outcome == OUTCOME_RETAINED
    assert repo.strength_meta()["publication_id"] == pub.publication_id
    assert repo.sync_state("strength_snapshot")["data_through"] == "2026-09-07"


def test_b08_empty_universe_is_not_a_complete_publish(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-08")
    empty_engine = RadarEngine(repo, _config(market_codes=("0112",)))
    summary = empty_engine.scan("2026-09-08", lookback_start="2026-01-01")
    assert summary["coverage"]["expected"] == 0
    assert summary["coverage"]["allows_complete_publish"] is False


def test_c04_exception_before_commit_rolls_back(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-07")
    engine = RadarEngine(repo, _config())
    first = engine.scan("2026-09-07", lookback_start="2026-01-01")
    published = repo.replace_strength_rows(
        build_strength_rows(
            trade_date="2026-09-07",
            features_by_code=first["features_by_code"],
            structure_by_code=first["structure_by_code"],
            securities={"72030": repo.get_security("72030")},
            topix_return_63d=None,
        ),
        trade_date="2026-09-07",
        regime={},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=first["coverage"],
        input_fingerprint=first["input_fingerprint"],
        input_data_through="2026-09-07",
    )
    try:
        with repo.write() as connection:
            connection.execute("DELETE FROM strength_rows")
            connection.execute(
                "UPDATE strength_meta SET trade_date='2026-09-08', publication_id='pub_half'"
            )
            raise RuntimeError("crash before commit")
    except RuntimeError:
        raised = True
    else:
        raised = False
    assert raised
    rows, meta = repo.strength_snapshot()
    assert meta["publication_id"] == published.publication_id
    assert meta["trade_date"] == "2026-09-07"
    assert len(rows) == 1


def test_c05_restart_after_receipt_loss_is_already_current(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-08")
    engine = RadarEngine(repo, _config())
    summary = engine.scan("2026-09-08", lookback_start="2026-01-01")
    rows = build_strength_rows(
        trade_date="2026-09-08",
        features_by_code=summary["features_by_code"],
        structure_by_code=summary["structure_by_code"],
        securities={"72030": repo.get_security("72030")},
        topix_return_63d=None,
    )
    first = repo.replace_strength_rows(
        rows,
        trade_date="2026-09-08",
        regime={},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=summary["coverage"],
        input_fingerprint=summary["input_fingerprint"],
        input_data_through="2026-09-08",
    )
    # 提交后回执丢失：重启只看真实发布凭证，不得再造一个新 publication_id。
    again = repo.replace_strength_rows(
        rows,
        trade_date="2026-09-08",
        regime={},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=summary["coverage"],
        input_fingerprint=summary["input_fingerprint"],
        input_data_through="2026-09-08",
    )
    assert again.outcome == OUTCOME_ALREADY_CURRENT
    assert again.publication_id == first.publication_id
    assert again.built_at == first.built_at


def test_c07_unusable_previous_does_not_block_recovery(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-08")
    engine = RadarEngine(repo, _config())
    summary = engine.scan("2026-09-08", lookback_start="2026-01-01")
    rows = build_strength_rows(
        trade_date="2026-09-08",
        features_by_code=summary["features_by_code"],
        structure_by_code=summary["structure_by_code"],
        securities={"72030": repo.get_security("72030")},
        topix_return_63d=None,
    )
    repo.replace_strength_rows(
        rows,
        trade_date="2026-09-08",
        regime={},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=summary["coverage"],
        input_fingerprint=summary["input_fingerprint"],
        input_data_through="2026-09-08",
    )
    with repo.write() as connection:
        connection.execute("UPDATE strength_meta SET publication_id = NULL, trade_date = '2099-01-01'")
    recovered = repo.replace_strength_rows(
        rows,
        trade_date="2026-09-08",
        regime={},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=summary["coverage"],
        input_fingerprint="recovery-fingerprint",
        input_data_through="2026-09-08",
        today="2026-09-08",
    )
    assert recovered.outcome == OUTCOME_PUBLISHED
    assert repo.strength_meta()["trade_date"] == "2026-09-08"
    assert repo.strength_meta()["publication_id"]


def test_g04_weekend_uses_last_jp_session():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    def latest(day: str) -> str | None:
        return {
            "2026-09-04": "2026-09-04",
            "2026-09-05": "2026-09-04",
            "2026-09-06": "2026-09-04",
        }.get(day)

    jst = ZoneInfo("Asia/Tokyo")
    saturday = expected_trade_date(
        today="2026-09-05",
        now=datetime(2026, 9, 5, 17, 30, tzinfo=jst),
        batch_hhmm="17:00",
        latest_trading_day=latest,
    )
    assert saturday == "2026-09-04"


def test_g05_missing_calendar_is_unknown():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    unknown = expected_trade_date(
        today="2026-09-08",
        now=datetime(2026, 9, 8, 17, 30, tzinfo=ZoneInfo("Asia/Tokyo")),
        batch_hhmm="17:00",
        latest_trading_day=lambda _day: None,
    )
    assert unknown is None


def test_r06_stale_calendar_gap_is_unknown_not_long_holiday():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    def latest(day: str) -> str | None:
        return "2026-07-31" if day >= "2026-07-31" else None

    def status(day: str) -> bool | None:
        return True if day == "2026-07-31" else None

    expected = expected_trade_date(
        today="2026-09-08",
        now=datetime(2026, 9, 8, 17, 30, tzinfo=ZoneInfo("Asia/Tokyo")),
        batch_hhmm="17:00",
        latest_trading_day=latest,
        session_status=status,
    )
    assert expected is None
    freshness = evaluate_freshness(
        stored_trade_date="2026-07-31",
        expected=expected,
        stored_score_version=STRENGTH_SCORE_VERSION,
        current_score_version=STRENGTH_SCORE_VERSION,
        coverage={"allows_complete_publish": True},
    )
    assert freshness["freshness"] == "unknown"


def test_r06_known_weekend_keeps_previous_session():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    def latest(day: str) -> str | None:
        return {
            "2026-09-04": "2026-09-04",
            "2026-09-05": "2026-09-04",
        }.get(day)

    def status(day: str) -> bool | None:
        return False if day == "2026-09-05" else True

    saturday = expected_trade_date(
        today="2026-09-05",
        now=datetime(2026, 9, 5, 17, 30, tzinfo=ZoneInfo("Asia/Tokyo")),
        batch_hhmm="17:00",
        latest_trading_day=latest,
        session_status=status,
    )
    assert saturday == "2026-09-04"


def test_r06_incomplete_coverage_is_partial_not_current():
    freshness = evaluate_freshness(
        stored_trade_date="2026-09-08",
        expected="2026-09-08",
        stored_score_version=STRENGTH_SCORE_VERSION,
        current_score_version=STRENGTH_SCORE_VERSION,
        coverage={"allows_complete_publish": False},
    )
    assert freshness["freshness"] == "partial"


def test_r06_index_stale_is_degraded_not_current():
    freshness = evaluate_freshness(
        stored_trade_date="2026-09-08",
        expected="2026-09-08",
        stored_score_version=STRENGTH_SCORE_VERSION,
        current_score_version=STRENGTH_SCORE_VERSION,
        coverage={"allows_complete_publish": True, "index_stale": True},
    )
    assert freshness["freshness"] == "degraded"
    assert freshness["index_stale"] is True


def test_r02_same_close_turnover_correction_publishes(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-08", last_bars={"72030": {"turnover_value": 1e7}})
    engine = RadarEngine(repo, _config())
    first_scan = engine.scan("2026-09-08", lookback_start="2026-01-01")
    first = repo.replace_strength_rows(
        build_strength_rows(
            trade_date="2026-09-08",
            features_by_code=first_scan["features_by_code"],
            structure_by_code=first_scan["structure_by_code"],
            securities={"72030": repo.get_security("72030")},
            topix_return_63d=None,
        ),
        trade_date="2026-09-08",
        regime={},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=first_scan["coverage"],
        input_fingerprint=first_scan["input_fingerprint"],
        input_data_through="2026-09-08",
    )
    last = repo.bars_for_code("72030")[-1]
    repo.upsert_daily_bars(
        [
            {
                **last,
                "turnover_value": 9e8,
                "adj_close": last.get("close"),
            }
        ]
    )
    second_scan = engine.scan("2026-09-08", lookback_start="2026-01-01")
    second = repo.replace_strength_rows(
        build_strength_rows(
            trade_date="2026-09-08",
            features_by_code=second_scan["features_by_code"],
            structure_by_code=second_scan["structure_by_code"],
            securities={"72030": repo.get_security("72030")},
            topix_return_63d=None,
        ),
        trade_date="2026-09-08",
        regime={},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=second_scan["coverage"],
        input_fingerprint=second_scan["input_fingerprint"],
        input_data_through="2026-09-08",
    )
    assert first.outcome == OUTCOME_PUBLISHED
    assert second_scan["input_fingerprint"] != first_scan["input_fingerprint"]
    assert second.outcome == OUTCOME_PUBLISHED
    assert second.publication_id != first.publication_id


def test_r03_already_current_repairs_screener(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-08")

    class _Ctx:
        config = type(
            "C",
            (),
            {
                "features": type("F", (), {"radar_enabled": True})(),
                "radar": _config(),
            },
        )()
        repository = repo

    first = _run_radar_and_screener(_Ctx(), "2026-09-08")
    assert first["outcome"] == OUTCOME_PUBLISHED
    assert repo.screener_trade_date() == "2026-09-08"
    with repo.write() as connection:
        connection.execute("DELETE FROM screener_rows")
        connection.execute(
            "UPDATE sync_state SET data_through='2026-09-07' WHERE dataset='screener_snapshot'"
        )
    assert repo.screener_trade_date() is None
    second = _run_radar_and_screener(_Ctx(), "2026-09-08")
    assert second["outcome"] == OUTCOME_ALREADY_CURRENT
    assert second["status"] == "ok"
    assert second.get("screener_outcome") == OUTCOME_PUBLISHED
    assert repo.screener_trade_date() == "2026-09-08"
    assert repo.sync_state("screener_snapshot")["data_through"] == "2026-09-08"


def test_r03_screener_write_failure_is_repaired_next_round(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-08")
    original = repo.replace_screener_rows
    calls = {"n": 0}

    def flaky(rows):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("screener down")
        return original(rows)

    repo.replace_screener_rows = flaky  # type: ignore[method-assign]

    class _Ctx:
        config = type(
            "C",
            (),
            {
                "features": type("F", (), {"radar_enabled": True})(),
                "radar": _config(),
            },
        )()
        repository = repo

    first = _run_radar_and_screener(_Ctx(), "2026-09-08")
    assert first["status"] == "error"
    assert first["outcome"] == OUTCOME_PUBLISHED
    assert repo.screener_trade_date() is None
    second = _run_radar_and_screener(_Ctx(), "2026-09-08")
    assert second["outcome"] == OUTCOME_ALREADY_CURRENT
    assert second["status"] == "ok"
    assert repo.screener_trade_date() == "2026-09-08"
    assert calls["n"] == 2
