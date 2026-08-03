"""強度スキャン API — 夜間断面の読み出し + 要求時の profile/market 重ね掛け。

米国版 /api/strength/* との対応:
- GET /scan     … スキャン実行（保存済み断面に対するビュー計算; 全評価済み
                   母集団へサーバ側でフィルタを掛けるので「上位N名内だけの
                   絞り込み」問題は日本版には存在しない）
- GET /market   … 市場レジーム 6 次元
- GET /profiles … 選択肢メタ（周期・偏好・33業種）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import core_repository
from app.domain.constants import SECTOR33
from app.services.strength_scan import (
    PROFILES,
    STRENGTH_SCORE_VERSION,
    TIMEFRAMES,
    build_view_rows,
    sort_view_rows,
    tier_distribution,
    tier_of,
)

router = APIRouter(prefix="/api/strength", tags=["strength"])

_MAX_TOP = 200


def _load_snapshot() -> tuple[list[dict], dict]:
    repository = core_repository()
    if not repository.exists():
        raise HTTPException(status_code=503, detail={"code": "data_not_initialized"})
    meta = repository.strength_meta()
    if meta is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "strength_snapshot_unavailable",
                "message": "強度断面は未生成です（引け後バッチ完了後に利用可能）",
            },
        )
    return repository.strength_rows_all(), meta


@router.get("/scan")
def strength_scan(
    timeframe: str = Query(default="all"),
    profile: str = Query(default="balanced"),
    top: int = Query(default=20, ge=1, le=_MAX_TOP),
    sector_id: str | None = Query(default=None, description="33業種コード。カンマ区切りで複数可"),
    min_price: float = Query(default=0.0, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    min_avg_turnover: float = Query(default=0.0, ge=0),
    tier: str | None = Query(default=None, pattern="^(S|A|B|C)$"),
    min_score: float | None = Query(default=None, ge=0, le=100),
) -> dict:
    if timeframe not in TIMEFRAMES:
        raise HTTPException(status_code=422, detail={"code": "invalid_timeframe"})
    if profile not in PROFILES:
        raise HTTPException(status_code=422, detail={"code": "invalid_profile"})
    sector_ids: set[str] = set()
    if sector_id:
        sector_ids = {part.strip() for part in sector_id.split(",") if part.strip()}
        unknown = sector_ids - set(SECTOR33)
        if unknown:
            raise HTTPException(status_code=422, detail={"code": "invalid_sector"})

    stored, meta = _load_snapshot()
    view = build_view_rows(stored, meta["regime"], profile=profile)

    # サーバ側フィルタ: 全評価済み母集団に適用（米国版はクライアント側条件が
    # 上位120行にしか届かなかった — 日本版は断面が手元にあるので全量に掛ける）。
    screened = [
        row for row in view
        if (row.get("close") or 0.0) >= min_price
        and (max_price is None or (row.get("close") or 0.0) <= max_price)
        and (min_avg_turnover <= 0 or (row.get("avg_turnover_20d") or 0.0) >= min_avg_turnover)
        and (not sector_ids or row.get("sector33_code") in sector_ids)
    ]
    distribution = tier_distribution(screened, timeframe)
    matched = screened
    if tier is not None:
        matched = [
            row for row in matched
            if row.get("ranking_score") is not None and tier_of(float(row["ranking_score"])) == tier
        ]
    if min_score is not None:
        matched = [
            row for row in matched
            if row.get("ranking_score") is not None and float(row["ranking_score"]) >= min_score
        ]
    sort_view_rows(matched, timeframe)
    limited = matched[: top]
    for rank, row in enumerate(limited, start=1):
        row["selected_view_rank"] = rank

    return {
        "trade_date": meta["trade_date"],
        "built_at": meta["built_at"],
        "score_version": STRENGTH_SCORE_VERSION,
        "params": {
            "timeframe": timeframe, "profile": profile, "top": top,
            "sector_id": sector_id, "min_price": min_price,
            "min_avg_turnover": min_avg_turnover, "tier": tier, "min_score": min_score,
        },
        "market_regime": meta["regime"],
        "universe_count": meta["universe_count"],
        "screened_count": len(screened),
        "matched_count": len(matched),
        "tier_distribution": distribution,
        "rows": [_public_row(row) for row in limited],
    }


def _public_row(row: dict) -> dict:
    details = row.get("details") or {}
    return {
        "canonical_code": row["canonical_code"],
        "display_code": (
            row["canonical_code"][:4]
            if len(row["canonical_code"]) == 5 and row["canonical_code"].endswith("0")
            else row["canonical_code"]
        ),
        "name_ja": details.get("name_ja"),
        "sector33_code": row.get("sector33_code"),
        "sector33_name": details.get("sector33_name"),
        "market_name": details.get("market_name"),
        "close": row.get("close"),
        "change_pct": row.get("change_pct"),
        "intrinsic_score": row.get("intrinsic_score"),
        # ranking_score は互換のため残すが、中身はリスク調整後（= final）。
        # 素点と減点を並べて出し、順位がどう作られたか画面で追えるようにする。
        "ranking_score": row.get("ranking_score"),
        "raw_ranking_score": row.get("raw_ranking_score"),
        "final_ranking_score": row.get("final_ranking_score"),
        "market_fit_score": row.get("market_fit_score"),
        "profile_fit_score": row.get("profile_fit_score"),
        "confidence": row.get("confidence"),
        "ranking_confidence": row.get("ranking_confidence"),
        "score_short": row.get("score_short"),
        "score_mid": row.get("score_mid"),
        "score_long": row.get("score_long"),
        "trend_score": row.get("trend_score"),
        "breakout_quality_score": row.get("breakout_quality_score"),
        "price_action_score": row.get("price_action_score"),
        "global_rank_percentile": row.get("global_rank_percentile"),
        "sector_rank_percentile": row.get("sector_rank_percentile"),
        "avg_turnover_20d": row.get("avg_turnover_20d"),
        "turnover_ratio": row.get("turnover_ratio"),
        "atr_pct": row.get("atr_pct"),
        "ath_proximity": row.get("ath_proximity"),
        "rs_topix_63d": row.get("rs_topix_63d"),
        "ma_alignment_pct": row.get("ma_alignment_pct"),
        "risk_penalty": row.get("risk_penalty"),
        # 信用规制は独立したリスク次元として出す（severity<0 = 判定不能）
        "regulation_level": row.get("regulation_level"),
        "regulation_severity": row.get("regulation_severity"),
        "classification": row.get("classification"),
        "tags": row.get("tags") or [],
        "reasons": row.get("reasons") or [],
        "warnings": row.get("warnings") or [],
        "selected_view_rank": row.get("selected_view_rank"),
        "families": details.get("families") or {},
        "effective_weights": details.get("effective_weights") or {},
        "missing_families": details.get("missing_families") or [],
        "structure": {
            "price_action": details.get("price_action") or {},
            "vol_price": details.get("vol_price") or {},
            "technicals": details.get("technicals") or {},
        },
    }


@router.get("/market")
def strength_market() -> dict:
    _stored, meta = _load_snapshot()
    return {
        "trade_date": meta["trade_date"],
        "built_at": meta["built_at"],
        "market_regime": meta["regime"],
        "universe_count": meta["universe_count"],
    }


@router.get("/profiles")
def strength_profiles() -> dict:
    return {
        "timeframes": list(TIMEFRAMES),
        "profiles": [
            {"id": "conservative", "name": "稳健", "description": "波动惩罚更重、流动性权重更高"},
            {"id": "balanced", "name": "均衡", "description": "默认权重"},
            {"id": "aggressive", "name": "进取", "description": "接受更高波动、突破权重更高"},
        ],
        "presets": [
            {"id": "breakout", "name": "突破进取", "profile": "aggressive", "min_score": 70,
             "description": "进取评分 + 强度分 ≥70"},
            {"id": "lowvol", "name": "低波稳健", "profile": "conservative", "min_score": None,
             "description": "稳健评分（波动惩罚加重）"},
        ],
        "sectors": [
            # 9999（その他）はレーダー/強度の走査対象外なので選択肢から除く。
            {"id": code, "name": name}
            for code, name in sorted(SECTOR33.items())
            if code != "9999"
        ],
        "family_weights": {
            "short": 0.16, "mid": 0.24, "long": 0.14,
            "trend": 0.16, "breakout": 0.15, "price_action": 0.15,
        },
    }
