"""過去のある日に立って、その日に見えていた材料だけで特徴量と分数を作る。

**点時（point-in-time）の原則**: 対象日 D の評価には D までのバーしか使わない。
実装上はここを 1 箇所に絞る —— `bars_up_to()` を通さない経路を作らないこと。
分散して truncate すると、どこかで 1 本多く渡って静かに未来が漏れる。

漏れやすい所は具体的に 3 つある:

  1. ベース（平台）検出に対象日を入れる → 当日の高値が自分の抵抗線になり、
     「上抜けた」判定が自明に成立する。本番エンジンは既に当日を除いている
     ので、ここでも同じ関数を使う。
  2. 業種中位・TOPIX を「その後修正された値」で計算する。
  3. 銘柄マスタ（業種・市場区分）を **現在の** 値で埋める。過去の評価に今日の
     業種を使うと、途中で業種変更された銘柄の履歴が書き換わる。ここは
     J-Quants の断面が 1 つしか無いので、**避けられない制約として申告する**
     （`point_in_time_limits` に出す）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.services.radar.base_detector import detect_base
from app.services.radar.engine import compute_scores, crowding_score
from app.services.radar.features import (
    clean_series,
    compute_features_from_series,
    index_return,
    series_excluding_last,
)
from app.services.radar.price_action import compute_price_action
from app.services.radar.technicals import compute_technicals
from app.services.radar.vol_price_match import compute_vol_price_match
from app.services.strength_scan import score_intrinsic_jp

REPLAY_VERSION = "jp-replay-v1"

#: 現時点で真の点時版が用意できない項目。結果に必ず添えて、無バイアスの
#: ふりをしない（doc §五「明确标记限制，不要假装无偏」）。
POINT_IN_TIME_LIMITS = (
    "sector33_code/market_code は現在のマスタ断面のみ。過去に業種・市場区分が"
    "変わった銘柄は、当時ではなく現在の分類で集計される。",
    "信用規制・空売り比率は履歴を保持しているが、訂正（同一申込日の再公表）は"
    "最新版で上書きされるため、当時見えていた初報とは一致しない場合がある。",
    "財務データは開示日ベースで持つが、後日の訂正報告は反映済みの値で残る。",
)


def bars_up_to(bars: Sequence[Mapping[str, Any]], as_of: str) -> list[Mapping[str, Any]]:
    """`as_of` **以前**のバーだけ（当日は含む）。ここが点時の単一の関門。"""

    return [row for row in bars if str(row.get("trade_date") or "") <= as_of]


@dataclass
class ReplayRow:
    canonical_code: str
    trade_date: str
    features: dict[str, Any]
    structure: dict[str, Any]
    intrinsic: dict[str, Any]
    scores: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "canonical_code": self.canonical_code,
            "trade_date": self.trade_date,
            "intrinsic_score": self.intrinsic.get("score"),
            "confidence": self.intrinsic.get("confidence"),
            "alert_priority": ((self.scores or {}).get("alert_priority") or {}).get("score"),
            "close": self.features.get("close"),
            "atr14": self.features.get("atr14"),
            "avg_turnover_20d": self.features.get("avg_turnover_20d"),
            "turnover_stability": self.features.get("turnover_stability"),
            "return_20d": self.features.get("return_20d"),
            "return_63d": self.features.get("return_63d"),
            "pct_from_high_252": self.features.get("pct_from_high_252"),
            "data_days": self.features.get("data_days"),
            "liquidity_known": self.features.get("liquidity_known"),
        }


def replay_security(
    canonical_code: str,
    bars: Sequence[Mapping[str, Any]],
    as_of: str,
    *,
    rs_topix_63d: float | None = None,
    min_data_days: int = 120,
) -> ReplayRow | None:
    """1 銘柄 × 1 日の点時評価。材料不足なら None。"""

    window = bars_up_to(bars, as_of)
    if not window or str(window[-1].get("trade_date") or "") != as_of:
        return None  # その日に値が付いていない（休場・上場前・売買停止）
    series = clean_series(window)
    if series is None:
        return None
    features = compute_features_from_series(series)
    if features is None or int(features.get("data_days") or 0) < min_data_days:
        return None
    features["liquidity_known"] = features.get("avg_turnover_20d") is not None

    # ベースは当日を除いた列から。ここを外すと当日の高値が自分の抵抗線になる。
    prior = series_excluding_last(series)
    structure = {
        "base": detect_base(prior) if prior else None,
        "price_action": compute_price_action(series),
        "vol_price": compute_vol_price_match(series),
        "technicals": compute_technicals(series),
    }
    intrinsic = score_intrinsic_jp(features, structure, rs_topix_63d=rs_topix_63d)
    return ReplayRow(
        canonical_code=canonical_code,
        trade_date=as_of,
        features=features,
        structure=structure,
        intrinsic=intrinsic,
    )


def replay_cross_section(
    bars_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    as_of: str,
    *,
    topix_bars: Sequence[Mapping[str, Any]] | None = None,
    sectors_by_code: Mapping[str, str] | None = None,
    min_data_days: int = 120,
    regulation_map: Mapping[str, Any] | None = None,
) -> list[ReplayRow]:
    """ある日の全銘柄断面。業種中位も **その日までの** データから作る。"""

    topix_window = bars_up_to(topix_bars or [], as_of)
    topix_r63 = index_return(topix_window, 63) if topix_window else None

    rows: list[ReplayRow] = []
    for code, bars in bars_by_code.items():
        row = replay_security(
            code, bars, as_of, rs_topix_63d=None, min_data_days=min_data_days
        )
        if row is not None:
            rows.append(row)

    # 業種中位は断面が揃ってから。個別の rs はここで後付けする
    # （1 銘柄ずつ計算すると自分自身を含む中位と比べてしまう）。
    by_sector: dict[str, list[float]] = {}
    for row in rows:
        sector = (sectors_by_code or {}).get(row.canonical_code)
        value = row.features.get("return_20d")
        if sector and value is not None:
            by_sector.setdefault(sector, []).append(float(value))
    sector_median = {
        sector: sorted(values)[len(values) // 2]
        for sector, values in by_sector.items()
        if len(values) >= 5      # 標本不足の業種は基準を作らない
    }

    for row in rows:
        sector = (sectors_by_code or {}).get(row.canonical_code)
        r63 = row.features.get("return_63d")
        r20 = row.features.get("return_20d")
        rs_topix = (r63 - topix_r63) if (r63 is not None and topix_r63 is not None) else None
        median20 = sector_median.get(sector or "")
        rs_sector_20d = (r20 - median20) if (r20 is not None and median20 is not None) else None
        # rs_topix を反映した intrinsic に取り直す（断面が要る指標なので後段）
        row.intrinsic = score_intrinsic_jp(
            row.features, row.structure, rs_topix_63d=rs_topix
        )
        regulation = (regulation_map or {}).get(row.canonical_code)
        row.scores = compute_scores(
            row.features,
            pivot_price=(row.structure.get("base") or {}).get("pivot_price"),
            hold_days=0,
            rs_topix_63d=rs_topix,
            rs_sector_20d=rs_sector_20d,
            rs_sector_63d=None,
            sector_fit=None,
            market_fit=None,
            crowding_risk=crowding_score(None),
            regulation_risk=(
                regulation.risk_score() if hasattr(regulation, "risk_score") else None
            ),
            base_structure=row.structure.get("base"),
            price_action=row.structure.get("price_action"),
            vol_price=row.structure.get("vol_price"),
            technicals=row.structure.get("technicals"),
        )
    return rows


def sample_dates(trading_days: Iterable[str], *, every: int = 5, skip_last: int = 20) -> list[str]:
    """評価日の間引き。

    `skip_last` は結果窓（既定 20 営業日）の分。末尾を含めると「まだ結果が
    出ていないシグナル」が混ざり、短い保有期間だけで評価されて成績が歪む。
    """

    days = sorted(set(trading_days))
    if skip_last > 0:
        days = days[:-skip_last] if len(days) > skip_last else []
    return days[::every]


__all__ = [
    "POINT_IN_TIME_LIMITS",
    "REPLAY_VERSION",
    "ReplayRow",
    "bars_up_to",
    "replay_cross_section",
    "replay_security",
    "sample_dates",
]
