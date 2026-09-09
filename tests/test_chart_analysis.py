"""日本站图表分析包：副图序列、指纹、TOPIX RS，且不引入 pandas。"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone

from app.services.chart_analysis import (
    FINGERPRINT_ALGORITHM,
    TOPIX_INDEX_CODE,
    assemble_chart_analysis,
    bar_fingerprint,
    chart_analysis_for_bars,
    rsi_series,
    series_from_jp_bars,
    sma_series,
    topix_close_map,
)
from app.services.stock_research import stock_chart, technical_structure


def _bar(day: str, close: float, *, volume: float = 1000, high=None, low=None, open_=None):
    high = close + 1 if high is None else high
    low = close - 1 if low is None else low
    open_ = close if open_ is None else open_
    return {
        "trade_date": day,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "adj_open": open_,
        "adj_high": high,
        "adj_low": low,
        "adj_close": close,
        "volume": volume,
        "turnover_value": volume * close,
    }


def _trend_bars(n: int = 80, start: float = 100.0) -> list[dict]:
    bars = []
    for i in range(n):
        wave = 3.5 * ((i % 12) - 6)
        close = start + i * 0.4 + wave
        month = (i // 28) + 1
        day = (i % 28) + 1
        bars.append(_bar(f"2026-{month:02d}-{day:02d}", close, volume=1000 + i))
    return bars


def test_series_fingerprint_uses_utc_midnight_and_volume():
    bars = _trend_bars(40)
    series = series_from_jp_bars(bars, min_bars=30)
    assert series is not None
    assert series["times"][0] == int(
        datetime.fromisoformat(series["dates"][0]).replace(tzinfo=timezone.utc).timestamp()
    )
    assert series["volumes"][0] == 1000
    digest = bar_fingerprint(series)
    assert len(digest) == 64
    assert digest == bar_fingerprint(series)


def test_indicator_panes_include_rsi_macd_and_topix_rs():
    bars = _trend_bars(80)
    topix = {bar["trade_date"]: 2000 + i for i, bar in enumerate(bars)}
    bundle = chart_analysis_for_bars(bars, ticker="72030", topix_closes=topix)
    assert bundle is not None
    assert bundle["version"].startswith("jp-chart-analysis")
    assert bundle["ticker"] == "72030"
    assert bundle["range"] == "1d"
    assert bundle["adjustment"] == "adjusted"
    assert bundle["fingerprintAlgorithm"] == FINGERPRINT_ALGORITHM
    ids = [pane["id"] for pane in bundle["indicatorPanes"]]
    assert ids[:5] == ["rsi", "macd", "obv", "clv", "range_persistence"]
    assert "topix_rs" in ids
    assert "spy_rs" not in ids
    rsi = next(pane for pane in bundle["indicatorPanes"] if pane["id"] == "rsi")
    assert any(value is not None for value in rsi["values"]["rsi"])
    kinds = {row["kind"] for row in bundle["overlays"]}
    assert {"ma", "swing"}.issubset(kinds)


def test_chart_analysis_failure_is_none_not_exception():
    assert chart_analysis_for_bars([], ticker="72030") is None
    assert chart_analysis_for_bars([_bar("2026-01-01", 10)], ticker="72030") is None


def test_stock_research_keeps_legacy_overlays_and_adds_analysis():
    bars = _trend_bars(80)
    technical = technical_structure(bars, ticker="72030", topix_closes={})
    assert technical is not None
    assert "chart_overlays" in technical
    assert technical["chart_overlays"]["swing_highs"] is not None
    assert technical["last_bar"]["trade_date"] == bars[-1]["trade_date"]
    assert technical["chart_analysis"] is not None
    assert technical["chart_analysis"]["indicatorPanes"]


def test_stock_chart_includes_aligned_analysis(data_dir, monkeypatch):
    from app.tools.dev_fixture import build_fixture
    from app.repositories.core import CoreRepository

    build_fixture(str(data_dir), days=140)
    repo = CoreRepository(data_dir / "jp-core.db")
    codes = [row["canonical_code"] for row in repo.list_securities(active_only=True)]
    assert codes
    payload = stock_chart(repo, codes[0], range_key="6m")
    assert payload["bars"]
    analysis = payload["chart_analysis"]
    assert analysis is not None
    assert analysis["barCount"] == len(analysis["dates"])
    assert analysis["dataThrough"] == payload["data_through"]
    pane_ids = [pane["id"] for pane in analysis["indicatorPanes"]]
    assert "rsi" in pane_ids
    assert "macd" in pane_ids


def test_topix_map_ignores_bad_rows():
    mapped = topix_close_map(
        [
            {"index_code": TOPIX_INDEX_CODE, "trade_date": "2026-01-05", "close": 2700},
            {"trade_date": "2026-01-06", "close": None},
            {"trade_date": "", "close": 1},
        ]
    )
    assert mapped == {"2026-01-05": 2700.0}


def test_rsi_and_sma_warmup_stay_none():
    closes = [100 + i for i in range(20)]
    rsi = rsi_series(closes)
    assert rsi[:14] == [None] * 14
    assert rsi[14] is not None
    ma = sma_series(closes, 20)
    assert ma[:19] == [None] * 19
    assert ma[19] == 109.5


def test_assembler_does_not_import_pandas():
    module = importlib.import_module("app.services.chart_analysis")
    assert "pandas" not in getattr(module, "__dict__", {})
    source = module.__file__
    assert source
    text = open(source, encoding="utf-8").read()
    assert "import pandas" not in text
    assert "spy_rs" not in text
    lowered = text.lower()
    assert "from pandas" not in lowered
    assert "import pandas" not in lowered


def test_fingerprint_matches_visible_adjusted_bars():
    from app.services.chart_analysis import _fmt6

    bars = _trend_bars(80)
    bundle = chart_analysis_for_bars(bars, ticker="72030")
    assert bundle is not None
    by_date = {str(bar["trade_date"])[:10]: bar for bar in bars}
    lines = []
    for day in bundle["dates"]:
        bar = by_date[day]
        close = bar["adj_close"]
        open_ = bar.get("adj_open") if bar.get("adj_open") is not None else close
        high = bar.get("adj_high") if bar.get("adj_high") is not None else close
        low = bar.get("adj_low") if bar.get("adj_low") is not None else close
        volume = bar["volume"] if bar.get("volume") is not None else (bar.get("turnover_value") or 0)
        epoch = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())
        lines.append(
            f"{epoch}|{_fmt6(open_)}|{_fmt6(high)}|{_fmt6(low)}|{_fmt6(close)}|{_fmt6(volume)}|0|0"
        )
    import hashlib

    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    assert digest == bundle["barFingerprint"]


def test_assemble_without_topix_omits_rs_pane():
    bars = _trend_bars(80)
    series = series_from_jp_bars(bars, min_bars=30)
    assert series is not None
    bundle = assemble_chart_analysis(
        series=series,
        data_through=series["dates"][-1],
        ticker="72030",
        topix_closes=None,
    )
    assert all(pane["id"] != "topix_rs" for pane in bundle["indicatorPanes"])
