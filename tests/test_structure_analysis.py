"""K線構造分析（米国版移植アルゴリズム）の検証。"""

from app.services.radar.base_detector import detect_base
from app.services.radar.engine import SIGNAL_BASE_BREAK, detect_new_signal
from app.services.radar.features import clean_series, compute_features_from_series, series_excluding_last
from app.services.radar.price_action import compute_price_action, find_swings
from app.services.radar.technicals import compute_technicals, rsi14, rsi_score
from app.services.radar.vol_price_match import compute_vol_price_match


def _bar(date, open_, high, low, close, turnover=5e8):
    return {
        "trade_date": date,
        "open": open_, "high": high, "low": low, "close": close,
        "adj_open": open_, "adj_high": high, "adj_low": low, "adj_close": close,
        "turnover_value": turnover, "volume": turnover / close, "upper_limit": 0,
    }


def _date(index: int) -> str:
    return f"2026-{(index // 28) + 1:02d}-{(index % 28) + 1:02d}"


def _base_bars(days=70, resistance=110.0, support=100.0, touches_every=8):
    """支持〜抵抗の間で往復するレンジ相場（抵抗に周期的にタッチ）。"""

    bars = []
    for i in range(days):
        phase = (i % touches_every) / touches_every
        mid = support + (resistance - support) * (0.15 + 0.7 * abs(0.5 - phase) * 2)
        high = min(resistance, mid + 2.0)
        low = max(support, mid - 2.0)
        close = (high + low) / 2
        turnover = 6e8 if i < days // 2 else 4e8  # 後半は売買代金収縮
        bars.append(_bar(_date(i), close - 0.5, high, low, close, turnover))
    return bars


def test_base_detector_finds_range_base():
    series = clean_series(_base_bars())
    base = detect_base(series)
    assert base is not None
    assert base["resistance_touches"] >= 2
    assert base["resistance_high"] >= 108.0
    assert base["support_low"] <= 102.0
    assert 0.0 < base["quality"] <= 1.0
    assert base["metrics"]["tightness_quality"] > 0
    assert base["invalidation_price"] < base["support_low"]


def test_base_breakout_signal_uses_base_pivot():
    bars = _base_bars()
    # 翌日: 抵抗帯を明確に上抜く大陽線
    bars.append(_bar(_date(len(bars)), 110.0, 116.5, 109.5, 116.0, 2.0e9))
    series = clean_series(bars)
    features = compute_features_from_series(series)
    prior = series_excluding_last(series)
    base = detect_base(prior)
    assert base is not None
    detection = detect_new_signal(features, base=base)
    assert detection is not None
    signal, pivot = detection
    # 60日高値(=抵抗タッチの高値)より、ベース抵抗帯の上抜けとして識別される
    assert signal in (SIGNAL_BASE_BREAK, "high_break_60")
    assert pivot <= 116.0


def test_price_action_structure_and_patterns():
    # 上昇構造: 高値・安値とも切り上げ
    bars = []
    for i in range(60):
        base_price = 100 + i * 0.8
        wave = 3.0 * (1 if (i // 5) % 2 == 0 else -1) * ((i % 5) / 5)
        close = base_price + wave
        bars.append(_bar(_date(i), close - 1, close + 2, close - 2.5, close))
    series = clean_series(bars)
    result = compute_price_action(series)
    assert result["status"] == "active"
    assert result["structure"] in ("uptrend", "uptrend_weak", "hl_base", "range")
    assert result["score"] is not None

    # 看涨吞没: 前日陰線を当日大陽線が包む
    engulf = [_bar(_date(i), 100, 101, 98.5, 99, 5e8) for i in range(45)]
    engulf.append(_bar(_date(45), 100.0, 100.5, 98.0, 98.4))   # 陰線
    engulf.append(_bar(_date(46), 98.2, 102.8, 98.0, 102.5))   # 包む陽線
    result = compute_price_action(clean_series(engulf))
    assert "bullish_engulfing" in result["patterns"]


def test_swings_have_no_lookahead():
    highs = [100.0] * 10 + [110.0] + [100.0] * 2  # 末尾2本しか右側がない
    lows = [90.0] * 13
    swing_highs, _ = find_swings(highs, lows, span=3)
    # 右側が3本未満のピボットは未確定 → 検出されない
    assert all(idx <= len(highs) - 4 for idx, _ in swing_highs)


def test_vol_price_match_detects_absorption_direction():
    bars = []
    for i in range(70):
        # 前半: 広いレンジ・普通の売買代金 / 後半: レンジ収縮・売買代金維持 + 陽線連発
        if i < 40:
            bars.append(_bar(_date(i), 100, 103.5, 97.0, 100.5, 5e8))
        else:
            close = 100.6 + (i - 40) * 0.05
            bars.append(_bar(_date(i), close - 0.35, close + 0.5, close - 0.55, close, 5.4e8))
    result = compute_vol_price_match(clean_series(bars))
    assert result["status"] == "active"
    assert result["range_compression"] is not None and result["range_compression"] < 0.65
    assert result["setup_type"] in ("absorption_bullish", "absorption_neutral", "balanced_compression")
    if result["setup_type"] == "absorption_bullish":
        assert result["breakout_quality_adjustment"] > 0


def test_compute_scores_uses_detected_base_metrics():
    """検出済みベースの実測メトリクスが base_quality に入る（回帰防止:
    BASE_WEIGHTS_DETECTED 分岐はフィクスチャでしか踏まれていなかった）。"""

    from app.services.radar.engine import compute_scores

    bars = _base_bars()
    bars.append(_bar(_date(len(bars)), 110.0, 116.5, 109.5, 116.0, 2.0e9))
    series = clean_series(bars)
    features = compute_features_from_series(series)
    base = detect_base(series_excluding_last(series))
    assert base is not None
    scores = compute_scores(
        features,
        pivot_price=base["resistance_high"],
        hold_days=1,
        rs_topix_63d=0.05,
        rs_sector_63d=0.02,
        sector_fit=60.0,
        market_fit=70.0,
        crowding_risk=40.0,
        base_structure=base,
        price_action={"score": 66.0, "upthrust": False},
        vol_price={"breakout_quality_adjustment": 3.0, "false_breakout_risk": 0.0},
        technicals={"rsi_score": 75.0},
    )
    assert scores["base_detected"] is True
    assert scores["base_quality"]["score"] is not None
    assert scores["breakout_quality"]["vol_price_adjustment"] == 3.0
    assert scores["alert_priority"]["score"] is not None


def test_technicals_bounds_and_rsi_knots():
    closes = [100 * (1.005 ** i) for i in range(80)]
    rsi = rsi14(closes)
    assert rsi is not None and 50 < rsi <= 100
    assert rsi_score(68.0) == 88.0  # ノット最良点
    assert rsi_score(100.0) == 33.0

    bars = [_bar(_date(i), c - 0.5, c + 1, c - 1, c) for i, c in enumerate(closes)]
    result = compute_technicals(clean_series(bars))
    assert result["trend_efficiency_63d"] is not None and result["trend_efficiency_63d"] > 0.8
    assert result["range_position_60d"] is not None and result["range_position_60d"] > 0.9
    assert result["macd"]["histogram"] is not None
