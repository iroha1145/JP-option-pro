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


# ---------------------------------------------------------------------------
# 5. 全市場スキャンの入力に必要な列が揃っているか
# ---------------------------------------------------------------------------


def test_scan_input_carries_raw_ohlc_and_the_adjustment_factor(tmp_path):
    """`bars_matrix_since` が high/low/adjustment_factor を返すこと。

    ここが欠けると例外は出ず、静かに壊れる:
      * high/low 欠落 → clean_series の欠測フォールバックで high=low=close。
        ATR が日中レンジを失い、prior_high_N が「終値の高値」になって
        ピボットが本来より低くなる ＝ 突破が実際より出やすくなる。
      * adjustment_factor 欠落 → 分割・併合の調整が一切効かない。
    本番では adj_* が全行 NULL なので、生の列が唯一の情報源になる。
    """

    repo = CoreRepository(tmp_path / "core.db")
    repo.initialize()
    repo.upsert_daily_bars([{
        "canonical_code": "72030", "trade_date": "2026-07-31",
        "open": 3000.0, "high": 3200.0, "low": 2950.0, "close": 3100.0,
        "adjustment_factor": 0.5, "turnover_value": 1e9, "volume": 1e6,
        "upper_limit": 0,
    }])

    bars = repo.bars_matrix_since("2026-07-01")["72030"]
    for column in ("open", "high", "low", "close", "adjustment_factor"):
        assert column in bars[0], f"{column} がスキャン入力から欠けている"
    assert bars[0]["high"] == 3200.0
    assert bars[0]["adjustment_factor"] == 0.5


def test_scan_input_does_not_collapse_high_low_into_close(tmp_path):
    """実データ経路で high/low が close に潰れないこと（回帰）。"""

    repo = CoreRepository(tmp_path / "core.db")
    repo.initialize()
    dates = _dates(40)
    repo.upsert_daily_bars([
        {"canonical_code": "72030", "trade_date": date,
         "open": 100.0, "high": 108.0, "low": 96.0, "close": 100.0,
         "adjustment_factor": 1.0, "turnover_value": 8e8, "volume": 8e6,
         "upper_limit": 0}
        for date in dates
    ])
    series = clean_series(repo.bars_matrix_since(dates[0])["72030"])
    assert series is not None
    assert series["highs"] != series["closes"], "high が close に潰れている"
    assert max(series["highs"]) == 108.0
    assert min(series["lows"]) == 96.0


def test_latest_quote_map_computes_change_even_without_stored_adjusted_close(tmp_path):
    """前日比が adj_close の有無に依存しないこと。

    本番では adj_close が全行 NULL なので、adj_close だけを見る実装だと
    change_pct が **4,444 銘柄すべてで None** になっていた（決算カレンダーの
    騰落欄が全部空）。生値でも計算できること。
    """

    repo = CoreRepository(tmp_path / "core.db")
    repo.initialize()
    repo.upsert_daily_bars([
        {"canonical_code": "72030", "trade_date": "2026-07-30", "close": 3000.0,
         "open": 3000.0, "high": 3010.0, "low": 2990.0, "adjustment_factor": 1.0,
         "turnover_value": 1e9, "volume": 1e6, "upper_limit": 0},
        {"canonical_code": "72030", "trade_date": "2026-07-31", "close": 3150.0,
         "open": 3100.0, "high": 3160.0, "low": 3090.0, "adjustment_factor": 1.0,
         "turnover_value": 1e9, "volume": 1e6, "upper_limit": 0},
    ])
    quotes = repo.latest_quote_map()
    assert quotes["72030"]["change_pct"] == pytest.approx(5.0)


def test_latest_quote_map_does_not_show_a_split_as_a_crash(tmp_path):
    """分割当日に前日の生値と比べると −50% の下落に見える。"""

    repo = CoreRepository(tmp_path / "core.db")
    repo.initialize()
    repo.upsert_daily_bars([
        {"canonical_code": "76780", "trade_date": "2026-07-29", "close": 6330.0,
         "open": 6300.0, "high": 6350.0, "low": 6280.0, "adjustment_factor": 1.0,
         "turnover_value": 1e9, "volume": 1e6, "upper_limit": 0},
        # 1:2 分割。生値では 6330 → 3035 だが、実質は −4.1%
        {"canonical_code": "76780", "trade_date": "2026-07-30", "close": 3035.0,
         "open": 3100.0, "high": 3120.0, "low": 3020.0, "adjustment_factor": 0.5,
         "turnover_value": 1e9, "volume": 2e6, "upper_limit": 0},
    ])
    change = repo.latest_quote_map()["76780"]["change_pct"]
    assert change == pytest.approx(-4.1, abs=0.2), f"分割が {change}% の下落として出ている"


