"""Japan breakout radar — post-close full-market daily scan.

Data flow: jp-core.db daily bars (already synced) → per-security features →
signal detection & lifecycle updates → missing-aware scores → radar_events
upsert. The scan reads only completed sessions; no intraday pretence. The
same feature pass also produces the screener cross-section rows so the
nightly batch computes everything once.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from app.domain.constants import TOPIX_INDEX_CODE
from app.personal_config import RadarConfig
from app.repositories.core import CoreRepository
from app.services import margin_regulation as mreg

from . import lifecycle as lc
from .base_detector import detect_base
from .features import (
    _median,
    clean_series,
    compute_features_from_series,
    index_return,
    series_excluding_last,
)
from .price_action import compute_price_action
from .technicals import compute_technicals
from .vol_price_match import compute_vol_price_match
from .scoring import (
    BASE_WEIGHTS,
    BASE_WEIGHTS_DETECTED,
    CONFIRMATION_WEIGHTS,
    LIQUIDITY_WEIGHTS,
    PARTICIPATION_WEIGHTS,
    RELATIVE_STRENGTH_WEIGHTS,
    SCORE_VERSION,
    TREND_WEIGHTS,
    WeightedScore,
    alert_priority,
    clamp_score,
    linear_score,
    weighted_score,
)

ENGINE_VERSION = "jp-radar-engine-v2"

SIGNAL_HIGH_252 = "high_break_252"
SIGNAL_HIGH_120 = "high_break_120"
SIGNAL_BASE_BREAK = "base_breakout"
SIGNAL_HIGH_60 = "high_break_60"
SIGNAL_VOLUME_BREAK = "volume_surge_break"
SIGNAL_HIGH_20 = "high_break_20"

# Strongest first — one new event per security per scan.
SIGNAL_PRIORITY = (
    SIGNAL_HIGH_252,
    SIGNAL_HIGH_120,
    SIGNAL_BASE_BREAK,
    SIGNAL_HIGH_60,
    SIGNAL_VOLUME_BREAK,
    SIGNAL_HIGH_20,
)

ALL_SIGNAL_TYPES = SIGNAL_PRIORITY

_FAIL_BUFFER = 0.97          # 終値がピボットの 3% 下 → 失効
_RETEST_LOW = 0.97
_RETEST_HIGH = 1.01
_RECLAIM_BUFFER = 1.005
_EXTENDED_ATR_MULTIPLE = 3.5
_WATCH_PROXIMITY = 0.015     # ピボットの 1.5% 手前 → 監視イベント
_STRONG_CLOSE_LOCATION = 0.70
_STRONG_TURNOVER_RATIO = 2.5
_VOLUME_BREAK_RATIO = 3.0
_CONFIRM_HOLD_DAYS = 2
# 業種中位を基準として信用できる最低銘柄数（これ未満は基準を作らない）
_MIN_SECTOR_SAMPLE = 5
# 営業日で数える（暦日 90 日 ≒ 営業日 61 日。連休を跨いでも老化しない）
_CONFIRMED_MAX_AGE_TRADING_DAYS = 61


def _signal_pivot(features: Mapping[str, Any], signal_type: str) -> float | None:
    if signal_type == SIGNAL_HIGH_252:
        return features.get("prior_high_252")
    if signal_type == SIGNAL_HIGH_120:
        return features.get("prior_high_120")
    if signal_type == SIGNAL_HIGH_60:
        return features.get("prior_high_60")
    return features.get("prior_high_20")


def detect_new_signal(
    features: Mapping[str, Any], *, base: Mapping[str, Any] | None = None
) -> tuple[str, float] | None:
    """Strongest breakout signal on the target day, if any.

    優先順: 52週 > 120日 > 完成ベース上抜け > 60日 > 出来高急増 > 20日。
    """

    close = features.get("close")
    if close is None:
        return None
    ratio = features.get("turnover_ratio")
    for signal_type in (SIGNAL_HIGH_252, SIGNAL_HIGH_120):
        pivot = _signal_pivot(features, signal_type)
        if pivot is not None and close > pivot:
            return signal_type, float(pivot)
    if base is not None:
        resistance = base.get("resistance_high")
        buffer = base.get("break_buffer") or 0.0
        if resistance is not None and close > float(resistance) + float(buffer):
            return SIGNAL_BASE_BREAK, float(resistance)
    pivot60 = features.get("prior_high_60")
    if pivot60 is not None and close > pivot60:
        return SIGNAL_HIGH_60, float(pivot60)
    pivot20 = features.get("prior_high_20")
    if pivot20 is not None and close > pivot20:
        if ratio is not None and ratio >= _VOLUME_BREAK_RATIO:
            return SIGNAL_VOLUME_BREAK, float(pivot20)
        return SIGNAL_HIGH_20, float(pivot20)
    return None


def detect_watch_candidate(features: Mapping[str, Any]) -> tuple[str, float] | None:
    """Close just below the 60-day pivot → tomorrow's candidate pool.

    Requires actual upward momentum — a dead-flat range whose daily highs sit
    1% above every close is not "approaching" anything."""

    close = features.get("close")
    pivot = features.get("prior_high_60")
    if close is None or pivot is None or pivot <= 0.0:
        return None
    momentum = features.get("return_20d")
    if momentum is None or momentum < 0.03:
        return None
    gap = pivot / close - 1.0
    if 0.0 < gap <= _WATCH_PROXIMITY:
        return SIGNAL_HIGH_60, float(pivot)
    return None


# ---------------------------------------------------------------------------
# score assembly
# ---------------------------------------------------------------------------


def _score_pack(result: WeightedScore) -> dict[str, Any]:
    return {
        "score": result.score,
        "confidence": result.confidence,
        "status": result.status,
        "effective_weights": result.effective_weights,
        "contributions": result.contributions,
        "missing": list(result.missing),
    }


def compute_scores(
    features: Mapping[str, Any],
    *,
    pivot_price: float | None,
    hold_days: int,
    rs_topix_63d: float | None,
    # 業種相対は 20 日（短期強度・突破環境）と 63 日（中期トレンド）を
    # 別々に持つ。以前は 20 日の値を 63 日の名前で運んでいた。
    rs_sector_20d: float | None = None,
    rs_sector_63d: float | None = None,
    sector_fit: float | None,
    market_fit: float | None,
    crowding_risk: float | None,
    regulation_risk: float | None = None,
    base_structure: Mapping[str, Any] | None = None,
    price_action: Mapping[str, Any] | None = None,
    vol_price: Mapping[str, Any] | None = None,
    technicals: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    close = features.get("close")
    atr = features.get("atr14")
    pa_score = (price_action or {}).get("score")
    rsi_component = (technicals or {}).get("rsi_score")

    trend = weighted_score(
        {
            "ma_alignment": 100.0 if features.get("ma_alignment") else (30.0 if features.get("ma_alignment") is not None else None),
            "above_ma75": None if features.get("ma75_gap_pct") is None else (100.0 if features["ma75_gap_pct"] > 0 else 20.0),
            "return_63d_score": linear_score(features.get("return_63d"), -0.10, 0.40),
            "trend_persistence": None if features.get("trend_persistence") is None else clamp_score(features["trend_persistence"] * 100.0),
            "price_structure": clamp_score(pa_score) if pa_score is not None else None,
            "rsi": clamp_score(rsi_component) if rsi_component is not None else None,
        },
        TREND_WEIGHTS,
    )

    base_metrics = (base_structure or {}).get("metrics") or {}
    if base_metrics:
        # 実測ベース品質（枢軸クラスタ検出に成功した場合、米国版と同じ次元）
        base = weighted_score(
            {
                "tightness": base_metrics.get("tightness_quality"),
                "duration": base_metrics.get("duration_quality"),
                "resistance_touches": base_metrics.get("resistance_touch_quality"),
                "turnover_contraction": base_metrics.get("turnover_contraction_quality"),
                "atr_contraction": base_metrics.get("atr_contraction_quality"),
                "support_integrity": base_metrics.get("support_integrity"),
                "higher_low": base_metrics.get("higher_low_quality"),
            },
            BASE_WEIGHTS_DETECTED,
        )
    else:
        # 代理指標（ベース未検出）: 直近ピボットと MA25 の距離を終値比で測る。
        range_pct = None
        if features.get("prior_high_20") and close:
            low_proxy = features.get("ma25")
            if low_proxy:
                range_pct = abs(features["prior_high_20"] - low_proxy) / close
        base = weighted_score(
            {
                "tightness": linear_score(-(range_pct or 0.0), -0.30, -0.06) if range_pct is not None else None,
                "duration": None,
                "contraction": linear_score(features.get("volatility_contraction"), 0.0, 0.5),
                "position_in_base": None if features.get("close_location") is None else clamp_score(features["close_location"] * 100.0),
            },
            BASE_WEIGHTS,
        )

    breakout_margin = None
    if close and pivot_price and atr and atr > 0:
        breakout_margin = (close - pivot_price) / atr
    confirmation = weighted_score(
        {
            "close_location": None if features.get("close_location") is None else clamp_score(features["close_location"] * 100.0),
            "turnover_surge": linear_score(features.get("turnover_ratio"), 1.0, 4.0),
            "breakout_margin": linear_score(breakout_margin, -0.2, 1.5),
            "hold_days": clamp_score(min(hold_days, 3) / 3.0 * 100.0),
        },
        CONFIRMATION_WEIGHTS,
    )

    relative = weighted_score(
        {
            "rs_topix": linear_score(rs_topix_63d, -0.05, 0.25),
            # 突破環境の判定なので業種相対は短期側（20 日）を使う。閾値も
            # 20 日リターン差のスケールに合わせる（63 日と同じ幅は広すぎる）。
            "rs_sector": linear_score(rs_sector_20d, -0.03, 0.15),
            "rs_sector_mid": linear_score(rs_sector_63d, -0.05, 0.25),
        },
        RELATIVE_STRENGTH_WEIGHTS,
    )

    participation = weighted_score(
        {
            "turnover_ratio_score": linear_score(features.get("turnover_ratio"), 1.0, 5.0),
            "turnover_trend": linear_score(features.get("turnover_trend"), 0.8, 2.0),
        },
        PARTICIPATION_WEIGHTS,
    )

    avg_turnover = features.get("avg_turnover_20d")
    liquidity = weighted_score(
        {
            "avg_turnover_score": linear_score(
                math.log10(avg_turnover) if avg_turnover and avg_turnover > 0 else None, 7.7, 10.0
            ),
            # 旧実装は「売買代金の欄が埋まっていれば 100」だった。普段ほぼ商いが
            # 無く 1 日だけ爆発した銘柄が満点になるので、実測の安定性に置換。
            "turnover_stability": features.get("turnover_stability"),
        },
        LIQUIDITY_WEIGHTS,
    )

    data_confidence = linear_score(features.get("data_days"), 30.0, 250.0)

    chase = 0.0
    overheat = features.get("overheat_atr_multiple")
    if overheat is not None:
        chase = max(chase, (linear_score(overheat, 1.0, 4.0) or 0.0))
    r5 = features.get("return_5d")
    if r5 is not None:
        chase = max(chase, (linear_score(r5, 0.05, 0.25) or 0.0))
    # 量価一致の假突破リスク + Upthrust は追高リスク側に積む。
    vpm_risk = float((vol_price or {}).get("false_breakout_risk") or 0.0)
    if vpm_risk > 0:
        chase += vpm_risk
    if (price_action or {}).get("upthrust"):
        chase += 8.0
    chase_risk = clamp_score(chase)

    quality_components = {
        "base": base.score,
        "confirmation": confirmation.score,
        "liquidity": liquidity.score,
    }
    quality = weighted_score(quality_components, {"base": 0.40, "confirmation": 0.45, "liquidity": 0.15})
    # Wyckoff 努力対結果による突破品質の調整（±12 に制限、監査可能に別掲）。
    vpm_adjustment = float((vol_price or {}).get("breakout_quality_adjustment") or 0.0)
    quality_score = quality.score
    if quality_score is not None and vpm_adjustment:
        quality_score = clamp_score(quality_score + max(-12.0, min(12.0, vpm_adjustment)))

    priority = alert_priority(
        breakout_quality=quality_score,
        relative_strength=relative.score,
        market_fit=market_fit,
        sector_fit=sector_fit,
        participation=participation.score,
        data_confidence=data_confidence,
        chase_risk=chase_risk,
        crowding_risk=crowding_risk,
        regulation_risk=regulation_risk,
    )

    quality_pack = _score_pack(quality)
    quality_pack["score"] = quality_score
    quality_pack["vol_price_adjustment"] = vpm_adjustment

    return {
        "score_version": SCORE_VERSION,
        "trend_quality": _score_pack(trend),
        "base_quality": _score_pack(base),
        "base_detected": bool(base_metrics),
        "breakout_confirmation": _score_pack(confirmation),
        "relative_strength": _score_pack(relative),
        "participation": _score_pack(participation),
        "liquidity": _score_pack(liquidity),
        "breakout_quality": quality_pack,
        "sector_fit": sector_fit,
        "market_fit": market_fit,
        "data_confidence": data_confidence,
        "chase_risk": chase_risk,
        "crowding_risk": crowding_risk,
        "regulation_risk": regulation_risk,
        "alert_priority": _score_pack(priority),
    }


# ---------------------------------------------------------------------------
# market / sector context
# ---------------------------------------------------------------------------


def market_fit_score(topix_series: list[Mapping[str, Any]]) -> float | None:
    closes = [float(row["close"]) for row in topix_series if row.get("close") is not None]
    if len(closes) < 60:
        return None
    close = closes[-1]
    ma50 = sum(closes[-50:]) / 50.0
    ma200 = sum(closes[-200:]) / 200.0 if len(closes) >= 200 else None
    r20 = index_return(topix_series, 20)
    score = 50.0
    score += 20.0 if close > ma50 else -20.0
    if ma200 is not None:
        score += 15.0 if close > ma200 else -15.0
    if r20 is not None:
        score += max(-15.0, min(15.0, r20 * 300.0))
    return clamp_score(score)


def sector_fit_scores(sector_returns_20d: Mapping[str, float]) -> dict[str, float]:
    """Mid-rank percentile of each sector's 20d return across all sectors."""

    items = [(code, value) for code, value in sector_returns_20d.items() if value is not None]
    if len(items) < 5:
        return {}
    values = sorted(value for _, value in items)
    n = len(values)
    result: dict[str, float] = {}
    for code, value in items:
        below = sum(1 for v in values if v < value)
        equal = sum(1 for v in values if v == value)
        percentile = (below + 0.5 * equal) / n * 100.0
        result[code] = round(percentile, 2)
    return result


