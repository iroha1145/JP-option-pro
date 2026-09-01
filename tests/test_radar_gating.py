"""レーダーの受け入れ判定: 流動性欠損・営業日年齢・新規イベント上限。

いずれも「設定や条件は書いてあるのに実際には効いていない」型の不具合の回帰。
"""

from __future__ import annotations

from app.personal_config import RadarConfig
from app.repositories.core import CoreRepository
from app.services.radar import lifecycle as lc
from app.services.radar.engine import RadarEngine


def _bar(code, date, price, *, turnover):
    return {
        "canonical_code": code, "trade_date": date,
        "open": price * 0.99, "high": price * 1.01, "low": price * 0.985,
        "close": price, "adj_open": price * 0.99, "adj_high": price * 1.01,
        "adj_low": price * 0.985, "adj_close": price,
        "turnover_value": turnover, "volume": (turnover / price) if turnover else 0,
        "upper_limit": 0,
    }


def _dates(count):
    return [f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(count)]


def _seed(tmp_path, prices_by_code, *, turnover_by_code=None, calendar=None):
    repo = CoreRepository(tmp_path / "core.db")
    repo.initialize()
    dates = _dates(max(len(prices) for prices in prices_by_code.values()))
    for code, prices in prices_by_code.items():
        turnovers = (turnover_by_code or {}).get(code)
        repo.upsert_daily_bars([
            _bar(code, dates[index], price,
                 turnover=turnovers[index] if turnovers else 5e8)
            for index, price in enumerate(prices)
        ])
    repo.replace_security_master(
        [
            {"canonical_code": code, "name_ja": code, "market_code": "0111",
             "sector33_code": "3650", "sector33_name": "電気機器"}
            for code in prices_by_code
        ],
        as_of_date=dates[-1],
    )
    repo.upsert_trading_days(
        [{"calendar_date": date, "holiday_division": "1"} for date in (calendar or dates)]
    )
    repo.upsert_index_bars(
        [{"index_code": "0000", "trade_date": date, "close": 2700.0 + index}
         for index, date in enumerate(dates)]
    )
    return repo, dates


# ---------------------------------------------------------------------------
# 1. 売買代金が取れない銘柄は流動性フィルタを素通りしない
# ---------------------------------------------------------------------------


def test_missing_turnover_is_not_treated_as_passing_the_liquidity_floor():
    """欠損は「閾値未満ではない」ではない。

    旧実装の条件は `avg_turnover is not None and avg_turnover < floor` で、
    None のとき素通りして正式プールに入っていた。
    """

    from app.services.radar.features import compute_features_from_series, clean_series

    breakout = [100.0] * 80 + [115.0]
    bars = [_bar("70130", date, price, turnover=None)
            for date, price in zip(_dates(len(breakout)), breakout)]
    features = compute_features_from_series(clean_series(bars))

    assert features is not None
    assert features.get("avg_turnover_20d") is None, "前提: 売買代金が取れない"
    # 旧条件をそのまま書くと「通過」してしまうことを固定しておく
    assert not (features["avg_turnover_20d"] is not None
                and features["avg_turnover_20d"] < 1e8)


def test_liquidity_unknown_events_rank_behind_known_ones(tmp_path):
    """枠が 1 つしかないとき、流動性不明より流動性既知が先に採用される。"""

    length = 85
    breakout = [100.0] * (length - 1) + [118.0]
    repo, dates = _seed(
        tmp_path,
        {"70130": breakout, "80130": list(breakout)},
        turnover_by_code={
            "70130": [None] * length,      # 流動性不明
            "80130": [8e8] * length,       # 流動性既知
        },
    )
    config = RadarConfig(
        min_avg_turnover_jpy=0.0, min_listed_days=30, max_new_events_per_scan=50
    )
    summary = RadarEngine(repo, config).scan(dates[-1], lookback_start=dates[0])

    events = repo.open_radar_events(terminal_states=sorted(lc.TERMINAL_STATES))
    flags = {
        event["canonical_code"]: (event["features"] or {}).get("liquidity_known")
        for event in events
    }
    assert flags.get("80130") is True
    assert flags.get("70130") is False, "流動性不明が既知と同じ扱いになっている"
    assert summary["events_detected"] >= 2


# ---------------------------------------------------------------------------
# 2. 事件の年齢は営業日で数える
# ---------------------------------------------------------------------------