# ---------------------------------------------------------------------------
# 5. 空売り残高の日次取り込み
# ---------------------------------------------------------------------------


def test_short_position_rest_endpoint_requires_a_code():
    """日付範囲だけの REST 問い合わせはもう組み立てないこと。

    `/markets/short-sale-report` は `code` 必須で、`disc_date_from`/`disc_date_to`
    だけだと 400（実測）。この形の呼び出しが残っていると、増分取り込みは
    毎回失敗するのに「バックフィル済みのデータがある」ので画面は動いて見える。
    """

    import pathlib

    source = pathlib.Path(
        pathlib.Path(__file__).resolve().parents[1]
        / "backend/app/services/jquants_sync.py"
    ).read_text(encoding="utf-8")
    # 説明のための言及ではなく、実際の呼び出し（辞書リテラルのキー）を見る。
    assert '"disc_date_from"' not in source, (
        "code 無しの日付範囲クエリが残っている（実測で 400 を返す）"
    )
    assert "'disc_date_from'" not in source


def test_bulk_file_date_parses_daily_files_and_skips_monthly():
    from app.services.jquants_sync import _bulk_file_date

    daily = "markets/short-sale-report/live/markets_short-sale-report_20260803.csv.gz"
    monthly = "markets/short-sale-report/historical/2026/markets_short-sale-report_202607.csv.gz"
    assert _bulk_file_date(daily) == "2026-08-03"
    assert _bulk_file_date(monthly) is None      # 月次は日次取り込みの対象外
    assert _bulk_file_date("garbage") is None


def test_nothing_to_do_is_not_reported_as_a_successful_fetch():
    """取りに行っていない日を "ok" と名乗らない。

    以前は `start > target_date` で `status="ok", rows=0` を返しており、
    取り込みが壊れていても同期状態は成功のまま見えていた。
    """

    import pathlib

    source = pathlib.Path(
        pathlib.Path(__file__).resolve().parents[1]
        / "backend/app/services/jquants_sync.py"
    ).read_text(encoding="utf-8")
    marker = 'return SyncResult(\n                    dataset=DATASET_SHORT_POSITIONS, status="up_to_date"'
    assert marker in source, "何もしていない日が ok を名乗っている"


# ---------------------------------------------------------------------------
# 6. 空売り残高の集計（合計に何を足すか）
# ---------------------------------------------------------------------------


def _sp(holder, calc, ratio, prev=None, disc=None, shares=None):
    return {
        "holder_name": holder, "calculated_date": calc,
        "disclosed_date": disc or calc, "short_position_ratio": ratio,
        "previous_ratio": prev, "short_position_shares": shares,
    }


def test_total_excludes_holders_who_fell_below_the_threshold():
    """0.5% 割れの最終報告を合計に足さない。

    3905 の実データで言うと Barclays 0.40%・Jump 0.42%・UBS 0.43%・
    JPM 0.34%・Citigroup 0.49% … を足すと 4.64% になるが、これらは全て
    「0.5% を割ったので以後報告しません」という最終報告で、実際の建玉は
    その値以下のどこか（とっくにゼロかもしれない）。足すと居ない売り方を
    数えることになる。
    """

    from app.services import short_interest as si

    rows = [
        _sp("モルガン", "2026-07-31", 0.0123),
        _sp("Barclays", "2026-07-30", 0.0040, 0.0051),   # 義務消失
        _sp("Jump", "2026-07-17", 0.0042, 0.0055),       # 義務消失
        _sp("UBS", "2026-06-18", 0.0043),                # 義務消失（古い）
        _sp("Nomura", "2025-11-07", 0.0),                # 解消
    ]
    summary = si.summarise(rows)
    assert summary.reporting_total == pytest.approx(0.0123), "閾値割れを合計に混ぜている"
    assert summary.reporting_holders == 1
    assert summary.below_threshold_holders == 3
    assert summary.closed_holders == 1


def test_position_as_of_uses_the_last_report_before_the_date():
    """残高報告はイベント駆動。その日の断面は存在しないので再構成する。"""

    from app.services import short_interest as si

    rows = [
        _sp("A", "2026-07-31", 0.0123),
        _sp("A", "2026-07-16", 0.0076),
        _sp("B", "2026-07-10", 0.0060),
    ]
    at_month_end = si.positions_as_of(rows, "2026-07-31")
    mid_july = si.positions_as_of(rows, "2026-07-20")
    assert at_month_end["A"] == pytest.approx(0.0123)
    assert mid_july["A"] == pytest.approx(0.0076), "その日より後の報告を使っている"
    assert mid_july["B"] == pytest.approx(0.0060)