def crowding_score(
    margin_row: Mapping[str, Any] | None, *, regulated: bool = False
) -> float | None:
    if margin_row is None:
        return 30.0 + (30.0 if regulated else 0.0)
    long_total = margin_row.get("long_total")
    short_total = margin_row.get("short_total")
    score = None
    if long_total and short_total and short_total > 0:
        ratio = long_total / short_total  # 信用倍率
        score = linear_score(ratio, 2.0, 15.0)
    elif long_total:
        score = 60.0
    if score is None:
        score = 30.0
    if regulated:
        score = clamp_score(score + 30.0)
    return score


# ---------------------------------------------------------------------------
# scan orchestration
# ---------------------------------------------------------------------------


class RadarEngine:
    def __init__(self, repository: CoreRepository, config: RadarConfig) -> None:
        self._repository = repository
        self._config = config

    def scan(self, target_date: str, *, lookback_start: str) -> dict[str, Any]:
        securities = self._repository.list_securities(
            active_only=True, market_codes=list(self._config.market_codes)
        )
        # 株式のみ: 業種が付く銘柄（ETF/REIT は業種なし or その他扱い）。
        equities = {
            row["canonical_code"]: row
            for row in securities
            if row.get("sector33_code") and row.get("sector33_code") != "9999"
        }
        bars_by_code = self._repository.bars_matrix_since(lookback_start)
        topix = self._repository.index_series(TOPIX_INDEX_CODE, start_date=lookback_start)
        topix_r63 = index_return(topix, 63)
        market_fit = market_fit_score(topix)
        margin_map = self._repository.latest_margin_map()
        regulation_map = self._build_regulation_map(target_date, equities.keys())

        features_by_code: dict[str, dict[str, Any]] = {}
        structure_by_code: dict[str, dict[str, Any]] = {}
        sector_returns: dict[str, list[float]] = {}
        sector_returns_63d: dict[str, list[float]] = {}
        for code, security in equities.items():
            bars = bars_by_code.get(code)
            if not bars or bars[-1].get("trade_date") != target_date:
                continue  # 当日データの無い銘柄はスキャン対象外
            series = clean_series(bars)
            if series is None:
                continue
            features = compute_features_from_series(series)
            if features is None:
                continue
            if features.get("data_days", 0) < self._config.min_listed_days:
                continue
            avg_turnover = features.get("avg_turnover_20d")
            if avg_turnover is not None and avg_turnover < self._config.min_avg_turnover_jpy:
                continue
            # 売買代金が **取れない** 銘柄を「閾値未満ではない」として通していた。
            # 欠損は合格ではない: 流動性は判定不能なので低信頼として印を付け、
            # 新規採用は正規プールの後ろに回す（0 や中央値で埋めない）。
            features["liquidity_known"] = avg_turnover is not None
            features_by_code[code] = features
            # 構造分析: ベースは「当日を除いた」列で検出（先読み禁止）。
            prior_series = series_excluding_last(series)
            structure_by_code[code] = {
                "base": detect_base(prior_series) if prior_series else None,
                "price_action": compute_price_action(series),
                "vol_price": compute_vol_price_match(series),
                "technicals": compute_technicals(series),
            }
            sector = security.get("sector33_code")
            if sector and features.get("return_20d") is not None:
                sector_returns.setdefault(sector, []).append(features["return_20d"])
            if sector and features.get("return_63d") is not None:
                sector_returns_63d.setdefault(sector, []).append(features["return_63d"])

        # 業種の中位を基準にする以上、標本が数銘柄しかない業種の「中位」は
        # 業種の実勢ではなく個別銘柄そのもの。相対強度が自分自身との比較に
        # 縮退するので、標本不足の業種は基準を作らない（= rs_sector は None、
        # 欠損として重みから外れる。0 で埋めない）。
        sector_median_returns = {
            sector: _median(values)
            for sector, values in sector_returns.items()
            if len(values) >= _MIN_SECTOR_SAMPLE
        }
        sector_median_returns_63d = {
            sector: sorted(values)[len(values) // 2]
            for sector, values in sector_returns_63d.items()
            if len(values) >= _MIN_SECTOR_SAMPLE
        }
        sector_fit = sector_fit_scores(sector_median_returns)

        open_events = {
            event["event_id"]: event
            for event in self._repository.open_radar_events(terminal_states=sorted(lc.TERMINAL_STATES))
        }
        events_by_code: dict[str, list[dict[str, Any]]] = {}
        for event in open_events.values():
            events_by_code.setdefault(event["canonical_code"], []).append(event)

        updated: list[dict[str, Any]] = []
        # 新規イベントは一旦ここに溜め、**優先度で並べてから**上限で切る。
        # 走査順（銘柄コード順）で切ると強いシグナルが黙って捨てられる。
        new_candidates: list[dict[str, Any]] = []
        transitions = 0

        for code, features in features_by_code.items():
            security = equities[code]
            sector = security.get("sector33_code") or ""
            rs_topix = None
            if features.get("return_63d") is not None and topix_r63 is not None:
                rs_topix = features["return_63d"] - topix_r63
            # 行業相対は 20 日リターン同士の比較 → 20 日指標。63 日の名前で
            # 保存していたため、UI も DB も API も 63 日だと言いながら中身は
            # 20 日だった。窓は名前と一致させる（混用しない）。
            sector_median_20d = sector_median_returns.get(sector)
            rs_sector_20d = None
            if features.get("return_20d") is not None and sector_median_20d is not None:
                rs_sector_20d = features["return_20d"] - sector_median_20d
            sector_median_63d = sector_median_returns_63d.get(sector)
            rs_sector_63d = None
            if features.get("return_63d") is not None and sector_median_63d is not None:
                rs_sector_63d = features["return_63d"] - sector_median_63d
            regulation = regulation_map.get(code, mreg.UNKNOWN_STATE)
            margin_row = margin_map.get(code)
            crowding = crowding_score(margin_row, regulated=bool(regulation.regulated))
            structure = structure_by_code.get(code) or {}
            score_kwargs = {
                "rs_topix_63d": rs_topix,
                "rs_sector_20d": rs_sector_20d,
                "rs_sector_63d": rs_sector_63d,
                "regulation_risk": regulation.risk_score(),
                "sector_fit": sector_fit.get(sector),
                "market_fit": market_fit,
                "crowding_risk": crowding,
                "base_structure": structure.get("base"),
                "price_action": structure.get("price_action"),
                "vol_price": structure.get("vol_price"),
                "technicals": structure.get("technicals"),
            }

            existing = events_by_code.get(code, [])
            handled_signals: set[str] = set()

            for event in existing:
                outcome = self._advance_event(event, features, target_date)
                if outcome is None:
                    continue
                event, changed = outcome
                handled_signals.add(event["signal_type"])
                scores = compute_scores(
                    features,
                    pivot_price=event.get("pivot_price"),
                    hold_days=int(event["features"].get("hold_days") or 0),
                    **score_kwargs,
                )
                event["scores"] = scores
                event["alert_priority"] = (scores.get("alert_priority") or {}).get("score")
                event_features = dict(event.get("features") or {})
                event_features["structure"] = _structure_snapshot(structure)
                event["features"] = event_features
                updated.append(event)
                if changed:
                    transitions += 1

            detection = detect_new_signal(features, base=structure.get("base"))
            watch = None if detection else detect_watch_candidate(features)
            chosen = detection or watch
            if chosen is None:
                continue
            signal_type, pivot = chosen
            if signal_type in handled_signals:
                continue
            pivot_date = target_date
            event_id = lc.event_identity(code, signal_type, pivot_date, pivot)
            if event_id in open_events:
                continue
            state = lc.STATE_TRIGGERED if detection else lc.STATE_WATCHING
            reason = lc.REASON_TRIGGERED if detection else lc.REASON_WATCHING
            hold_days = 1 if detection else 0
            strong = (
                detection is not None
                and (features.get("close_location") or 0.0) >= _STRONG_CLOSE_LOCATION
                and (features.get("turnover_ratio") or 0.0) >= _STRONG_TURNOVER_RATIO
            )
            transitions_log = [
                {"date": target_date, "from": None, "to": state, "reason": reason}
            ]
            if strong:
                state = lc.STATE_CONFIRMED
                transitions_log.append(
                    {
                        "date": target_date,
                        "from": lc.STATE_TRIGGERED,
                        "to": state,
                        "reason": lc.REASON_CONFIRMED_STRONG,
                    }
                )
            scores = compute_scores(
                features,
                pivot_price=pivot,
                hold_days=hold_days,
                **score_kwargs,
            )
            new_candidates.append(
                {
                    "event_id": event_id,
                    "canonical_code": code,
                    "signal_type": signal_type,
                    "state": state,
                    "discovered_date": target_date,
                    "pivot_price": pivot,
                    "trigger_price": features.get("close") if detection else None,
                    "state_changed_date": target_date,
                    "last_scanned_date": target_date,
                    "alert_priority": (scores.get("alert_priority") or {}).get("score"),
                    "scores": scores,
                    "features": {
                        "engine_version": ENGINE_VERSION,
                        "hold_days": hold_days,
                        "event_high": features.get("close"),
                        "liquidity_known": bool(features.get("liquidity_known")),
                        "snapshot": _feature_snapshot(features),
                        "structure": _structure_snapshot(structure),
                    },
                    "transitions": transitions_log,
                }
            )

        # 新規イベントの採用: シグナル強度 → アラート優先度 の順で並べ、上限で切る。
        # 既存イベントの更新（`updated`）は無条件に保存する —— 上限は「今日新しく
        # 監視対象を何件増やすか」の話で、追跡中の事件を捨てる理由にはならない。
        signal_rank = {name: index for index, name in enumerate(SIGNAL_PRIORITY)}
        new_candidates.sort(
            key=lambda item: (
                # 流動性不明は正規プールの後ろ（枠が余ったときだけ採用）
                0 if (item.get("features") or {}).get("liquidity_known") else 1,
                signal_rank.get(item["signal_type"], len(signal_rank)),
                -(item.get("alert_priority") or 0.0),
                item["canonical_code"],
            )
        )
        cap = self._config.max_new_events_per_scan
        accepted = new_candidates[:cap]
        dropped = len(new_candidates) - len(accepted)
        updated.extend(accepted)

        if updated:
            self._repository.upsert_radar_events(updated)

        return {
            "engine_version": ENGINE_VERSION,
            "target_date": target_date,
            "scanned": len(features_by_code),
            "events_written": len(updated),
            "events_created": len(accepted),
            # 上限で落とした件数を黙って隠さない（0 でも必ず返す）
            "events_detected": len(new_candidates),
            "events_dropped_by_cap": dropped,
            "new_event_cap": cap,
            "state_transitions": transitions,
            "market_fit": market_fit,
            "sector_fit": sector_fit,
            "features_by_code": features_by_code,
            "structure_by_code": structure_by_code,
            "sector_median_returns": sector_median_returns,
            "sector_median_returns_63d": sector_median_returns_63d,
            "regulation_map": regulation_map,
            "rs_context": {"topix_return_63d": topix_r63},
        }

    def _advance_event(
        self, event: dict[str, Any], features: Mapping[str, Any], target_date: str
    ) -> tuple[dict[str, Any], bool] | None:
        if event.get("last_scanned_date") == target_date:
            return None  # 同一日再実行 → 冪等
        close = features.get("close")
        pivot = event.get("pivot_price")
        if close is None or pivot is None or pivot <= 0.0:
            return None
        state = event["state"]
        event_features = dict(event.get("features") or {})
        hold_days = int(event_features.get("hold_days") or 0)
        event_high = float(event_features.get("event_high") or 0.0)
        atr = features.get("atr14")

        days_open = self._trading_days_open(event["discovered_date"], target_date)
        confirmed_family = state in (
            lc.STATE_CONFIRMED, lc.STATE_HOLDING, lc.STATE_RETESTING,
            lc.STATE_RETEST_HELD, lc.STATE_REACCELERATING, lc.STATE_EXTENDED,
        )
        observation = {
            "failed": close < pivot * _FAIL_BUFFER,
            "expired": (
                days_open > self._config.expiry_trading_days if not confirmed_family
                else days_open > _CONFIRMED_MAX_AGE_TRADING_DAYS
            ),
            "triggered": close > pivot,
            "holding": close > pivot,
            "retesting": confirmed_family and pivot * _RETEST_LOW <= close <= pivot * _RETEST_HIGH,
            "retest_reclaimed": close > pivot * _RECLAIM_BUFFER,
            "new_event_high": event_high > 0.0 and close > event_high,
            "extended": bool(atr and atr > 0 and (close - pivot) / atr > _EXTENDED_ATR_MULTIPLE),
        }
        # 確認判定は「今日ピボットの上で引けた」なら状態を問わず評価する。
        # TRIGGERED のときだけ計算していたため、同じ 1 日の値動きでも新規検出
        # なら CONFIRMED、既存の WATCHING なら TRIGGERED 止まり、という食い違いが
        # あった（新規側は scan() で strong を見て CONFIRMED を積んでいる）。
        if close > pivot:
            next_hold = hold_days + 1
            observation["confirmed_hold"] = next_hold >= _CONFIRM_HOLD_DAYS
            observation["confirmed_strong"] = (
                (features.get("close_location") or 0.0) >= _STRONG_CLOSE_LOCATION
                and (features.get("turnover_ratio") or 0.0) >= _STRONG_TURNOVER_RATIO
            )

        event_features["hold_days"] = hold_days + 1 if close > pivot else 0
        event_features["event_high"] = max(event_high, close)
        event_features["snapshot"] = _feature_snapshot(features)
        event["features"] = event_features
        event["last_scanned_date"] = target_date

        # 1 日で 2 段進むことがある（窓開け突破 = TRIGGERED → EXTENDED）。
        # 途中で棄却された場合はそこで打ち切り、状態を巻き戻さない。
        changed = False
        log = list(event.get("transitions") or [])
        for target_state, reason in lc.resolve_path(state, observation):
            result = lc.transition(state, target_state, reason)
            if not result.changed:
                break
            state = result.state
            log.append(
                {"date": target_date, "from": result.previous_state, "to": result.state, "reason": result.reason}
            )
            changed = True
        if changed:
            event["state"] = state
            event["state_changed_date"] = target_date
            event["transitions"] = log[-40:]
        return event, changed

    def _build_regulation_map(
        self, target_date: str, universe: Any
    ) -> dict[str, mreg.RegulationState]:
        """走査日時点の信用規制状態。リストが古ければ全銘柄「判定不能」。

        日々公表は営業日ごとに出る。同期が止まっている日に「リストに無い =
        規制なし」と読むと、実際には増担保が掛かっている銘柄を無印で上位に
        出してしまう。鮮度が測れないときは無規制ではなく unknown に倒す。
        """

        try:
            alerts = self._repository.latest_margin_alert_map()
            latest = self._repository.latest_margin_alert_date()
        except Exception:  # noqa: BLE001 — 規制が読めなくても走査自体は続ける
            return {}
        gap: int | None = None
        if latest:
            try:
                days = self._repository.trading_days_between(latest, target_date)
                gap = max(0, len(days) - 1) if days else None
            except Exception:  # noqa: BLE001
                gap = None
        return mreg.build_regulation_map(
            alerts.values(), as_of=target_date, trading_days_since=gap, universe=universe
        )

    def _trading_days_open(self, discovered_date: str, target_date: str) -> int:
        """発見日から経過した **営業日** 数。

        暦日差だと週末・祝日・GW・年末年始で新しい取引情報が 1 つも増えて
        いないのにイベントが老化し、連休明けに一斉失効する。取引所カレンダー
        が無い場合のみ暦日にフォールバックする（その旨は data_confidence 側で
        は扱わない —— 期限判定を止めるほうが害が大きいため）。
        """

        try:
            days = self._repository.trading_days_between(discovered_date, target_date)
        except Exception:  # noqa: BLE001 — カレンダー未同期でも走査は止めない
            days = []
        if days:
            # 発見日自身を 0 日目とする（片端を除く）
            return max(0, len(days) - 1)
        return _date_diff_days(discovered_date, target_date)


def _structure_snapshot(structure: Mapping[str, Any]) -> dict[str, Any]:
    """イベント行に保存する構造分析の要約（フルの swing 配列等は間引く）。"""

    base = structure.get("base") or None
    price_action = structure.get("price_action") or {}
    vol_price = structure.get("vol_price") or {}
    technicals = structure.get("technicals") or {}
    return {
        "base": (
            {
                "pivot_id": base.get("pivot_id"),
                "pivot_price": base.get("pivot_price"),
                "resistance_low": base.get("resistance_low"),
                "resistance_high": base.get("resistance_high"),
                "support_low": base.get("support_low"),
                "invalidation_price": base.get("invalidation_price"),
                "base_start": base.get("base_start"),
                "base_end": base.get("base_end"),
                "resistance_touches": base.get("resistance_touches"),
                "quality": base.get("quality"),
            }
            if base
            else None
        ),
        "structure": price_action.get("structure"),
        "structure_label": price_action.get("structure_label"),
        "price_action_score": price_action.get("score"),
        "pattern_labels": price_action.get("pattern_labels") or [],
        "spring": bool(price_action.get("spring")),
        "upthrust": bool(price_action.get("upthrust")),
        "setup_type": vol_price.get("setup_type"),
        "setup_label": vol_price.get("setup_label"),
        "vpm_tags": vol_price.get("tags") or [],
        "rsi14": technicals.get("rsi14"),
        "trend_efficiency_63d": technicals.get("trend_efficiency_63d"),
    }


def _feature_snapshot(features: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "trade_date", "close", "atr14", "turnover_today", "avg_turnover_20d",
        "turnover_ratio", "return_5d", "return_20d", "return_63d",
        "pct_from_high_252", "ma25_gap_pct", "ma75_gap_pct", "ma_alignment",
        "close_location", "volatility_contraction", "overheat_atr_multiple",
        "data_days", "upper_limit_today", "liquidity_known",
    )
    return {key: features.get(key) for key in keys}


def _date_diff_days(start: str, end: str) -> int:
    from datetime import date

    try:
        return (date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days
    except ValueError:
        return 0


__all__ = [
    "ALL_SIGNAL_TYPES",
    "ENGINE_VERSION",
    "RadarEngine",
    "SIGNAL_PRIORITY",
    "compute_scores",
    "crowding_score",
    "detect_new_signal",
    "detect_watch_candidate",
    "market_fit_score",
    "sector_fit_scores",
]
