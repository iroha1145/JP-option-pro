"""データ側の縁のケース（doc §十二「数据」）。

半日立会・欠測日・銘柄ごとの取得失敗・週次と日次の頻度差。どれも
「例外は出ないが静かに結果が歪む」型なので、明示的に固定しておく。
"""

from __future__ import annotations

import pytest

from app.domain.constants import (
    EQUITY_TRADING_DIVISIONS,
    HOLIDAY_DIVISION_BUSINESS,
    HOLIDAY_DIVISION_HALF_DAY,
    HOLIDAY_DIVISION_HOLIDAY_TRADING,
)
from app.providers.intraday.contract import Quote
from app.repositories.core import CoreRepository
from app.services.radar.features import clean_series, compute_features_from_series
from app.services.radar.turnover_quality import turnover_stability


def _bar(date, price, *, turnover=8e8):
    return {
        "trade_date": date, "open": price, "high": price * 1.01, "low": price * 0.99,
        "close": price, "turnover_value": turnover, "volume": turnover / price,
        "adjustment_factor": 1.0, "upper_limit": 0,
    }


def _dates(count):
    return [f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(count)]


# ---------------------------------------------------------------------------
# 1. 半日立会
# ---------------------------------------------------------------------------


def test_half_day_is_a_trading_day_but_holiday_derivatives_day_is_not(tmp_path):
    """区分 "2"（半日立会）は現物の営業日、"3"（祝日取引）は **違う**。

    "3" は 2022-09-23 に始まったデリバティブの祝日取引で、現物株は立会しない
    （本番カレンダーに 62 日あり、いずれも 2022-09-23 以降）。名前が
    「取引」なので営業日に見えるが、これを混ぜると現物の営業日数が水増しされ、
    事件年齢も結果窓も 1 日ずつずれていく。
    """

    assert HOLIDAY_DIVISION_HALF_DAY == "2"
    assert HOLIDAY_DIVISION_HALF_DAY in EQUITY_TRADING_DIVISIONS
    assert HOLIDAY_DIVISION_BUSINESS in EQUITY_TRADING_DIVISIONS
    assert HOLIDAY_DIVISION_HOLIDAY_TRADING not in EQUITY_TRADING_DIVISIONS

    repo = CoreRepository(tmp_path / "core.db")
    repo.initialize()
    repo.upsert_trading_days([
        {"calendar_date": "2026-01-05", "holiday_division": "1"},   # 通常
        {"calendar_date": "2026-01-06", "holiday_division": "2"},   # 半日立会
        {"calendar_date": "2026-01-07", "holiday_division": "0"},   # 休場
        {"calendar_date": "2026-01-08", "holiday_division": "3"},   # 祝日取引（現物は休み）
        {"calendar_date": "2026-01-09", "holiday_division": "1"},
    ])
    days = repo.trading_days_between("2026-01-01", "2026-01-31")
    assert days == ["2026-01-05", "2026-01-06", "2026-01-09"]
    assert repo.is_trading_day("2026-01-06") is True     # 半日は営業日
    assert repo.is_trading_day("2026-01-07") is False
    assert repo.is_trading_day("2026-01-08") is False    # 祝日取引は現物の営業日ではない
    assert repo.is_trading_day("2026-01-20") is None     # カレンダーに無い


def test_half_day_low_turnover_is_not_mistaken_for_a_dead_stock():
    """半日は前場だけなので売買代金がおよそ半分。

    それを「商いが無い日」と数えると安定性スコアが不当に下がる。半日は
    年 6 日程度（本番 10 年で 62 日）なので、閾値との距離で吸収されること
    を確認する —— 流動性のある銘柄なら半日でも桁が違う。
    """

    normal = [1.0e9] * 58
    half_days = [5.0e8, 5.0e8]          # 半日 = おおむね半分
    assert turnover_stability(normal + half_days) > 90.0


# ---------------------------------------------------------------------------
# 2. 欠測日・穴
# ---------------------------------------------------------------------------


def test_missing_sessions_are_skipped_not_interpolated():
    """売買が成立しなかった日を前日値で埋めない（偽の平坦さを作らない）。"""

    dates = _dates(60)
    bars = [_bar(date, 100.0 + index * 0.5) for index, date in enumerate(dates)]
    for index in (10, 11, 12):
        bars[index]["close"] = None      # 取引成立なし

    series = clean_series(bars)
    assert series is not None
    assert len(series["closes"]) == len(dates) - 3
    assert dates[10] not in series["dates"]


def test_a_broken_bar_is_dropped_rather_than_repaired():
    """high < low のような壊れたバーは捨てる（推測で直さない）。"""

    dates = _dates(60)
    bars = [_bar(date, 100.0) for date in dates]
    bars[20].update(high=50.0, low=150.0)     # 明らかに壊れている

    series = clean_series(bars)
    assert series is not None
    assert dates[20] not in series["dates"]


