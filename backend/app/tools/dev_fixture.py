"""ローカル開発・テスト用の合成データ生成器。

実 J-Quants には一切接続しない。決定論的な擬似乱数で「それらしい」
日本株ユニバースを作り、レーダー・スクリーナー断面まで構築する。

使い方:
    DATA_DIR=/tmp/jp-dev PYTHONPATH=. python -m app.tools.dev_fixture
"""

from __future__ import annotations

import argparse
import math
import random
from datetime import date, timedelta

from app.data_paths import get_data_paths
from app.personal_config import RadarConfig
from app.repositories.core import CoreRepository
from app.services.jquants_sync import (
    DATASET_DAILY_PRICES,
    DATASET_EARNINGS_CALENDAR,
    DATASET_FINANCIAL_SUMMARY,
    DATASET_INDEX_PRICES,
    DATASET_MARGIN_ALERTS,
    DATASET_MARGIN_INTEREST,
    DATASET_SECURITY_MASTER,
    DATASET_SHORT_POSITIONS,
    DATASET_SHORT_RATIO,
    DATASET_TRADING_CALENDAR,
)
from app.services.radar.engine import RadarEngine
from app.services.radar.lifecycle import TERMINAL_STATES
from app.services.screener import build_screener_rows

# (display_code, 名称, 33業種コード, 33業種名, 市場, 基準価格, 年率ドリフト)
FIXTURE_SECURITIES: tuple[tuple[str, str, str, str, str, float, float], ...] = (
    ("7203", "トヨタ自動車", "3700", "輸送用機器", "0111", 3200.0, 0.18),
    ("6758", "ソニーグループ", "3650", "電気機器", "0111", 13500.0, 0.25),
    ("8306", "三菱UFJフィナンシャル・グループ", "7050", "銀行業", "0111", 1750.0, 0.15),
    ("9984", "ソフトバンクグループ", "5250", "情報・通信業", "0111", 9800.0, 0.30),
    ("6861", "キーエンス", "3650", "電気機器", "0111", 68000.0, 0.12),
    ("8035", "東京エレクトロン", "3650", "電気機器", "0111", 26000.0, 0.42),
    ("6501", "日立製作所", "3650", "電気機器", "0111", 3900.0, 0.35),
    ("4063", "信越化学工業", "3200", "化学", "0111", 6200.0, 0.10),
    ("9101", "日本郵船", "5100", "海運業", "0111", 5100.0, -0.05),
    ("2914", "日本たばこ産業", "3050", "食料品", "0111", 4300.0, 0.08),
    ("7013", "IHI", "3600", "機械", "0111", 9200.0, 0.55),
    ("5803", "フジクラ", "3500", "非鉄金属", "0111", 6800.0, 0.60),
    ("4385", "メルカリ", "5250", "情報・通信業", "0113", 2100.0, -0.12),
    ("5253", "カバー", "5250", "情報・通信業", "0113", 2900.0, 0.20),
    ("285A", "キオクシアホールディングス", "3650", "電気機器", "0111", 3400.0, 0.45),
    ("7011", "三菱重工業", "3600", "機械", "0111", 2300.0, 0.50),
)


def _canonical(display: str) -> str:
    return display + "0" if len(display) == 4 else display


def trading_days(end: date, count: int) -> list[str]:
    days: list[str] = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    return list(reversed(days))