def test_corrections_take_the_newer_disclosure_for_the_same_calc_date():
    from app.services import short_interest as si

    rows = [
        _sp("A", "2026-07-31", 0.0100, disc="2026-08-03"),
        _sp("A", "2026-07-31", 0.0123, disc="2026-08-04"),   # 訂正
    ]
    assert si.positions_as_of(rows)["A"] == pytest.approx(0.0123)


def test_every_report_in_the_window_is_listed_not_aggregated():
    """同じ保有者が窓の中で 3 回報告したら 3 行出す。

    保有者単位で差し引きすると「いつ何が起きたか」が読めなくなる。
    """

    from app.services import short_interest as si

    rows = [
        _sp("A", "2026-07-30", 0.0040, 0.0051),
        _sp("A", "2026-07-29", 0.0051, 0.0077),
        _sp("A", "2026-07-23", 0.0077, 0.0089),
        _sp("A", "2026-07-01", 0.0089, 0.0098),   # 窓の外
    ]
    changes = si.changes_within(rows, since="2026-07-20")
    assert len(changes) == 3, "窓の中の報告を集約している"
    assert [c["calculated_date"] for c in changes] == [
        "2026-07-30", "2026-07-29", "2026-07-23",
    ]
    assert changes[0]["delta"] == pytest.approx(-0.0011)
    assert changes[0]["kind"] == si.MOVE_BELOW_THRESHOLD


def test_change_kinds_are_distinguished():
    from app.services import short_interest as si

    rows = [
        _sp("new", "2026-07-30", 0.0060, 0.0),          # 新規
        _sp("closed", "2026-07-30", 0.0, 0.0057),       # 解消
        _sp("down", "2026-07-30", 0.0070, 0.0090),      # 減
        _sp("up", "2026-07-30", 0.0090, 0.0070),        # 増
        _sp("below", "2026-07-30", 0.0040, 0.0051),     # 義務消失
    ]
    kinds = {c["holder_name"]: c["kind"] for c in si.changes_within(rows, since="2026-07-01")}
    assert kinds["new"] == si.MOVE_NEW
    assert kinds["closed"] == si.MOVE_CLOSED
    assert kinds["down"] == si.MOVE_DECREASED
    assert kinds["up"] == si.MOVE_INCREASED
    assert kinds["below"] == si.MOVE_BELOW_THRESHOLD


def test_share_total_counts_the_same_holders_as_the_ratio_total():
    """株数合計も「報告義務中」だけ。閾値割れの株数を混ぜない。

    比率で足さないと決めたものを株数では足す、が一番ありがちなズレ方。
    """

    from app.services import short_interest as si

    rows = [
        _sp("モルガン", "2026-07-31", 0.0123, shares=395_600),
        _sp("Barclays", "2026-07-30", 0.0040, 0.0051, shares=131_200),  # 義務消失
        _sp("Nomura", "2025-11-07", 0.0, shares=0),                     # 解消
    ]
    summary = si.summarise(rows)
    assert summary.reporting_shares == pytest.approx(395_600), "閾値割れの株数を足している"
    assert summary.reporting_total == pytest.approx(0.0123)


def test_share_total_is_withheld_when_any_reporting_holder_lacks_shares():
    """欠損を 0 として足すと、合計が黙って小さく出る。出さない方を選ぶ。"""

    from app.services import short_interest as si

    rows = [
        _sp("A", "2026-07-31", 0.0123, shares=395_600),
        _sp("B", "2026-07-31", 0.0080, shares=None),
    ]
    summary = si.summarise(rows)
    assert summary.reporting_shares is None
    assert summary.reporting_total == pytest.approx(0.0203), "比率の合計まで巻き添えにしている"


def test_changes_carry_the_share_count():
    from app.services import short_interest as si

    rows = [_sp("A", "2026-07-30", 0.0040, 0.0051, shares=131_200)]
    change = si.changes_within(rows, since="2026-07-20")[0]
    assert change["shares"] == pytest.approx(131_200)


def test_window_change_compares_reporting_totals_only():
    from app.services import short_interest as si

    rows = [
        _sp("A", "2026-07-31", 0.0123),      # 新規（窓の中）
        _sp("B", "2026-07-30", 0.0040, 0.0051),  # 義務消失（窓の中）
        _sp("B", "2026-07-10", 0.0051),      # 窓の外の状態
    ]
    summary = si.summarise(rows, baseline_date="2026-07-20")
    assert summary.baseline_total == pytest.approx(0.0051)   # B のみ報告義務中
    assert summary.reporting_total == pytest.approx(0.0123)  # A のみ報告義務中
    assert summary.change == pytest.approx(0.0072)
