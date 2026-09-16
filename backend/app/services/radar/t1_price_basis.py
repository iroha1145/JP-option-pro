"""Align the T1 T-window to the frozen first-publish price basis.

The stored resistance is an immutable event-day number. Later vendor
``adj_*`` restatements (splits after T) must not be compared against that
number in mixed units. Rebuild from raw OHLCV × factors through T when
possible. Convert restated ``adj_*`` only with a documented post-T factor
product. Do not infer a split from close-only changes.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from app.services.radar.adjustment import cumulative_factors, _factor

T1_EVENT_DAY_KIND = "jp_event_day_v1"
PRICE_BASIS_UNRELIABLE = "price_basis_unreliable"


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _finite_volume(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _bar_day(bar: Mapping[str, Any]) -> str:
    return str(bar.get("trade_date") or bar.get("session_date") or "")[:10]


def post_session_factor_product(
    factor_bars: Sequence[Mapping[str, Any]] | None,
    session_date: str,
) -> float:
    """Π{adjustment_factor(d) : d > session_date}. Missing / invalid factors are 1.0."""

    product = 1.0
    for bar in factor_bars or ():
        day = _bar_day(bar)
        if not day or day <= session_date:
            continue
        product *= _factor(bar)
    return product


def t1_price_basis_payload(
    *,
    session_date: str,
    source: str,
    post_t_factor_product: float,
) -> dict[str, Any]:
    return {
        "kind": T1_EVENT_DAY_KIND,
        "session_date": session_date,
        "source": source,
        "post_t_factor_product": post_t_factor_product,
    }


def rebuild_t1_event_day_window(
    bars: Sequence[Mapping[str, Any]] | None,
    session_date: str,
    *,
    factor_bars: Sequence[Mapping[str, Any]] | None = None,
    allow_unconverted_adj: bool = False,
) -> dict[str, Any]:
    """Rebuild bars through ``session_date`` onto the event-day price basis.

    Preference: raw × through-T factors, then ``adj_*`` divided by a documented
    post-T factor product. Unconverted ``adj_*`` is only allowed when no
    settled T1 conclusion exists yet (first publish / first eval).
    """

    empty = {
        "ok": False,
        "bars": [],
        "basis": None,
        "reason": PRICE_BASIS_UNRELIABLE,
        "sources": [],
    }
    if not session_date:
        return {**empty, "reason": "missing_session_date"}
    window = [dict(bar) for bar in (bars or []) if _bar_day(bar) and _bar_day(bar) <= session_date]
    if not window:
        return {**empty, "reason": "no_bars_through_session"}

    factors = cumulative_factors(window)
    post_t = post_session_factor_product(factor_bars, session_date)
    if not math.isfinite(post_t) or post_t <= 0:
        return {**empty, "reason": "invalid_post_t_factor_product"}

    rebuilt: list[dict[str, Any]] = []
    sources: list[str] = []
    for bar, through_t in zip(window, factors):
        day = _bar_day(bar)
        raw_open = _finite_positive(bar.get("open"))
        raw_high = _finite_positive(bar.get("high"))
        raw_low = _finite_positive(bar.get("low"))
        raw_close = _finite_positive(bar.get("close"))
        raw_volume = _finite_volume(bar.get("volume"))
        raw_complete = None not in (raw_open, raw_high, raw_low, raw_close, raw_volume)
        if raw_complete:
            if not math.isfinite(through_t) or through_t <= 0:
                return {**empty, "reason": "invalid_through_t_factor"}
            packed = {
                "trade_date": day,
                "session_date": day,
                "open": raw_open * through_t,
                "high": raw_high * through_t,
                "low": raw_low * through_t,
                "close": raw_close * through_t,
                "volume": raw_volume / through_t,
                "t1_price_source": "raw",
            }
            rebuilt.append(packed)
            sources.append("raw")
            continue

        adj_open = _finite_positive(bar.get("adj_open"))
        adj_high = _finite_positive(bar.get("adj_high"))
        adj_low = _finite_positive(bar.get("adj_low"))
        adj_close = _finite_positive(bar.get("adj_close"))
        adj_volume = _finite_volume(bar.get("adj_volume"))
        adj_complete = None not in (adj_open, adj_high, adj_low, adj_close, adj_volume)
        if not adj_complete:
            return {**empty, "reason": "missing_raw_and_adj"}

        documented_conversion = factor_bars is not None and abs(post_t - 1.0) > 1e-12
        if documented_conversion:
            packed = {
                "trade_date": day,
                "session_date": day,
                "open": adj_open / post_t,
                "high": adj_high / post_t,
                "low": adj_low / post_t,
                "close": adj_close / post_t,
                "volume": adj_volume * post_t,
                "t1_price_source": "adj_converted",
            }
            rebuilt.append(packed)
            sources.append("adj_converted")
            continue

        if allow_unconverted_adj:
            packed = {
                "trade_date": day,
                "session_date": day,
                "open": adj_open,
                "high": adj_high,
                "low": adj_low,
                "close": adj_close,
                "volume": adj_volume,
                "t1_price_source": "adj_first",
            }
            rebuilt.append(packed)
            sources.append("adj_first")
            continue
        return {**empty, "reason": PRICE_BASIS_UNRELIABLE}

    unique_sources = sorted(set(sources))
    if "raw" in unique_sources:
        source = "raw"
    elif "adj_converted" in unique_sources:
        source = "adj_converted"
    else:
        source = "adj_first"
    return {
        "ok": True,
        "bars": rebuilt,
        "basis": t1_price_basis_payload(
            session_date=session_date,
            source=source,
            post_t_factor_product=post_t if source == "adj_converted" else 1.0,
        ),
        "reason": None,
        "sources": sources,
    }


__all__ = [
    "PRICE_BASIS_UNRELIABLE",
    "T1_EVENT_DAY_KIND",
    "post_session_factor_product",
    "rebuild_t1_event_day_window",
    "t1_price_basis_payload",
]
