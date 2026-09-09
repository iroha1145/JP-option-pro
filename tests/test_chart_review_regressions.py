"""Review regressions: split consistency, missing pattern detection, event dates."""

from copy import deepcopy
from datetime import date, timedelta

import pytest

from app.services.chart_analysis import chart_analysis_for_bars, chart_bars, series_from_jp_bars
from app.services.chart_patterns import detect_auto_patterns
from app.services.radar.price_action import compute_price_action
from app.services.stock_research import stock_chart


def _bar(index, close=100.0, **fields):
    return {
        "trade_date": (date(2026, 1, 5) + timedelta(days=index)).isoformat(),
        "open": close, "high": close + 1, "low": close - 1, "close": close,
        "adj_open": None, "adj_high": None, "adj_low": None, "adj_close": None,
        "volume": 1000.0, "adj_volume": None, "turnover_value": close * 1000,
        "adjustment_factor": 1.0, **fields,
    }


class ChartRepository:
    def __init__(self, bars):
        self.bars = bars

    def bars_for_code(self, code, *, limit):
        return self.bars[-limit:]

    def index_series(self, code, *, limit):
        return [{"trade_date": b["trade_date"], "close": 2000} for b in self.bars]


def test_bulk_split_chart_and_analysis_use_the_same_adjusted_prices_and_volume():
    bars = [_bar(i, 200 if i < 40 else 100, volume=1000 if i < 40 else 2000) for i in range(80)]
    bars[40]["adjustment_factor"] = 0.5
    original = deepcopy(bars)
    payload = stock_chart(ChartRepository(bars), "76780", range_key="6m")
    visible = payload["bars"]
    assert bars == original  # raw source is still available to the raw-price view
    assert visible[39]["close"] == 200
    assert visible[39]["adj_close"] == visible[40]["adj_close"] == 100
    assert visible[39]["adj_volume"] == visible[40]["adj_volume"] == 2000
    series = series_from_jp_bars(visible)
    assert series["closes"] == [b["adj_close"] for b in visible]
    assert series["volumes"] == [b["adj_volume"] for b in visible]
    bundle = payload["chart_analysis"]
    rsi = next(p for p in bundle["indicatorPanes"] if p["id"] == "rsi")
    obv = next(p for p in bundle["indicatorPanes"] if p["id"] == "obv")
    assert all(v == 50 for v in rsi["values"]["rsi"])
    assert all(v == 0 for v in obv["values"]["obv"])


def test_stored_adjustment_is_not_applied_twice():
    bars = [_bar(i, 200) for i in range(40)]
    bars[-1]["adjustment_factor"] = 0.5
    bars[0].update(adj_open=100, adj_high=101, adj_low=99, adj_close=100, adj_volume=2000)
    once = chart_bars(bars)
    assert once[0]["adj_close"] == 100
    assert once[0]["adj_volume"] == 2000
    assert chart_bars(once) == once


def test_missing_share_volume_never_uses_yen_turnover():
    bars = [_bar(i, 100 + i, volume=None, turnover_value=10_000_000) for i in range(40)]
    series = series_from_jp_bars(bars)
    assert series["volumes"] == [0] * 40
    assert all(b["adj_volume"] is None for b in chart_bars(bars))


def _zigzag(low, high, count=160):
    bars = []
    for i in range(count):
        phase = i % 12
        position = phase / 6 if phase <= 6 else (12 - phase) / 6
        price = low(i) + (high(i) - low(i)) * position
        bars.append(_bar(i, round(price + 0.05, 4), open=round(price - 0.05, 4),
                         high=round(price + 0.15, 4), low=round(price - 0.15, 4)))
    return bars


@pytest.mark.parametrize("low,high,kind,subtype", [
    (lambda i: 40 + 0.12 * i, lambda i: 90 - 0.12 * i, "triangle", "symmetric"),
    (lambda i: 40 + 0.14 * i, lambda i: 80, "triangle", "ascending"),
    (lambda i: 40, lambda i: 90 - 0.14 * i, "triangle", "descending"),
    (lambda i: 40 + 0.22 * i, lambda i: 70 + 0.12 * i, "wedge", "rising"),
    (lambda i: 80 - 0.12 * i, lambda i: 110 - 0.22 * i, "wedge", "falling"),
])
def test_triangle_and_wedge_reach_the_public_chart_bundle(low, high, kind, subtype):
    bars = _zigzag(low, high)
    bundle = stock_chart(ChartRepository(bars), "72030", range_key="1y")["chart_analysis"]
    matched = [o for o in bundle["overlays"] if o["kind"] == kind and o["geometry"]["subtype"] == subtype]
    assert matched
    assert all(o["sourceId"] == "auto_patterns" for o in matched)
    assert all(len(o["geometry"]["supportRail"]) == len(o["geometry"]["resistanceRail"]) == 2 for o in matched)
    assert all(a["barKey"] in bundle["dates"] for o in matched for a in o["geometry"]["anchors"])


def test_patterns_respect_the_requested_completed_session():
    series = series_from_jp_bars(_zigzag(lambda i: 50 + i * 0.16, lambda i: 64 + i * 0.16))
    cut = {key: values[:-8] for key, values in series.items()}
    through = cut["dates"][-1]
    assert detect_auto_patterns(series, data_through=through) == detect_auto_patterns(cut, data_through=through)


def test_candle_marker_stays_on_the_actual_penultimate_bar():
    bars = [_bar(i) for i in range(40)]
    bars[-2].update(open=99.5, close=100, high=100.1, low=95)
    bundle = chart_analysis_for_bars(bars, ticker="72030")
    hammers = [o for o in bundle["overlays"] if o["kind"] == "candle" and o["geometry"]["pattern"] == "hammer"]
    assert len(hammers) == 1
    assert hammers[0]["geometry"]["anchors"][0]["barKey"] == bars[-2]["trade_date"]
    assert hammers[0]["geometry"]["anchors"][0]["price"] == 100


@pytest.mark.parametrize("name,high,low,close,level", [
    ("spring", 101, 94, 100, 95),
    ("upthrust", 106, 99, 100, 105),
])
def test_trap_switch_has_an_event_at_its_real_session(name, high, low, close, level):
    bars = [_bar(i) for i in range(45)]
    bars[25].update(high=105, low=95)
    bars[39].update(high=high, low=low, close=close)
    series = series_from_jp_bars(bars)
    price_action = compute_price_action(series)
    assert price_action[name] is True
    bundle = chart_analysis_for_bars(bars, ticker="72030")
    markers = [o for o in bundle["overlays"] if o["kind"] == "trap" and o["geometry"]["pattern"] == name]
    assert len(markers) == 1
    anchor = markers[0]["geometry"]["anchors"][0]
    assert anchor["barKey"] == bars[39]["trade_date"]
    assert anchor["price"] == level
