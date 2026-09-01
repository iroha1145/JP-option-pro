"""ザラ場気配 API（表示専用）。

J-Quants は場中に一切 publish しない（実測: 場中の分足・日足とも 0 行）。
そこで「今いくらか」を出すためだけに別系統の気配を併用する。ここで返す値が
公式の確定値かどうかは供給元によって変わるので、**判断材料をレスポンスに
必ず載せる**（source / delay_class / is_official / is_realtime / stale /
market_session）。UI はこれを見て J-Quants 由来の値と視覚的に区別する。

このモジュールは特定の供給元（Yahoo 等）を知らない。選択はレジストリの
仕事で、将来リアルタイム源が繋がってもここは変わらない。

レーダー・スクリーナー・強度スコアはこの値を一切参照しない（混ぜない）。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import core_repository
from app.domain.constants import SECTOR33
from app.domain.symbols import normalize_input_code
from app.services.cache import cache as shared_cache
from app.services.intraday_quotes import (
    all_source_statuses,
    current_source,
    fetch_quotes_and_indices,
    fetch_quotes_blocking,
)
from app.services.market import _median_sorted

router = APIRouter(prefix="/api/quotes", tags=["quotes"])

QUOTES_VERSION = "jp-quotes-v2"
# 遅延がある以上、これ以上細かく取りに行っても新しい値は出てこない。
_CACHE_SECONDS = 60
# 全市場 1,587 銘柄 = 80 バッチ ≈ 6 秒。1 分ごとに撫でても情報は増えない。
_SECTOR_CACHE_SECONDS = 180
# 1 リクエストで受ける銘柄数の上限（外部への 1 回の呼び出し上限に合わせる）。
MAX_CODES_PER_REQUEST = 60


def _source_envelope() -> dict:
    """毎レスポンスに載せる供給元の申告（値の意味を決めるのはこれ）。"""

    status = current_source()
    return {
        "version": QUOTES_VERSION,
        "source": status.name,
        "delay_class": status.delay_class,
        "is_official": status.is_official,
        "is_realtime": status.is_realtime,
        "source_detail": status.detail,
        # 互換: 既存の画面は delayed / delayed_minutes を読んでいる。値は
        # プロバイダの申告から導くので、リアルタイム源に切り替われば
        # delayed=False・0 分になり、文言も自動で正しくなる。
        "delayed": not status.is_realtime,
        "delayed_minutes": status.delay_minutes,
    }


def _disabled(**extra) -> dict:
    return {
        **_source_envelope(),
        "enabled": False,
        "reason": "feature_disabled",
        "quotes": {},
        **extra,
    }


def _enabled() -> bool:
    return current_source().available


@router.get("/sources")
def quote_sources() -> dict:
    """全供給元の状態。未接続のリレーも隠さずに出す（データ状態ページ用）。"""

    return {
        "version": QUOTES_VERSION,
        "selected": current_source().as_dict(),
        "providers": [status.as_dict() for status in all_source_statuses()],
    }


@router.get("/intraday")
async def intraday_quotes(codes: str = Query(default="", max_length=800)) -> dict:
    """codes=7203,9984 → 気配。取得できなかった銘柄は単に欠落する。"""

    if not _enabled():
        return _disabled(indices={})

    canonical: list[str] = []
    for raw in codes.split(","):
        raw = raw.strip()
        if not raw:
            continue
        code = normalize_input_code(raw)
        if code is None:
            raise HTTPException(status_code=422, detail={"code": "invalid_code_format"})
        if code not in canonical:
            canonical.append(code)
    if len(canonical) > MAX_CODES_PER_REQUEST:
        raise HTTPException(status_code=422, detail={"code": "too_many_codes"})

    repository = core_repository()
    if canonical and repository.exists():
        # 存在しないコードで外部を叩かない（マスタにある銘柄だけ）
        known = {row["canonical_code"] for row in repository.list_securities(active_only=False)}
        canonical = [code for code in canonical if code in known]

    key = "quotes:intraday:" + ",".join(sorted(canonical))

    async def build() -> dict:
        found, indices = await fetch_quotes_and_indices(canonical)
        return {
            **_source_envelope(),
            "enabled": True,
            "requested": len(canonical),
            "quotes": {code: quote.as_dict() for code, quote in found.items()},
            "indices": {
                symbol: {**quote.as_dict(), **quote.extra}
                for symbol, quote in indices.items()
            },
        }

    return await shared_cache.get_or_set(key, _CACHE_SECONDS, build)


@router.get("/sectors/intraday")
async def intraday_sectors() -> dict:
    """業種別のザラ場断面（気配から中央値を作る・表示専用）。

    公式日足の断面（/api/market/overview の sectors）とは別物として返す。
    レーダーやスコアには一切入らない。
    """

    if not _enabled():
        return _disabled(sectors=[])
    repository = core_repository()
    if not repository.exists():
        raise HTTPException(status_code=503, detail={"code": "data_not_initialized"})

    rows, _total = repository.screener_query(
        where_sql="1=1", params=[], order_sql="canonical_code ASC", limit=10000, offset=0
    )
    universe = [(row["canonical_code"], row.get("sector33_code")) for row in rows]

    async def build() -> dict:
        # 1,587 銘柄で 5 秒超。ここを await せずに回すとページ全体が落ちる
        # （実測: 市場ページ本体が「請求超時」になった）。
        found = await asyncio.to_thread(
            fetch_quotes_blocking, [code for code, _sector in universe]
        )
        by_sector: dict[str, list[float]] = {}
        for code, sector in universe:
            quote = found.get(code)
            if sector is None or quote is None or quote.change_pct is None:
                continue
            by_sector.setdefault(sector, []).append(quote.change_pct)
        sectors = []
        for sector_code, changes in by_sector.items():
            changes.sort()
            median = _median_sorted(changes)  # true median (avg of two central for even n)
            advancing = sum(1 for value in changes if value > 0.0005)
            sectors.append(
                {
                    "sector33_code": sector_code,
                    "sector33_name": SECTOR33.get(sector_code, sector_code),
                    "median_return_1d": median,
                    "advancers_share": advancing / len(changes),
                    "covered": len(changes),
                }
            )
        sectors.sort(key=lambda item: -item["median_return_1d"])
        return {
            **_source_envelope(),
            "enabled": True,
            "universe": len(universe),
            "quoted": len(found),
            "sectors": sectors,
        }

    return await shared_cache.get_or_set("quotes:sectors:intraday", _SECTOR_CACHE_SECONDS, build)


@router.get("/overlay")
async def intraday_overlay_view(
    scope: str = Query(default="radar", pattern="^(radar|screener)$"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    """夜間断面 × ザラ場気配のオーバーレイ（再スキャンではない）。

    scope=radar    : 生存中のレーダー事件に「今ピボットの上か」を付ける
    scope=screener : スクリーナー断面に「今の値段/高値からの距離」を付ける

    スコアは書き換えない。出来高由来の指標にも触れない（場中の部分出来高を
    1 日平均と比べるのは誤り）。
    """

    if not _enabled():
        return _disabled(scope=scope, rows={})
    repository = core_repository()
    if not repository.exists():
        raise HTTPException(status_code=503, detail={"code": "data_not_initialized"})

    from app.services.intraday_overlay import build_overlay, overlay_event
    from app.services.radar.lifecycle import TERMINAL_STATES

    if scope == "radar":
        events = repository.open_radar_events(terminal_states=sorted(TERMINAL_STATES))[:limit]
        codes = [event["canonical_code"] for event in events]
    else:
        rows, _total = repository.screener_query(
            where_sql="1=1", params=[], order_sql="canonical_code ASC", limit=limit, offset=0
        )
        codes = [row["canonical_code"] for row in rows]

    cache_key = f"quotes:overlay:{scope}:{limit}"

    async def build() -> dict:
        quotes = await asyncio.to_thread(fetch_quotes_blocking, codes)
        envelope = {**_source_envelope(), "enabled": True, "scope": scope}
        if scope == "radar":
            packs = {}
            for event in events:
                quote = quotes.get(event["canonical_code"])
                pack = overlay_event(event, getattr(quote, "price", None) if quote else None)
                if pack is not None:
                    packs[event["event_id"]] = pack
            above = sum(1 for pack in packs.values() if pack.get("above_pivot"))
            return {
                **envelope,
                "requested": len(events), "quoted": len(packs),
                "above_pivot_count": above,
                "rows": packs,
            }
        packs = build_overlay(rows, quotes)
        return {
            **envelope,
            "requested": len(rows), "quoted": len(packs),
            "rows": packs,
        }

    return await shared_cache.get_or_set(cache_key, _CACHE_SECONDS, build)
