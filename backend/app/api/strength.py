"""強度スキャン API — 夜間断面の読み出し + 要求時の profile/market 重ね掛け。

米国版 /api/strength/* との対応:
- GET /scan     … スキャン実行（保存済み断面に対するビュー計算; 全評価済み
                   母集団へサーバ側でフィルタを掛けるので「上位N名内だけの
                   絞り込み」問題は日本版には存在しない）
- GET /market   … 市場レジーム 6 次元
- GET /profiles … 選択肢メタ（周期・偏好・33業種）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.api.account import current_account
from app.access import request_is_owner_session
from app.api.deps import app_store, core_repository
from app.domain.constants import SECTOR33
from app.domain.timeutil import iso_date, now_jst, today_jst
from app.personal_config import get_personal_config
from app.repositories.base import utc_now_iso
from app.services.a0_ranking import (
    a0_request_can_score,
    annotate_a0_row,
    annotate_production_row,
    apply_a0_mid_long,
)
from app.services.algorithm_modes import (
    A0_ALGORITHM,
    A0_UNAVAILABLE,
    A0_VERSION,
    ConflictingAlgorithmError,
    PRODUCTION_ALGORITHM,
    UnknownAlgorithmError,
    resolve_screener_algorithm,
)
from app.services.publication import (
    evaluate_freshness,
    expected_trade_date,
    strength_etag,
)
from app.services.strength_scan import (
    PROFILES,
    STRENGTH_SCORE_VERSION,
    TIMEFRAMES,
    build_view_rows,
    sort_view_rows,
    tier_distribution,
    tier_of,
)
from app.services.view_preferences import (
    preference_principal,
    read_admin_defaults,
    read_view_preferences,
)

router = APIRouter(prefix="/api/strength", tags=["strength"])

_MAX_TOP = 200


def _expected_trade_date(repository) -> str | None:
    config = get_personal_config()
    return expected_trade_date(
        today=iso_date(today_jst()),
        now=now_jst(),
        batch_hhmm=config.sync.daily_batch_time_jst,
        latest_trading_day=repository.latest_trading_day,
        session_status=repository.is_trading_day,
    )


def _publication_fields(meta: dict, *, expected: str | None) -> dict:
    stored_version = meta.get("stored_score_version")
    if stored_version is None:
        stored_version = meta.get("score_version")
    coverage = meta.get("coverage") or {}
    freshness = evaluate_freshness(
        stored_trade_date=meta.get("trade_date"),
        expected=expected,
        stored_score_version=stored_version,
        current_score_version=STRENGTH_SCORE_VERSION,
        coverage=coverage,
    )
    return {
        "queried_at": utc_now_iso(),
        "publication_id": meta.get("publication_id"),
        "stored_score_version": stored_version,
        "expected_score_version": STRENGTH_SCORE_VERSION,
        "score_compatible": freshness["score_compatible"],
        "expected_trade_date": expected,
        "input_data_through": meta.get("input_data_through") or meta.get("trade_date"),
        "index_input_date": meta.get("index_input_date"),
        "coverage": coverage,
        "freshness": freshness["freshness"],
        "calendar_state": freshness["calendar_state"],
        "version_state": freshness["version_state"],
        "query_kind": "filter",
    }


def _maybe_304(request: Request, response: Response, etag: str) -> bool:
    response.headers["ETag"] = f'"{etag}"'
    response.headers["Cache-Control"] = "private, must-revalidate"
    incoming = request.headers.get("if-none-match")
    if incoming and incoming.strip() in {etag, f'"{etag}"'}:
        response.status_code = 304
        return True
    return False


def _request_screener_resolution(
    request: Request,
    *,
    ranking_algorithm: str | None,
    timeframe: str,
    profile: str,
):
    store = app_store()
    defaults = read_admin_defaults(store)
    account = current_account(request)
    if account is not None:
        principal = preference_principal("account", account.user_id)
    elif request_is_owner_session(request):
        principal = preference_principal("owner", None)
    else:
        principal = None
    user_choice = None
    if principal:
        user_choice = read_view_preferences(store, principal).screener_ranking_algorithm
    explicit = ranking_algorithm is not None
    return resolve_screener_algorithm(
        requested=ranking_algorithm,
        user_choice=user_choice,
        admin_default=defaults.get("screener_ranking_algorithm"),
        timeframe=timeframe,
        profile=profile,
        explicit_request=explicit,
    )


def _view_identity(
    *,
    resolution,
    timeframe: str,
    profile: str,
    top: int,
    sector_id: str | None,
    min_price: float,
    max_price: float | None,
    min_avg_turnover: float,
    tier: str | None,
    min_score: float | None,
) -> str:
    return "|".join(
        (
            resolution.effective,
            resolution.version,
            timeframe,
            profile,
            str(top),
            sector_id or "",
            str(min_price),
            "" if max_price is None else str(max_price),
            str(min_avg_turnover),
            tier or "",
            "" if min_score is None else str(min_score),
        )
    )


def _load_snapshot() -> tuple[list[dict], dict]:
    repository = core_repository()
    if not repository.exists():
        raise HTTPException(status_code=503, detail={"code": "data_not_initialized"})
    snapshot = repository.strength_snapshot()
    if snapshot is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "strength_snapshot_unavailable",
                "message": "強度断面は未生成です（引け後バッチ完了後に利用可能）",
            },
        )
    return snapshot


@router.get("/scan")
def strength_scan(
    request: Request,
    response: Response,
    timeframe: str = Query(default="all"),
    profile: str = Query(default="balanced"),
    top: int = Query(default=20, ge=1, le=_MAX_TOP),
    sector_id: str | None = Query(default=None, description="33業種コード。カンマ区切りで複数可"),
    min_price: float = Query(default=0.0, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    min_avg_turnover: float = Query(default=0.0, ge=0),
    tier: str | None = Query(default=None, pattern="^(S|A|B|C)$"),
    min_score: float | None = Query(default=None, ge=0, le=100),
    ranking_algorithm: str | None = Query(default=None),
) -> dict:
    if timeframe not in TIMEFRAMES:
        raise HTTPException(status_code=422, detail={"code": "invalid_timeframe"})
    if profile not in PROFILES:
        raise HTTPException(status_code=422, detail={"code": "invalid_profile"})
    try:
        resolution = _request_screener_resolution(
            request, ranking_algorithm=ranking_algorithm, timeframe=timeframe, profile=profile
        )
    except UnknownAlgorithmError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "family": exc.family, "value": exc.value},
        ) from exc
    except ConflictingAlgorithmError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "algorithm": exc.algorithm, "message": str(exc)},
        ) from exc
    sector_ids: set[str] = set()
    if sector_id:
        sector_ids = {part.strip() for part in sector_id.split(",") if part.strip()}
        unknown = sector_ids - set(SECTOR33)
        if unknown:
            raise HTTPException(status_code=422, detail={"code": "invalid_sector"})

    stored, meta = _load_snapshot()
    repository = core_repository()
    expected = _expected_trade_date(repository)
    extra = _publication_fields(meta, expected=expected)
    view_identity = _view_identity(
        resolution=resolution,
        timeframe=timeframe,
        profile=profile,
        top=top,
        sector_id=sector_id,
        min_price=min_price,
        max_price=max_price,
        min_avg_turnover=min_avg_turnover,
        tier=tier,
        min_score=min_score,
    )
    etag = strength_etag(
        publication_id=extra.get("publication_id"),
        stored_score_version=extra.get("stored_score_version"),
        expected_trade_date_value=expected,
        freshness={"freshness": extra["freshness"], "calendar_state": extra["calendar_state"]},
        universe_count=int(meta.get("universe_count") or 0),
        view_identity=view_identity,
    )
    if _maybe_304(request, response, etag):
        return {}
    view = build_view_rows(list(stored), meta["regime"], profile=profile)

    # サーバ側フィルタ: 全評価済み母集団に適用してから並べ、最後に Top-N。
    screened = [
        dict(row) for row in view
        if (row.get("close") or 0.0) >= min_price
        and (max_price is None or (row.get("close") or 0.0) <= max_price)
        and (min_avg_turnover <= 0 or (row.get("avg_turnover_20d") or 0.0) >= min_avg_turnover)
        and (not sector_ids or row.get("sector33_code") in sector_ids)
    ]
    distribution = tier_distribution(screened, timeframe)
    matched = list(screened)
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
    a0_status = None
    sort_basis = resolution.score_basis
    effective = resolution.effective
    if effective == A0_ALGORITHM:
        a0_status = "active" if a0_request_can_score(matched) else A0_UNAVAILABLE
        matched = apply_a0_mid_long(matched)
    else:
        sort_view_rows(matched, timeframe)
        matched = [annotate_production_row(row) for row in matched]
        for rank, row in enumerate(matched, start=1):
            row["selected_view_rank"] = rank
    limited = matched[: top]

    return {
        "trade_date": meta["trade_date"],
        "built_at": meta["built_at"],
        "score_version": extra.get("stored_score_version"),
        **extra,
        **resolution.as_public_dict(),
        "a0_status": a0_status,
        "sort_basis": sort_basis,
        "params": {
            "timeframe": timeframe, "profile": profile, "top": top,
            "sector_id": sector_id, "min_price": min_price, "max_price": max_price,
            "min_avg_turnover": min_avg_turnover, "tier": tier, "min_score": min_score,
            "ranking_algorithm": ranking_algorithm,
            "effective_algorithm": effective,
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
        "sort_score": row.get("sort_score"),
        "sort_basis": row.get("sort_basis"),
        "sort_algorithm": row.get("sort_algorithm"),
        "sort_algorithm_version": row.get("sort_algorithm_version"),
        "a0_score": row.get("a0_score"),
        "a0_available": row.get("a0_available"),
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
    extra = _publication_fields(meta, expected=_expected_trade_date(core_repository()))
    return {
        "trade_date": meta["trade_date"],
        "built_at": meta["built_at"],
        "market_regime": meta["regime"],
        "universe_count": meta["universe_count"],
        **extra,
        "score_version": extra.get("stored_score_version"),
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
        "algorithms": [
            {
                "id": PRODUCTION_ALGORITHM,
                "name": "原版综合",
                "version": STRENGTH_SCORE_VERSION,
                "default": True,
            },
            {
                "id": A0_ALGORITHM,
                "name": "A0 中长期",
                "version": A0_VERSION,
                "supported_timeframe": "all",
                "supported_profile": "balanced",
                "default": False,
            },
        ],
    }
