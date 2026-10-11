"""個別銘柄 API: 検索・概要・チャート。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import core_repository
from app.domain.symbols import display_code, normalize_input_code
from app.services.stock_research import resolve_code, stock_chart, stock_overview

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=40), limit: int = 20) -> dict:
    repository = core_repository()
    if not repository.exists():
        return {"query": q, "results": []}
    results = repository.search_securities(q, limit=max(1, min(50, limit)))
    return {
        "query": q,
        "results": [
            {
                "canonical_code": row["canonical_code"],
                "display_code": row["display_code"],
                "name_ja": row.get("name_ja"),
                "name_en": row.get("name_en"),
                "market_name": row.get("market_name"),
                "sector33_name": row.get("sector33_name"),
            }
            for row in results
        ],
    }


def _resolve_or_404(raw_code: str) -> str:
    repository = core_repository()
    if not repository.exists():
        raise HTTPException(status_code=503, detail={"code": "data_not_initialized"})
    security = resolve_code(repository, raw_code)
    if security is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_security"})
    return security["canonical_code"]


@router.get("/{code}")
def get_stock(code: str) -> dict:
    canonical = _resolve_or_404(code)
    overview = stock_overview(core_repository(), canonical)
    if overview is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_security"})
    return overview


@router.get("/{code}/chart")
def get_chart(
    code: str,
    range: str = Query(default="1y", pattern="^(3m|6m|1y|3y|5y|10y)$"),
    interval: str = Query(default="1d", pattern="^(1d|60m|5m|1m)$"),
) -> dict:
    canonical = _resolve_or_404(code)
    if interval == "1d":
        return stock_chart(core_repository(), canonical, range_key=range)
    from app.data_paths import get_data_paths
    from app.domain.symbols import display_code as to_display
    from app.repositories.intraday_store import IntradayStore
    from app.services.intraday import intraday_chart

    store = IntradayStore(get_data_paths().intraday_db, read_only=True)
    view = intraday_chart(store, canonical, interval=interval)
    view["data_through"] = view["bars"][-1]["trade_date"] if view.get("bars") else None
    _refresh_cached_view(store, canonical, "minute", view)
    return {
        "canonical_code": canonical,
        "display_code": to_display(canonical),
        "range": "5d",
        "interval": interval,
        **view,
    }


@router.get("/{code}/ticks")
def get_ticks(code: str) -> dict:
    """ティックチャート＋歩み値（サーバ側で ≤1200 点へ間引き済み）。"""

    canonical = _resolve_or_404(code)
    from app.data_paths import get_data_paths
    from app.domain.symbols import display_code as to_display
    from app.repositories.intraday_store import IntradayStore
    from app.services.intraday import tick_view

    store = IntradayStore(get_data_paths().intraday_db, read_only=True)
    view = tick_view(store, canonical)
    view["data_through"] = view.get("trade_date") if view.get("available") else None
    _refresh_cached_view(store, canonical, "tick", view)
    return {"canonical_code": canonical, "display_code": to_display(canonical), **view}


@router.get("/{code}/resolve")
def resolve(code: str) -> dict:
    canonical = normalize_input_code(code)
    if canonical is None:
        raise HTTPException(status_code=422, detail={"code": "invalid_code_format"})
    return {"canonical_code": canonical, "display_code": display_code(canonical)}

def _refresh_cached_view(store, canonical: str, dataset: str, view: dict) -> None:
    from app.services.intraday import PUBLICATION_RETRY_SECONDS, cache_freshness

    target = core_repository().latest_bar_date()
    freshness = cache_freshness(store, canonical, dataset, target)
    needs_fetch = freshness.pop("needs_fetch")
    view.update(freshness)
    view["stale"] = bool(target and (not view.get("data_through") or view["data_through"] < target))
    view["queued"] = _active_intraday_fetch(canonical, dataset) or (
        _ensure_intraday_fetch(canonical, dataset, target) if needs_fetch else False
    )
    view["refreshing"] = view["queued"]
    if needs_fetch and not view["queued"]:
        # The worker may be unavailable or cooling down after a failed request.
        # Keep the page eligible for a later retry, without a fast request loop.
        view["retry_after_seconds"] = PUBLICATION_RETRY_SECONDS
    if view["queued"] and not view.get("available"):
        view["reason"] = "fetching"


def _active_intraday_fetch(canonical: str, dataset: str) -> bool:
    from app.api.deps import worker_state_read

    repository = worker_state_read()
    if not repository.exists():
        return False
    try:
        with repository.read() as connection:
            return connection.execute(
                "SELECT 1 FROM worker_action_requests WHERE action_type = ? "
                "AND status IN ('queued', 'running') AND json_extract(payload_json, '$.code') = ? LIMIT 1",
                ("tick_fetch" if dataset == "tick" else "intraday_fetch", canonical),
            ).fetchone() is not None
    except Exception:  # Cache browsing remains available while the worker starts.
        return False


def _ensure_intraday_fetch(canonical: str, dataset: str, trade_date: str | None) -> bool:
    """欠けている日中データの取得をワーカーに依頼する（API はプロバイダに触れない）。

    個股頁を開いただけで使えるようにするための自動化。冪等キーに銘柄と日付を
    含めるので、進行中の同一依頼は合流する。完了済みキーは再投入できる。
    自動補取はオーナーかログイン済みアカウントに限る。匿名はキャッシュを読む。
    実際にこの銘柄の取得が queued/running のときだけ True。
    """

    from app.access import current_request_can_refresh_public_data
    from app.api.deps import worker_state_write

    if not current_request_can_refresh_public_data():
        return False
    try:
        repository = worker_state_write()
        if not repository.exists():
            return False
        payload = {"code": canonical}
        if dataset == "tick":
            payload["dataset"] = "tick"
        outcome = repository.request_action(
            "tick_fetch" if dataset == "tick" else "intraday_fetch",
            idempotency_key=f"auto:{dataset}:{canonical}:{trade_date or 'latest'}",
            payload=payload,
        )
        return bool(outcome.get("accepted"))
    except Exception:  # noqa: BLE001 — 取得依頼が積めなくても閲覧は続行させる
        return False