def test_too_few_bars_yields_no_features_rather_than_a_guess():
    bars = [_bar(date, 100.0) for date in _dates(10)]
    assert clean_series(bars) is None
    # 欠測を渡しても落ちない（clean_series → compute の連結が自然な書き方なので）
    assert compute_features_from_series(None) is None


# ---------------------------------------------------------------------------
# 3. 銘柄単位の取得失敗が全体を巻き込まない
# ---------------------------------------------------------------------------


def test_one_failing_symbol_does_not_break_the_batch(monkeypatch):
    """1 銘柄が取れなくても、残りの気配は返ること。

    取れなかった銘柄は **結果に入らない**（古い値で埋めない）。呼び出し側は
    「無い」を見て公式終値のまま表示できる。
    """

    from app.services import intraday_quotes as service

    class _PartialProvider:
        name = "partial"
        delay_class = "delayed"
        is_official = False
        is_realtime = False

        def status(self):
            from app.providers.intraday.contract import ProviderStatus

            return ProviderStatus(
                name=self.name, available=True, delay_class=self.delay_class,
                is_official=False, is_realtime=False, delay_minutes=15,
            )

        def quotes_for_codes(self, codes):
            # 72030 だけ取れて、9984 は落ちたことにする
            return {
                code: Quote(key=code, price=1000.0, source=self.name)
                for code in codes if code == "72030"
            }

        def index_quotes(self):
            return {}

    monkeypatch.setattr(service, "select_provider", lambda: _PartialProvider())
    found = service.fetch_quotes_blocking(["72030", "99840"])

    assert set(found) == {"72030"}
    assert "99840" not in found, "取れなかった銘柄を埋めている"


def test_an_empty_code_list_does_not_call_the_provider(monkeypatch):
    from app.services import intraday_quotes as service

    calls = []
    monkeypatch.setattr(
        service, "select_provider", lambda: calls.append(1) or (_ for _ in ()).throw(AssertionError)
    )
    assert service.fetch_quotes_blocking([]) == {}
    assert calls == [], "空リストでプロバイダを呼んでいる"


def test_duplicate_codes_are_requested_once(monkeypatch):
    from app.services import intraday_quotes as service

    seen: list[list[str]] = []

    class _Recorder:
        name = "rec"
        delay_class = "delayed"
        is_official = False
        is_realtime = False

        def status(self):
            from app.providers.intraday.contract import ProviderStatus

            return ProviderStatus(
                name=self.name, available=True, delay_class="delayed",
                is_official=False, is_realtime=False,
            )

        def quotes_for_codes(self, codes):
            seen.append(list(codes))
            return {}

        def index_quotes(self):
            return {}

    monkeypatch.setattr(service, "select_provider", lambda: _Recorder())
    service.fetch_quotes_blocking(["72030", "72030", "99840", "72030"])
    assert seen == [["72030", "99840"]]


# ---------------------------------------------------------------------------
# 4. 週次と日次で更新頻度が違うデータ
# ---------------------------------------------------------------------------


def test_weekly_margin_and_daily_alerts_keep_their_own_dates(tmp_path):
    """信用残（週次）と日々公表（日次）は別の鮮度を持つ。

    片方の最新日でもう片方を「新しい」と判定すると、週次が 1 週間古いのに
    新鮮だと誤認する（またはその逆で毎日過期扱いになる）。
    """

    repo = CoreRepository(tmp_path / "core.db")
    repo.initialize()
    repo.upsert_margin_alerts([
        {"canonical_code": "72030", "published_date": "2026-07-31",
         "application_date": "2026-07-31", "tse_regulation_class": "001",
         "publish_reason": "PrecautionByJSF"},
    ])
    repo.upsert_margin_interest([
        {"canonical_code": "72030", "application_date": "2026-07-24",
         "long_total": 1000.0, "short_total": 400.0},
    ])

    alert_date = repo.latest_margin_alert_date()
    alerts = repo.latest_margin_alert_map()
    interest = repo.latest_margin_map()

    assert alert_date == "2026-07-31"
    assert alerts["72030"]["application_date"] == "2026-07-31"
    # 週次側は自分の申込日を保持していること（日次の日付で上書きされない）
    assert interest["72030"]["application_date"] == "2026-07-24"


def test_regulation_map_is_empty_when_nothing_is_published(tmp_path):
    repo = CoreRepository(tmp_path / "core.db")
    repo.initialize()
    assert repo.latest_margin_alert_map() == {}
    assert repo.latest_margin_alert_date() is None
