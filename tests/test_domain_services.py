"""時間・四半期導出・スクリーナーフィルタ・アクセス制御の単体検証。"""

from datetime import datetime, timezone

import pytest

from app.access import hash_owner_password, owner_password_hash_is_valid, verify_owner_password
from app.domain.timeutil import JST, seconds_until_next_jst_time
from app.services.screener import ScreenerFilters, compile_filters
from app.services.stock_research import derive_quarter_values


def test_jst_schedule_next_slot():
    # JST 2026-08-03 16:00 → 17:00 まで 3600 秒
    now = datetime(2026, 8, 3, 16, 0, tzinfo=JST)
    assert seconds_until_next_jst_time(("17:00",), now=now) == 3600.0
    # 既に過ぎた時刻は翌日へ
    assert seconds_until_next_jst_time(("07:10",), now=now) == pytest.approx(15.0 * 3600 + 600, abs=1)


def test_quarter_derivation_from_cumulative():
    summaries = [
        {"fiscal_year_end": "2026-03-31", "period_type": "1Q", "disclosed_date": "2025-08-01",
         "sales": 100.0, "operating_profit": 10.0, "ordinary_profit": 11.0, "net_profit": 7.0},
        {"fiscal_year_end": "2026-03-31", "period_type": "2Q", "disclosed_date": "2025-11-01",
         "sales": 220.0, "operating_profit": 24.0, "ordinary_profit": 25.0, "net_profit": 16.0},
        {"fiscal_year_end": "2026-03-31", "period_type": "FY", "disclosed_date": "2026-05-10",
         "sales": 470.0, "operating_profit": 52.0, "ordinary_profit": 54.0, "net_profit": 34.0},
    ]
    quarters = derive_quarter_values(summaries)
    q2 = next(q for q in quarters if q["period_type"] == "2Q")
    assert q2["sales"] == 120.0 and q2["operating_profit"] == 14.0
    fy = next(q for q in quarters if q["period_type"] == "FY")
    # 3Q が欠けているので FY 単期は導出不能 → None（0 にしない）
    assert fy["sales"] is None


def test_screener_filter_compilation_is_allowlisted():
    filters = ScreenerFilters(markets=["0111"], min_price=100, ma_alignment=True, sort_by="return_20d")
    where_sql, params, order_sql = compile_filters(filters)
    assert "market_code IN (?)" in where_sql
    assert "close >= ?" in where_sql
    assert "ma_alignment = 1" in where_sql
    assert params == ["0111", 100]
    assert order_sql.startswith("return_20d IS NULL, return_20d DESC")


def test_screener_rejects_unknown_fields():
    with pytest.raises(Exception):
        ScreenerFilters(evil="1; DROP TABLE screener_rows")  # extra=forbid


def test_owner_password_roundtrip():
    encoded = hash_owner_password("correct-horse-battery")
    assert owner_password_hash_is_valid(encoded)
    assert verify_owner_password("correct-horse-battery", encoded)
    assert not verify_owner_password("wrong-password-123", encoded)
    with pytest.raises(ValueError):
        hash_owner_password("short")