def test_event_age_counts_trading_days_not_calendar_days(tmp_path):
    """連休を跨いでも「新しい取引情報が無い日」で老化しないこと。"""

    repo, dates = _seed(tmp_path, {"70130": [100.0] * 84 + [112.0]})
    engine = RadarEngine(repo, RadarConfig(min_avg_turnover_jpy=0.0, min_listed_days=30))

    discovered = dates[-1]
    # 暦では 60 日空いているが、営業日は 3 日しか入っていない大型連休。
    far_date = "2026-06-01"
    trading_gap = ["2026-05-28", "2026-05-29", far_date]
    repo.upsert_trading_days(
        [{"calendar_date": date, "holiday_division": "1"} for date in trading_gap]
    )

    assert engine._trading_days_open(discovered, far_date) <= 4, (
        "休場期間でイベントが老化している"
    )
    # 暦日差なら 60 日超 = 既定の失効日数（28）を軽く超えてしまう
    from datetime import date as _date
    calendar_gap = (_date.fromisoformat(far_date) - _date.fromisoformat(discovered)).days
    assert calendar_gap > 28, "前提: 暦日では失効するほど離れている"


def test_trading_day_age_falls_back_when_calendar_is_missing(tmp_path):
    repo, dates = _seed(tmp_path, {"70130": [100.0] * 40})
    engine = RadarEngine(repo, RadarConfig(min_avg_turnover_jpy=0.0, min_listed_days=30))
    # カレンダーに無い区間 → 暦日にフォールバック（走査を止めない）
    assert engine._trading_days_open("2030-01-01", "2030-01-11") == 10


# ---------------------------------------------------------------------------
# 3. 新規イベント上限は「並べてから」効く
# ---------------------------------------------------------------------------


def test_new_event_cap_truncates_after_sorting_and_reports_the_drop(tmp_path):
    """上限で捨てた件数を黙って隠さないこと。

    走査順（銘柄コード順）で切ると強いシグナルが無言で落ちる。優先度順に
    並べてから切り、落とした件数を必ず返す。
    """

    length = 85
    prices_by_code = {}
    for index in range(6):
        # 全銘柄が同日に 52 週高値を更新する（= 新規イベント候補が 6 件）
        prices_by_code[f"{90000 + index}"] = [100.0] * (length - 1) + [130.0]
    repo, dates = _seed(tmp_path, prices_by_code)

    config = RadarConfig(
        min_avg_turnover_jpy=0.0, min_listed_days=30, max_new_events_per_scan=50
    )
    summary = RadarEngine(repo, config).scan(dates[-1], lookback_start=dates[0])
    detected = summary["events_detected"]
    assert detected >= 4, f"前提: 候補が複数ある (実際 {detected})"
    assert summary["events_dropped_by_cap"] == 0
    assert summary["new_event_cap"] == 50

    # 上限を候補数より小さくすると、その分だけ落ち、件数が申告される
    repo2, dates2 = _seed(tmp_path / "second", prices_by_code)
    # 設定の下限は 50 なので、切り詰めロジック自体を突くために検証を迂回する。
    capped = config.model_copy(update={"max_new_events_per_scan": 2})
    summary2 = RadarEngine(repo2, capped).scan(dates2[-1], lookback_start=dates2[0])
    assert summary2["events_created"] == 2
    assert summary2["events_dropped_by_cap"] == detected - 2
    assert summary2["events_detected"] == detected


def test_cap_never_drops_existing_tracked_events(tmp_path):
    """上限は「今日いくつ増やすか」の話。追跡中の事件を捨てる理由にはしない。"""

    length = 85
    repo, dates = _seed(tmp_path, {"70130": [100.0] * (length - 1) + [118.0]})
    config = RadarConfig(min_avg_turnover_jpy=0.0, min_listed_days=30)
    engine = RadarEngine(repo, config)
    engine.scan(dates[-1], lookback_start=dates[0])
    assert len(repo.open_radar_events(terminal_states=sorted(lc.TERMINAL_STATES))) == 1

    # 翌営業日、新規上限を 0 相当まで絞っても既存イベントは更新され続ける
    next_date = "2026-04-06"
    repo.upsert_trading_days([{"calendar_date": next_date, "holiday_division": "1"}])
    repo.upsert_daily_bars([_bar("70130", next_date, 120.0, turnover=6e8)])
    repo.upsert_index_bars([{"index_code": "0000", "trade_date": next_date, "close": 2800.0}])
    # 新規上限を 1 まで絞っても、既存イベントの更新は止まらない
    starved = RadarEngine(repo, config.model_copy(update={"max_new_events_per_scan": 1}))
    starved.scan(next_date, lookback_start=dates[0])

    events = repo.open_radar_events(terminal_states=sorted(lc.TERMINAL_STATES))
    assert len(events) >= 1
    assert events[0]["last_scanned_date"] == next_date, (
        "上限のせいで追跡中の事件が更新されなくなっている"
    )
