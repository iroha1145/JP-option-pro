"""レーダー: 検出・先読み禁止・ライフサイクル・同日再実行の冪等性。"""

from app.personal_config import RadarConfig
from app.repositories.core import CoreRepository
from app.services.radar import lifecycle as lc
from app.services.radar.engine import RadarEngine, detect_new_signal
from app.services.radar.features import compute_security_features
from app.services.radar.scoring import weighted_score


def _bars(prices, *, start_turnover=5e8, surge_last=None):
    bars = []
    for index, price in enumerate(prices):
        turnover = start_turnover
        if surge_last and index >= len(prices) - surge_last:
            turnover *= 4
        bars.append(
            {
                "trade_date": f"2026-{(index // 28) + 1:02d}-{(index % 28) + 1:02d}",
                "open": price * 0.99, "high": price * 1.01, "low": price * 0.985,
                "close": price, "adj_open": price * 0.99, "adj_high": price * 1.01,
                "adj_low": price * 0.985, "adj_close": price,
                "turnover_value": turnover, "volume": turnover / price, "upper_limit": 0,
            }
        )
    return bars


def test_prior_high_excludes_breakout_bar():
    """当日バーが自分の抵抗線に参加しない（先読み禁止の核心）。"""

    prices = [100.0] * 80 + [110.0]  # 最終日に高値更新
    features = compute_security_features(_bars(prices))
    assert features is not None
    assert features["prior_high_60"] <= 101.1  # 過去だけから計算
    detection = detect_new_signal(features)
    assert detection is not None
    signal, pivot = detection
    assert signal in ("high_break_60", "high_break_20")
    assert pivot < 110.0


def test_flat_series_produces_no_signal():
    features = compute_security_features(_bars([100.0] * 90))
    assert detect_new_signal(features) is None


def test_missing_component_renormalizes_not_neutral():
    result = weighted_score({"a": 80.0, "b": None}, {"a": 0.5, "b": 0.5})
    assert result.score == 80.0  # b は重みごと除外; 50 で埋めない
    assert result.confidence == 0.5
    assert "b" in result.missing


def test_all_missing_gives_none():
    result = weighted_score({"a": None}, {"a": 1.0})
    assert result.score is None
    assert result.status == "insufficient_data"


def _seed_market(tmp_path, prices_by_code):
    repo = CoreRepository(tmp_path / "core.db")
    repo.initialize()
    dates = None
    for code, prices in prices_by_code.items():
        bars = _bars(prices, surge_last=3)
        dates = [bar["trade_date"] for bar in bars]
        repo.upsert_daily_bars([{**bar, "canonical_code": code} for bar in bars])
    repo.replace_security_master(
        [
            {"canonical_code": code, "name_ja": code, "market_code": "0111",
             "sector33_code": "3650", "sector33_name": "電気機器"}
            for code in prices_by_code
        ],
        as_of_date=dates[-1],
    )
    repo.upsert_trading_days([{"calendar_date": date, "holiday_division": "1"} for date in dates])
    repo.upsert_index_bars(
        [{"index_code": "0000", "trade_date": date, "close": 2700.0 + i} for i, date in enumerate(dates)]
    )
    return repo, dates


def test_scan_creates_event_and_same_day_rescan_is_idempotent(tmp_path):
    up = [100.0 + i * 0.1 for i in range(84)] + [112.0]
    flat = [100.0] * 85
    repo, dates = _seed_market(tmp_path, {"70130": up, "99990": flat})
    config = RadarConfig(min_avg_turnover_jpy=0.0, min_listed_days=30)
    engine = RadarEngine(repo, config)

    first = engine.scan(dates[-1], lookback_start=dates[0])
    assert first["events_created"] == 1
    events = repo.open_radar_events(terminal_states=sorted(lc.TERMINAL_STATES))
    assert len(events) == 1
    event = events[0]
    assert event["canonical_code"] == "70130"
    assert event["state"] in (lc.STATE_TRIGGERED, lc.STATE_CONFIRMED)
    priority_first = event["alert_priority"]

    second = engine.scan(dates[-1], lookback_start=dates[0])
    assert second["events_created"] == 0  # 同日再実行はイベントを増やさない
    events_after = repo.open_radar_events(terminal_states=sorted(lc.TERMINAL_STATES))
    assert len(events_after) == 1
    assert events_after[0]["alert_priority"] == priority_first
    assert events_after[0]["transitions"] == event["transitions"]


def test_lifecycle_fail_on_break_below_pivot(tmp_path):
    up = [100.0] * 80 + [110.0]
    repo, dates = _seed_market(tmp_path, {"70130": up})
    config = RadarConfig(min_avg_turnover_jpy=0.0, min_listed_days=30)
    engine = RadarEngine(repo, config)
    engine.scan(dates[-1], lookback_start=dates[0])

    # 翌営業日: ピボットの 3% 下で大陰線 → failed
    crash_date = "2026-04-05"
    repo.upsert_trading_days([{"calendar_date": crash_date, "holiday_division": "1"}])
    pivot = repo.open_radar_events(terminal_states=sorted(lc.TERMINAL_STATES))[0]["pivot_price"]
    crash_price = pivot * 0.9
    repo.upsert_daily_bars(
        [{
            "canonical_code": "70130", "trade_date": crash_date,
            "open": crash_price, "high": crash_price * 1.01, "low": crash_price * 0.99,
            "close": crash_price, "adj_open": crash_price, "adj_high": crash_price * 1.01,
            "adj_low": crash_price * 0.99, "adj_close": crash_price,
            "turnover_value": 5e8, "volume": 1e6, "upper_limit": 0,
        }]
    )
    repo.upsert_index_bars([{"index_code": "0000", "trade_date": crash_date, "close": 2800.0}])
    engine.scan(crash_date, lookback_start=dates[0])
    all_events = repo.radar_events_for_code("70130")
    assert any(event["state"] == lc.STATE_FAILED for event in all_events)


def test_transition_table_rejects_illegal_moves():
    result = lc.transition(lc.STATE_WATCHING, lc.STATE_HOLDING, "impossible")
    assert not result.changed and result.reason == "transition_not_allowed"
    result = lc.transition(lc.STATE_FAILED, lc.STATE_TRIGGERED, "resurrect")
    assert not result.changed  # 終端状態から出られない