def build_fixture(data_dir: str | None = None, *, days: int = 320, end_date: date | None = None) -> dict:
    paths = get_data_paths(data_dir) if data_dir else get_data_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    repository = CoreRepository(paths.core_db)
    repository.initialize()

    end = end_date or date(2026, 7, 31)
    days_list = trading_days(end, days)
    target = days_list[-1]

    # 取引カレンダー（平日=営業日 + 前後の休日）
    calendar_rows = []
    cursor = date.fromisoformat(days_list[0]) - timedelta(days=7)
    final = date.fromisoformat(target) + timedelta(days=45)
    while cursor <= final:
        calendar_rows.append(
            {
                "calendar_date": cursor.isoformat(),
                "holiday_division": "1" if cursor.weekday() < 5 else "0",
            }
        )
        cursor += timedelta(days=1)
    repository.upsert_trading_days(calendar_rows)
    repository.record_sync_success(DATASET_TRADING_CALENDAR, rows_total=len(calendar_rows), data_through=final.isoformat())

    # マスタ
    master_rows = []
    for display, name, s33, s33_name, market, _base, _drift in FIXTURE_SECURITIES:
        master_rows.append(
            {
                "canonical_code": _canonical(display),
                "name_ja": name,
                "name_en": name,
                "sector17_code": "9",
                "sector17_name": "電機・精密" if s33 == "3650" else "その他",
                "sector33_code": s33,
                "sector33_name": s33_name,
                "scale_category": "TOPIX Large70",
                "market_code": market,
                "market_name": {"0111": "プライム", "0112": "スタンダード", "0113": "グロース"}[market],
                "margin_code": "1",
                "margin_name": "信用",
                "product_category": "1",
                "as_of_date": target,
            }
        )
    repository.replace_security_master(master_rows, as_of_date=target)
    repository.record_sync_success(DATASET_SECURITY_MASTER, rows_total=len(master_rows), data_through=target)

    # 日足: 幾何ブラウン運動 + 引け後ブレイク演出（末尾5営業日で 7013/5803/285A を高値更新させる）
    rng = random.Random(20260731)
    breakout_codes = {"70130", "58030", "285A0"}
    bar_rows = []
    for display, _name, _s33, _s33n, _mkt, base, drift in FIXTURE_SECURITIES:
        code = _canonical(display)
        price = base
        daily_drift = drift / 245.0
        volatility = 0.02 if drift < 0.4 else 0.028
        peak = price
        for index, day in enumerate(days_list):
            shock = rng.gauss(daily_drift, volatility)
            if code in breakout_codes and index >= len(days_list) - 5:
                shock = abs(shock) + 0.012  # 直近5日は強制的に上へ → 高値ブレイク
            price = max(1.0, price * (1.0 + shock))
            peak = max(peak, price)
            day_range = price * rng.uniform(0.008, 0.025)
            open_ = price * (1.0 + rng.uniform(-0.008, 0.008))
            high = max(open_, price) + day_range * rng.uniform(0.2, 0.6)
            low = min(open_, price) - day_range * rng.uniform(0.2, 0.6)
            volume = rng.uniform(0.8, 1.6) * 1_000_000
            if code in breakout_codes and index >= len(days_list) - 3:
                volume *= 3.2  # 出来高急増
            turnover = volume * price
            bar_rows.append(
                {
                    "canonical_code": code,
                    "trade_date": day,
                    "open": round(open_, 1), "high": round(high, 1),
                    "low": round(low, 1), "close": round(price, 1),
                    "upper_limit": 0, "lower_limit": 0,
                    "volume": round(volume), "turnover_value": round(turnover),
                    "adjustment_factor": 1.0,
                    "adj_open": round(open_, 1), "adj_high": round(high, 1),
                    "adj_low": round(low, 1), "adj_close": round(price, 1),
                    "adj_volume": round(volume),
                }
            )
    repository.upsert_daily_bars(bar_rows)
    repository.record_sync_success(
        DATASET_DAILY_PRICES, checkpoint={"last_synced_date": target},
        rows_total=len(bar_rows), data_through=target,
    )

    # 指数（TOPIX ほか）
    index_rows = []
    for index_code, base_level in (("0000", 2700.0), ("0500", 1350.0), ("0501", 1150.0), ("0502", 980.0), ("0028", 1450.0), ("002D", 3600.0)):
        level = base_level
        for day in days_list:
            level = max(10.0, level * (1.0 + rng.gauss(0.0004, 0.009)))
            index_rows.append(
                {
                    "index_code": index_code, "trade_date": day,
                    "open": round(level * 0.998, 2), "high": round(level * 1.004, 2),
                    "low": round(level * 0.995, 2), "close": round(level, 2),
                }
            )
    repository.upsert_index_bars(index_rows)
    repository.record_sync_success(
        DATASET_INDEX_PRICES, checkpoint={"last_synced_date": target},
        rows_total=len(index_rows), data_through=target,
    )

    # 財務サマリー: 四半期累計 + 会社予想（上方修正を1社に演出）
    fin_rows = []
    for display, _name, _s33, _s33n, _mkt, base, drift in FIXTURE_SECURITIES:
        code = _canonical(display)
        annual_sales = base * 2_000_000
        for quarter_index, (period, disc_offset) in enumerate(
            (("1Q", 300), ("2Q", 210), ("3Q", 120), ("FY", 30))
        ):
            disclosed = (date.fromisoformat(target) - timedelta(days=disc_offset)).isoformat()
            cumulative = annual_sales * (quarter_index + 1) / 4.0
            margin = 0.08 + (drift * 0.05)
            fin_rows.append(
                {
                    "canonical_code": code,
                    "disclosed_date": disclosed,
                    "disclosed_time": "15:30",
                    "disclosure_number": f"FX{quarter_index}",
                    "type_of_document": "四半期決算短信〔日本基準〕（連結）" if period != "FY" else "決算短信〔日本基準〕（連結）",
                    "period_type": period,
                    "fiscal_year_end": "2026-03-31",
                    "sales": round(cumulative),
                    "operating_profit": round(cumulative * margin),
                    "ordinary_profit": round(cumulative * margin * 1.02),
                    "net_profit": round(cumulative * margin * 0.7),
                    "eps": round(cumulative * margin * 0.7 / 1_000_000, 1),
                    "equity_ratio": 42.5,
                    "forecast_sales": round(annual_sales * (1.1 if display == "7013" and period == "3Q" else 1.0)),
                    "forecast_operating_profit": round(annual_sales * margin * (1.15 if display == "7013" and period == "3Q" else 1.0)),
                    "forecast_net_profit": round(annual_sales * margin * 0.7),
                    "forecast_eps": 120.0,
                    "dividend_annual": 60.0,
                    "forecast_dividend_annual": 65.0,
                }
            )
    repository.upsert_financial_summaries(fin_rows)
    repository.record_sync_success(
        DATASET_FINANCIAL_SUMMARY, checkpoint={"last_synced_date": target},
        rows_total=len(fin_rows), data_through=target,
    )

    # 決算発表予定
    earnings_rows = []
    for offset, (display, name, _s33, s33_name, _mkt, _base, _drift) in enumerate(FIXTURE_SECURITIES[:10]):
        announce = (date.fromisoformat(target) + timedelta(days=3 + offset)).isoformat()
        earnings_rows.append(
            {
                "canonical_code": _canonical(display),
                "announcement_date": announce if offset != 4 else "",  # 1社は未定
                "company_name": name,
                "fiscal_year_end": "2026-03-31",
                "fiscal_quarter": "第１四半期",
                "sector_name": s33_name,
                "section": "プライム",
            }
        )
    repository.replace_earnings_announcements(earnings_rows)
    repository.record_sync_success(DATASET_EARNINGS_CALENDAR, rows_total=len(earnings_rows), data_through=target)

    # 信用残（週次・直近8週）
    margin_rows = []
    for display, _name, _s33, _s33n, _mkt, base, _drift in FIXTURE_SECURITIES:
        code = _canonical(display)
        for week in range(8):
            app_date = (date.fromisoformat(target) - timedelta(days=7 * week + 3)).isoformat()
            long_units = rng.uniform(0.5, 8.0) * 1_000_000
            short_units = long_units / rng.uniform(1.5, 12.0)
            margin_rows.append(
                {
                    "canonical_code": code, "application_date": app_date,
                    "short_total": round(short_units), "long_total": round(long_units),
                    "short_negotiable": round(short_units * 0.4), "long_negotiable": round(long_units * 0.5),
                    "short_standardized": round(short_units * 0.6), "long_standardized": round(long_units * 0.5),
                    "issue_type": "2",
                }
            )
    repository.upsert_margin_interest(margin_rows)
    repository.record_sync_success(
        DATASET_MARGIN_INTEREST, checkpoint={"last_synced_date": target},
        rows_total=len(margin_rows), data_through=target,
    )
    repository.record_sync_success(DATASET_MARGIN_ALERTS, checkpoint={"last_synced_date": target}, rows_total=0, data_through=target)

    # 業種別空売り比率（直近20営業日）
    ratio_rows = []
    sectors = sorted({s33 for _d, _n, s33, _sn, _m, _b, _dr in FIXTURE_SECURITIES})
    for day in days_list[-20:]:
        for sector in sectors:
            regular = rng.uniform(50, 400) * 1e9
            short_restricted = regular * rng.uniform(0.25, 0.45)
            short_free = regular * rng.uniform(0.01, 0.05)
            ratio_rows.append(
                {
                    "sector33_code": sector, "trade_date": day,
                    "selling_ex_short_value": round(regular),
                    "short_with_restriction_value": round(short_restricted),
                    "short_without_restriction_value": round(short_free),
                }
            )
    repository.upsert_short_ratios(ratio_rows)
    repository.record_sync_success(
        DATASET_SHORT_RATIO, checkpoint={"last_synced_date": target},
        rows_total=len(ratio_rows), data_through=target,
    )

    # 空売り残高報告
    position_rows = []
    for display in ("9984", "4385", "8035"):
        code = _canonical(display)
        for report in range(3):
            calc = (date.fromisoformat(target) - timedelta(days=5 * report)).isoformat()
            position_rows.append(
                {
                    "canonical_code": code,
                    "disclosed_date": calc,
                    "calculated_date": calc,
                    "holder_name": f"モルガン・スタンレーMUFG証券{report + 1}",
                    "short_position_ratio": round(0.005 + 0.002 * report, 4),
                    "short_position_shares": 1_000_000 + 50_000 * report,
                }
            )
    repository.upsert_short_positions(position_rows)
    repository.record_sync_success(
        DATASET_SHORT_POSITIONS, checkpoint={"last_synced_date": target},
        rows_total=len(position_rows), data_through=target,
    )

    # レーダー & スクリーナー断面
    config = RadarConfig(min_avg_turnover_jpy=1_000_000.0, min_listed_days=60)
    engine = RadarEngine(repository, config)
    lookback_start = days_list[0]
    summary = engine.scan(target, lookback_start=lookback_start)
    features_by_code = summary.pop("features_by_code")
    sector_median_returns = summary.pop("sector_median_returns")
    rs_context = summary.pop("rs_context")
    securities = {row["canonical_code"]: row for row in repository.list_securities(active_only=True)}
    open_events = repository.open_radar_events(terminal_states=sorted(TERMINAL_STATES))
    screener_rows = build_screener_rows(
        trade_date=target,
        features_by_code=features_by_code,
        securities=securities,
        sector_median_returns=sector_median_returns,
        topix_return_63d=rs_context.get("topix_return_63d"),
        margin_map=repository.latest_margin_map(),
        radar_state_by_code={event["canonical_code"]: event["state"] for event in open_events},
    )
    repository.replace_screener_rows(screener_rows)
    repository.record_sync_success("radar_scan", rows_total=summary.get("events_written"), data_through=target)
    repository.record_sync_success("screener_snapshot", rows_total=len(screener_rows), data_through=target)

    return {
        "data_dir": str(paths.root),
        "target_date": target,
        "securities": len(master_rows),
        "bars": len(bar_rows),
        "radar": {k: v for k, v in summary.items() if k != "sector_fit"},
        "screener_rows": len(screener_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=320)
    arguments = parser.parse_args()
    result = build_fixture(days=arguments.days)
    import json

    print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
