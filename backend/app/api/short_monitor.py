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
from app.repositories.core import FUND_PRODUCT_CATEGORIES, REIT_PRODUCT_CATEGORY
from app.services.short_monitor import explain
from app.services.short_monitor.radar_link import (
    CROWDING_LINK_ENABLED,
    CROWDING_VALIDATION,
    PRIORITY_LINK_ENABLED,
)
from app.services.short_monitor.snapshot import SNAPSHOT_VERSION
from app.services.short_monitor.states import (
    CROWDING_HIGH,
    CROWDING_LOW,
    CROWDING_MID,
    CROWDING_RULES,
    EVIDENCE,
    FLAG_NEW_ENTRY,
    FLAG_REENTRY,
    ORDERED_STATES,
    STATE_BUILDING,
    STATE_COVERING,
    crowding_level,
)

router = APIRouter(prefix="/api/short-monitor", tags=["short-monitor"])

#: v4: 点数（行動分・分項・監視優先度）と旧 6 状態を廃止。行に
#: `crowding_level` / `security_kind` / `last_report_age_days` /
#: `confidence_reasons` を追加、状態は building / covering / mixed / steady /
#: no_signal。ビューは事実の列で並べる。ETF・ETN は既定で外す。
SHORT_MONITOR_API_VERSION = "jp-short-monitor-v4"

#: 画面の各ビュー。**並び順はどれも事実の列**（合成した点数では並べない）。
#: ここに無い名前は受け付けない。
VIEWS: dict[str, dict[str, Any]] = {
    # 公開持仓比率が高い順。既定のビュー。
    "crowded": {"visible_only": True, "order_by": "visible_short_ratio", "descending": True},
    "building": {"states": [STATE_BUILDING], "order_by": "ratio_change_20d", "descending": True},
    "covering": {"states": [STATE_COVERING], "order_by": "ratio_change_20d", "descending": False},
    "entries": {
        "any_flags": [FLAG_NEW_ENTRY, FLAG_REENTRY],
        "order_by": "ratio_change_20d", "descending": True,
    },
    "days_to_cover": {"visible_only": True, "order_by": "visible_days_to_cover", "descending": True},
    "all": {"order_by": "visible_short_ratio", "descending": True},
}

#: 並べ替えに使える列。**どれも事実の列。** ここに無い名前はビューの既定に戻す
#: （応答の `order_by` にも実際に使った列を返す —— 受け取った文字列を鸚鵡返し
#: にすると、並びと表示が食い違う）。
ORDER_COLUMNS = frozenset({
    "visible_short_ratio", "visible_institution_count", "ratio_change_20d", "ratio_change_5d",
    "pressure_adv20_20d", "visible_days_to_cover", "drawdown_52w", "rel_topix_20d",
})

