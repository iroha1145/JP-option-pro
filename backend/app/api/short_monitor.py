"""機関空売り行動モニター API（読み取り専用）。

**ここでは何も計算しない。** スナップショットはワーカーが引け後に作り、
この API は保存済みの行を返すだけ。ページを開くたびに全市場計算が走る、
という事故を構造的に防ぐ。

どのフィールドにも `total_short_*` は無い。J-Quants の機関空売り報告は
**公開開示に達した分しか映さない**ので、名前は `visible` / `reported` で
統一する。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.api.deps import core_repository
from app.domain.symbols import display_code, normalize_input_code
from app.services.short_monitor import explain
from app.services.short_monitor.radar_link import (
    CROWDING_LINK_ENABLED,
    CROWDING_VALIDATION,
    MAX_PRIORITY_SHIFT,
    PRIORITY_LINK_ENABLED,
)
from app.services.short_monitor.scoring import SCORE_VALIDATED, SCORE_VERSION, VALIDATION
from app.services.short_monitor.snapshot import SNAPSHOT_VERSION
from app.services.short_monitor.states import (
    GATES_VALIDATED,
    ORDERED_STATES,
    STATE_ABSORPTION,
    STATE_COVERING_START,
    STATE_DIVERGENCE_FAILED,
    STATE_LOW_CONFLICT,
    STATE_SQUEEZE_CONFIRMED,
)

router = APIRouter(prefix="/api/short-monitor", tags=["short-monitor"])

#: v3: 回補開始・挤空確認が informed 口径の減少を要求（sbs-v3）、行に
#: `informed` / `parked_below_count` / `reporter_classes` を追加、status に
#: 拥挤度叠加のスイッチと検証状態を追加。
SHORT_MONITOR_API_VERSION = "jp-short-monitor-v3"

#: 画面の各ビューが要求する状態・並び順。ここに無い名前は受け付けない。
VIEWS: dict[str, dict[str, Any]] = {
    "low_conflict": {
        "states": [STATE_LOW_CONFLICT],
        "order_by": "low_position_score",
    },
    "absorption": {
        "states": [STATE_ABSORPTION],
        "order_by": "absorption_score",
    },
    "covering": {
        "states": [STATE_COVERING_START, STATE_SQUEEZE_CONFIRMED],
        "order_by": "covering_score",
    },
    "reentry": {
        "states": None, "flags": ["reentry"], "order_by": "monitor_priority",
    },
    "rotation": {
        "states": None, "flags": ["rotation"], "order_by": "rotation_score",
    },
    "squeeze": {
        "states": [STATE_SQUEEZE_CONFIRMED], "order_by": "monitor_priority",
    },
    "divergence_failed": {
        "states": [STATE_DIVERGENCE_FAILED], "order_by": "pressure_adv20_20d",
    },
    "all": {"states": None, "order_by": "monitor_priority"},
}

#: 画面に常時出す語義の注意書き。ここを消さない。
DISCLOSURE_NOTE = (
    "本页面展示达到公开披露条件的机构空卖持仓，不代表市场全部空头仓位。"
    "跌破公开门槛不代表仓位归零。"
)


def _repository():
    repository = core_repository()
    if not repository.exists():
        raise HTTPException(status_code=503, detail={"code": "data_not_initialized"})
    return repository


def _as_of(repository, requested: str | None) -> str | None:
    if requested:
        return requested
    return repository.latest_short_behavior_date()


def _run_token(repository, as_of: str | None) -> str:
    """スナップショット世代の識別子。同じ日を訂正で作り直しても ETag が変わる。"""

    run = repository.latest_short_monitor_run(as_of) if as_of else None
    return str((run or {}).get("run_id") or "")


def _etag(*parts: Any) -> str:
    seed = "|".join(str(part) for part in parts)
    return '"' + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:32] + '"'


def _maybe_304(request: Request, response: Response, etag: str) -> bool:
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=60"
    return request.headers.get("if-none-match") == etag


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _flags(row: dict[str, Any]) -> list[str]:
    try:
        return json.loads(row.get("flags_json") or "[]")
    except ValueError:
        return []


def _components(row: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(row.get("components_json") or "{}")
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _informed_view(components: dict[str, Any]) -> dict[str, Any] | None:
    """informed 口径（国内証券・集合名義を除いた報告主体）の要約。"""

    informed = components.get("informed")
    if not isinstance(informed, dict):
        return None
    pressure_20 = informed.get("pressure_20d") or {}
    pressure_5 = informed.get("pressure_5d") or {}
    return {
        "institution_count": informed.get("institution_count"),
        "visible_short_ratio": informed.get("visible_short_ratio"),
        "pressure_adv20_20d": pressure_20.get("pressure_adv20") if isinstance(pressure_20, dict) else None,
        "pressure_adv20_5d": pressure_5.get("pressure_adv20") if isinstance(pressure_5, dict) else None,
        "entry_count_20d": informed.get("entry_count_20d"),
        "reentry_count_20d": informed.get("reentry_count_20d"),
        "reduction_count_20d": informed.get("reduction_count_20d"),
    }


def _row_view(row: dict[str, Any]) -> dict[str, Any]:
    """1 行分の説明可能な形。**点数だけを返さない。**"""

    code = row.get("canonical_code") or ""
    components = _components(row)
    return {
        "canonical_code": code,
        "display_code": row.get("display_code") or display_code(code),
        "name": row.get("name_ja"),
        "market_code": row.get("market_code"),
        "market_name": row.get("market_name"),
        "sector33_code": row.get("sector33_code"),
        "sector33_name": row.get("sector33_name"),
        "as_of_date": row.get("as_of_date"),
        "close": row.get("close"),
        "drawdown_52w": row.get("drawdown_52w"),
        "price_percentile_252": row.get("price_percentile_252"),
        # 名前に visible / reported を必ず残す（総空売り残高ではない）。
        # visible_* = 新鮮な報告義務中だけの和（125 営業日は運用上の目安）、
        # reported_in_scope_* = 最終報告がまだ公開範囲内の全機関の和（公式
        # ルール口径）。どちらか片方だけを出すと、もう片方の意味に化ける。
        "visible_short_ratio": row.get("visible_short_ratio"),
        "visible_short_shares": row.get("visible_short_shares"),
        "reported_in_scope_ratio": row.get("reported_in_scope_ratio"),
        "reported_in_scope_shares": row.get("reported_in_scope_shares"),
        "visible_institution_count": row.get("visible_institution_count"),
        "below_threshold_count": row.get("below_threshold_count"),
        "stale_reporting_count": row.get("stale_reporting_count"),
        "unknown_institution_count": row.get("unknown_institution_count"),
        "largest_institution_ratio": row.get("largest_institution_ratio"),
        "concentration": row.get("concentration"),
        "ratio_change_5d": row.get("ratio_change_5d"),
        "ratio_change_20d": row.get("ratio_change_20d"),
        "shares_change_20d": row.get("shares_change_20d"),
        "pressure_adv20_5d": row.get("pressure_adv20_5d"),
        "pressure_adv20_20d": row.get("pressure_adv20_20d"),
        "visible_days_to_cover": row.get("visible_days_to_cover"),
        "rel_topix_20d": row.get("rel_topix_20d"),
        "rel_sector_20d": row.get("rel_sector_20d"),
        "entry_count_20d": row.get("entry_count_20d"),
        "reentry_count_20d": row.get("reentry_count_20d"),
        "reduction_count_20d": row.get("reduction_count_20d"),
        "threshold_exit_count_20d": row.get("threshold_exit_count_20d"),
        "scores": {
            "low_position": row.get("low_position_score"),
            "short_pressure": row.get("short_pressure_score"),
            "price_damage": row.get("price_damage_score"),
            "absorption": row.get("absorption_score"),
            "covering": row.get("covering_score"),
            "rotation": row.get("rotation_score"),
            "catalyst": row.get("catalyst_score"),
            "risk": row.get("risk_score"),
        },
        "behavior_score": row.get("behavior_score"),
        "monitor_priority": row.get("monitor_priority"),
        "data_confidence": row.get("data_confidence"),
        "primary_state": row.get("primary_state"),
        "flags": _flags(row),
        # informed 口径 / 潜伏空頭 / 報告主体クラス（v3）。古いスナップショット
        # 行には無いので None。
        "informed": _informed_view(components),
        "parked_below_count": components.get("parked_below_count"),
        "reporter_classes": components.get("reporter_classes"),
        "combined_visible_days_to_cover": components.get("combined_visible_days_to_cover"),
        "algorithm_version": row.get("algorithm_version"),
    }


@router.get("/overview")
def overview(request: Request, response: Response, date: str | None = Query(default=None)) -> dict:
    repository = _repository()
    as_of = _as_of(repository, date)
    if not as_of:
        return {
            "as_of_date": None, "note": DISCLOSURE_NOTE, "coverage": None,
            "states": {}, "api_version": SHORT_MONITOR_API_VERSION,
        }
    state = repository.sync_state("short_behavior") or {}
    coverage = repository.short_behavior_coverage(as_of)
    counts = repository.short_behavior_state_counts(as_of)
    etag = _etag(
        "overview", as_of, state.get("last_success_at"),
        _run_token(repository, as_of), SNAPSHOT_VERSION,
    )
    if _maybe_304(request, response, etag):
        response.status_code = 304
        return {}
    return {
        "as_of_date": as_of,
        "synced_at": state.get("last_success_at"),
        "coverage": coverage,
        "states": {name: counts.get(name, 0) for name in ORDERED_STATES},
        "note": DISCLOSURE_NOTE,
        "algorithm_version": SNAPSHOT_VERSION,
        "score_version": SCORE_VERSION,
        # 検証の状況を API 自身が名乗る。「まだやっていない」と「やったが
        # 通らなかった」は別のことなので、結果も一緒に返す。
        "validated": {"gates": GATES_VALIDATED, "score": SCORE_VALIDATED},
        "validation": VALIDATION,
        # 検証を通るまでレーダーの並び順には一切影響しない（表示・絞り込み・
        # 影子分のみ）。ここが False の間、priority_shift は常に 0。
        "radar_link": {
            "enabled": PRIORITY_LINK_ENABLED, "max_shift": MAX_PRIORITY_SHIFT,
            "crowding_enabled": CROWDING_LINK_ENABLED, "crowding_validation": CROWDING_VALIDATION,
        },
        "api_version": SHORT_MONITOR_API_VERSION,
    }


@router.get("/rankings")
def rankings(
    request: Request,
    response: Response,
    view: str = Query(default="all"),
    date: str | None = Query(default=None),
    states: str | None = Query(default=None),
    flags: str | None = Query(default=None),
    markets: str | None = Query(default=None),
    sectors: str | None = Query(default=None),
    codes: str | None = Query(default=None),
    institutions: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    min_turnover: float | None = Query(default=None, ge=0.0),
    min_score: float | None = Query(default=None, ge=0.0, le=100.0),
    order_by: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    repository = _repository()
    if view not in VIEWS:
        raise HTTPException(status_code=400, detail={"code": "unknown_view", "view": view})
    as_of = _as_of(repository, date)
    if not as_of:
        return {"as_of_date": None, "rows": [], "total": 0, "note": DISCLOSURE_NOTE}

    preset = VIEWS[view]
    state_filter = _csv(states) or preset.get("states")
    flag_filter = _csv(flags) or preset.get("flags") or []
    order = order_by or preset.get("order_by") or "monitor_priority"

    etag = _etag(
        "rankings", as_of, view, states, flags, markets, sectors, codes, institutions,
        min_confidence, min_turnover, min_score, order, limit, offset,
        _run_token(repository, as_of), SNAPSHOT_VERSION,
    )
    if _maybe_304(request, response, etag):
        response.status_code = 304
        return {}

    rows, total = repository.short_behavior_rankings(
        as_of,
        states=state_filter,
        flags=flag_filter,
        markets=_csv(markets) or None,
        sectors=_csv(sectors) or None,
        codes=[normalize_input_code(c) or c for c in _csv(codes)] or None,
        institutions=_csv(institutions) or None,
        min_confidence=min_confidence,
        min_turnover=min_turnover,
        min_score=min_score,
        order_by=order,
        limit=limit,
        offset=offset,
    )
    return {
        "as_of_date": as_of,
        "view": view,
        "order_by": order,
        "total": total,
        "limit": limit,
        "offset": offset,
        "rows": [_row_view(row) for row in rows],
        "note": DISCLOSURE_NOTE,
        "api_version": SHORT_MONITOR_API_VERSION,
    }


@router.get("/stocks/{code}")
def stock_detail(
    request: Request, response: Response, code: str, date: str | None = Query(default=None),
) -> dict:
    repository = _repository()
    canonical = normalize_input_code(code)
    if not canonical:
        raise HTTPException(status_code=404, detail={"code": "unknown_symbol"})
    as_of = _as_of(repository, date)
    if not as_of:
        raise HTTPException(status_code=503, detail={"code": "short_monitor_not_run"})

    snapshot = repository.short_behavior_snapshot(canonical, as_of)
    if snapshot is None:
        raise HTTPException(status_code=404, detail={"code": "no_snapshot", "as_of_date": as_of})

    etag = _etag("stock", canonical, as_of, _run_token(repository, as_of), SNAPSHOT_VERSION)
    if _maybe_304(request, response, etag):
        response.status_code = 304
        return {}

    security = repository.get_security(canonical) or {}
    holders = repository.short_position_last_known_for_code(canonical)
    history = repository.short_behavior_history(canonical)
    view = _row_view({**snapshot, **{
        "display_code": security.get("display_code"),
        "name_ja": security.get("name_ja"),
        "market_code": security.get("market_code"),
        "market_name": security.get("market_name"),
        "sector33_code": security.get("sector33_code"),
        "sector33_name": security.get("sector33_name"),
    }})
    try:
        components = json.loads(snapshot.get("components_json") or "{}")
    except ValueError:
        components = {}

    return {
        **view,
        "components": components,
        "holders": [_holder_view(row) for row in holders],
        "history": history,
        "explanation": explain.describe(view, holders),
        "note": DISCLOSURE_NOTE,
        "api_version": SHORT_MONITOR_API_VERSION,
    }


def _holder_view(row: dict[str, Any]) -> dict[str, Any]:
    known = bool(row.get("exact_position_known"))
    return {
        "legal_id": row.get("legal_id"),
        "name": row.get("display_name") or row.get("legal_id"),
        "group_name": row.get("group_name"),
        "last_reported_ratio": row.get("last_reported_ratio"),
        "last_reported_shares": row.get("last_reported_shares"),
        "last_position_date": row.get("last_position_date"),
        "last_published_date": row.get("last_published_date"),
        "visibility_status": row.get("visibility_status"),
        # 閾値を割ったのか、割らないまま報告が止まったのか。別の事象。
        "stale_reporting": bool(row.get("stale_reporting")),
        # 正確なのは **その仓位日時点** の値。今日の建玉は（直近報告でも）
        # 報告以後に動いていれば分からない。旧名 exact_position_known は
        # 「今も正確」と読めてしまうので改名（値は同じ）。
        "exact_at_position_date": known,
        "state_age_trading_days": row.get("state_age_trading_days"),
        # 同一機関の複数ファンド連鎖の内訳
        "chain_count": row.get("chain_count"),
        "unknown_chain_count": row.get("unknown_chain_count"),
        "is_hedge_disclosed": bool(row.get("is_hedge_disclosed")),
        "mapping_confidence": row.get("mapping_confidence"),
    }


@router.get("/stocks/{code}/events")
def stock_events(
    code: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    repository = _repository()
    canonical = normalize_input_code(code)
    if not canonical:
        raise HTTPException(status_code=404, detail={"code": "unknown_symbol"})
    rows = repository.short_position_events_for_code(canonical, limit=limit, offset=offset)
    total = repository.short_position_event_count(canonical)
    return {
        "canonical_code": canonical,
        "total": total,
        "limit": limit,
        "offset": offset,
        "events": [_event_view(row) for row in rows],
        "note": DISCLOSURE_NOTE,
    }


def _event_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": row.get("event_id"),
        "institution": row.get("raw_holder_name"),
        "investment_fund_name": row.get("investment_fund_name"),
        "legal_id": row.get("legal_id"),
        "group_id": row.get("group_id"),
        "position_date": row.get("position_date"),
        "published_date": row.get("published_date"),
        "effective_trade_date": row.get("effective_trade_date"),
        "short_ratio": row.get("short_ratio"),
        "short_shares": row.get("short_shares"),
        "previous_ratio": row.get("previous_ratio"),
        "ratio_delta": row.get("ratio_delta"),
        "event_type": row.get("event_type"),
        "visibility_status": row.get("visibility_status"),
        "correction_status": row.get("correction_status"),
        "is_hedge_disclosed": bool(row.get("is_hedge_disclosed")),
        "mapping_confidence": row.get("mapping_confidence"),
    }


@router.get("/institutions")
def institutions(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    repository = _repository()
    rows = repository.institution_directory(limit=limit)
    return {
        "institutions": [
            {
                "legal_id": row.get("legal_id"),
                "name": row.get("display_name"),
                "group_id": row.get("group_id"),
                "group_name": row.get("group_name"),
                "report_count": row.get("report_count"),
                "first_seen_date": row.get("first_seen_date"),
                "last_seen_date": row.get("last_seen_date"),
            }
            for row in rows
        ],
        "note": "同じグループでも法的主体は別々に数えている。",
    }


@router.get("/status")
def status() -> dict:
    repository = _repository()
    state = repository.sync_state("short_behavior") or {}
    positions = repository.sync_state("reported_short_positions") or {}
    return {
        "as_of_date": repository.latest_short_behavior_date(),
        "last_success_at": state.get("last_success_at"),
        "rows_total": state.get("rows_total"),
        "source_through": positions.get("data_through"),
        "algorithm_version": SNAPSHOT_VERSION,
        "score_version": SCORE_VERSION,
        "validated": {"gates": GATES_VALIDATED, "score": SCORE_VALIDATED},
        "validation": VALIDATION,
        "radar_link": {
            "enabled": PRIORITY_LINK_ENABLED, "max_shift": MAX_PRIORITY_SHIFT,
            "crowding_enabled": CROWDING_LINK_ENABLED, "crowding_validation": CROWDING_VALIDATION,
        },
        "note": DISCLOSURE_NOTE,
    }


__all__ = ["DISCLOSURE_NOTE", "SHORT_MONITOR_API_VERSION", "VIEWS", "router"]