#: `min_crowding` → (機関数の下限, 比率の下限)。1 は「公開持仓がある」だけ。
_CROWDING_FLOORS: dict[int, tuple[int, float]] = {
    level: (count, ratio) for level, count, ratio in CROWDING_RULES
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


def _security_kind(product_category: Any) -> str:
    category = str(product_category or "")
    if category in FUND_PRODUCT_CATEGORIES:
        return "fund"
    return "reit" if category == REIT_PRODUCT_CATEGORY else "stock"


def _row_view(row: dict[str, Any]) -> dict[str, Any]:
    """1 行分。**事実の列と、固定の規則で決まる 2 つの分類だけ。**"""

    code = row.get("canonical_code") or ""
    components = _components(row)
    confidence = components.get("confidence")
    return {
        "canonical_code": code,
        "display_code": row.get("display_code") or display_code(code),
        "name": row.get("name_ja"),
        "market_code": row.get("market_code"),
        "market_name": row.get("market_name"),
        "sector33_code": row.get("sector33_code"),
        "sector33_name": row.get("sector33_name"),
        "security_kind": _security_kind(row.get("product_category")),
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
        "combined_visible_days_to_cover": components.get("combined_visible_days_to_cover"),
        "rel_topix_20d": row.get("rel_topix_20d"),
        "rel_sector_20d": row.get("rel_sector_20d"),
        "entry_count_20d": row.get("entry_count_20d"),
        "reentry_count_20d": row.get("reentry_count_20d"),
        "reduction_count_20d": row.get("reduction_count_20d"),
        "threshold_exit_count_20d": row.get("threshold_exit_count_20d"),
        # 拥挤度は保存値ではなく 2 つの列から毎回決める（規則が 1 か所で済む）。
        "crowding_level": crowding_level(
            row.get("visible_institution_count"), row.get("visible_short_ratio"),
        ),
        "last_report_age_days": components.get("days_since_last_report"),
        "data_confidence": row.get("data_confidence"),
        "confidence_reasons": (
            list(confidence.get("reasons") or []) if isinstance(confidence, dict) else []
        ),
        "primary_state": row.get("primary_state"),
        "flags": _flags(row),
        "informed": _informed_view(components),
        "parked_below_count": components.get("parked_below_count"),
        "reporter_classes": components.get("reporter_classes"),
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
    coverage = repository.short_behavior_coverage(
        as_of, crowding_rules=[(count, ratio) for _level, count, ratio in CROWDING_RULES],
    )
    counts = repository.short_behavior_state_counts(as_of)
    etag = _etag(
        "overview", as_of, state.get("last_success_at"),
        _run_token(repository, as_of), SNAPSHOT_VERSION, SHORT_MONITOR_API_VERSION,
    )
    if _maybe_304(request, response, etag):
        response.status_code = 304
        return {}
    return {
        "as_of_date": as_of,
        "synced_at": state.get("last_success_at"),
        "coverage": {
            "covered": coverage["covered"],
            "with_visible_short": coverage["with_visible_short"],
            "low_confidence": coverage["low_confidence"],
        },
        "states": {name: counts.get(name, 0) for name in ORDERED_STATES},
        "crowding": _crowding_counts(coverage),
        "note": DISCLOSURE_NOTE,
        "algorithm_version": SNAPSHOT_VERSION,
        # 拥挤度について分かっていることと、その限界。API 自身が名乗る。
        "evidence": EVIDENCE,
        # レーダーの並び順には一切影響しない（表示と絞り込みのみ）。
        "radar_link": _radar_link_view(),
        "api_version": SHORT_MONITOR_API_VERSION,
    }


def _crowding_counts(coverage: dict[str, Any]) -> dict[str, int]:
    """段ごとの件数。リポジトリは「その段以上」の累積で返すので差を取る。"""

    cumulative = dict(zip(
        [level for level, _count, _ratio in CROWDING_RULES], coverage.get("crowding_at_least") or [],
    ))
    high = int(cumulative.get(CROWDING_HIGH, 0))
    mid_or_more = int(cumulative.get(CROWDING_MID, 0))
    with_visible = int(coverage.get("with_visible_short") or 0)
    return {
        "high": high,
        "mid": max(0, mid_or_more - high),
        "low": max(0, with_visible - mid_or_more),
    }


def _radar_link_view() -> dict[str, Any]:
    return {
        "enabled": PRIORITY_LINK_ENABLED,
        "crowding_enabled": CROWDING_LINK_ENABLED,
        "crowding_validation": CROWDING_VALIDATION,
    }


@router.get("/rankings")
def rankings(
    request: Request,
    response: Response,
    view: str = Query(default="crowded"),
    date: str | None = Query(default=None),
    states: str | None = Query(default=None),
    flags: str | None = Query(default=None),
    markets: str | None = Query(default=None),
    sectors: str | None = Query(default=None),
    codes: str | None = Query(default=None),
    institutions: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    min_turnover: float | None = Query(default=None, ge=0.0),
    min_crowding: int | None = Query(default=None, ge=0, le=CROWDING_HIGH),
    include_funds: bool = Query(default=False),
    order_by: str | None = Query(default=None),
    order_dir: str | None = Query(default=None, pattern="^(asc|desc)$"),
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
    order = order_by if order_by in ORDER_COLUMNS else preset["order_by"]
    descending = (order_dir == "desc") if order_dir else bool(preset["descending"])
    crowding = int(min_crowding or 0)

    etag = _etag(
        "rankings", as_of, view, states, flags, markets, sectors, codes, institutions,
        min_confidence, min_turnover, crowding, include_funds, order, descending, limit, offset,
        _run_token(repository, as_of), SNAPSHOT_VERSION, SHORT_MONITOR_API_VERSION,
    )
    if _maybe_304(request, response, etag):
        response.status_code = 304
        return {}

    rows, total = repository.short_behavior_rankings(
        as_of,
        states=state_filter,
        flags=_csv(flags) or None,
        any_flags=preset.get("any_flags"),
        markets=_csv(markets) or None,
        sectors=_csv(sectors) or None,
        codes=[normalize_input_code(c) or c for c in _csv(codes)] or None,
        institutions=_csv(institutions) or None,
        min_confidence=min_confidence,
        min_turnover=min_turnover,
        visible_only=bool(preset.get("visible_only")) or crowding >= CROWDING_LOW,
        crowding_floor=_CROWDING_FLOORS.get(crowding),
        include_funds=include_funds,
        order_by=order,
        descending=descending,
        limit=limit,
        offset=offset,
    )
    return {
        "as_of_date": as_of,
        "view": view,
        "order_by": order,
        "order_dir": "desc" if descending else "asc",
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

    etag = _etag(
        "stock", canonical, as_of, _run_token(repository, as_of), SNAPSHOT_VERSION,
        SHORT_MONITOR_API_VERSION,
    )
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
        "product_category": security.get("product_category"),
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
        "evidence": EVIDENCE,
        "radar_link": _radar_link_view(),
        "note": DISCLOSURE_NOTE,
        "api_version": SHORT_MONITOR_API_VERSION,
    }


__all__ = ["DISCLOSURE_NOTE", "SHORT_MONITOR_API_VERSION", "VIEWS", "router"]
