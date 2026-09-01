"""遅延ザラ場気配 API（表示専用・非公式ソース）。

J-Quants は場中に一切 publish しない（実測: 場中の分足・日足とも 0 行）。
そこで「今いくらか」を出すためだけに Yahoo の遅延気配を併用する。ここで返す
数字は **公式の確定値ではない**ので、レスポンスは必ず source と delayed を
申告し、UI 側で J-Quants 由来の値と視覚的に区別させる。

レーダー・スクリーナー・強度スコアはこの値を一切参照しない（混ぜない）。
"""

from __future__ import annotations

import asyncio
import concurrent.futures

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import core_repository
from app.domain.symbols import normalize_input_code
from app.personal_config import get_personal_config
from app.providers.yahoo_quotes import (
    INTRADAY_INDEX_SYMBOLS,
    MAX_SYMBOLS_PER_CALL,
    QUOTE_SOURCE,
    YahooQuoteProvider,
)
from app.domain.constants import SECTOR33
from app.services.cache import cache as shared_cache
from app.services.market import _median_sorted

router = APIRouter(prefix="/api/quotes", tags=["quotes"])

QUOTES_VERSION = "jp-quotes-v1"
# 遅延が 15 分ある以上、これ以上細かく取りに行っても新しい値は出てこない。
_CACHE_SECONDS = 60


def _disabled() -> dict:
    return {
        "version": QUOTES_VERSION,
        "enabled": False,
        "source": QUOTE_SOURCE,
        "reason": "feature_disabled",
        "quotes": {},
    }


@router.get("/intraday")
async def intraday_quotes(codes: str = Query(default="", max_length=800)) -> dict:
    """codes=7203,9984 → 遅延気配。取得できなかった銘柄は単に欠落する。"""

    config = get_personal_config()
    if not config.features.intraday_quotes:
        return _disabled()

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
    if len(canonical) > MAX_SYMBOLS_PER_CALL:
        raise HTTPException(status_code=422, detail={"code": "too_many_codes"})

    repository = core_repository()
    if canonical and repository.exists():
        # 存在しないコードで外部を叩かない（マスタにある銘柄だけ）
        known = {row["canonical_code"] for row in repository.list_securities(active_only=False)}
        canonical = [code for code in canonical if code in known]

    key = "quotes:intraday:" + ",".join(sorted(canonical))

    def _collect() -> tuple[dict, dict]:
        provider = YahooQuoteProvider()
        return (
            provider.quotes_for_codes(canonical) if canonical else {},
            provider.index_quotes(),
        )

    async def build() -> dict:
        # プロバイダは同期 HTTP。async ハンドラ内で直に回すとイベントループを
        # 止め、同じプロセスの他リクエスト（市場ページ本体）まで道連れにする。
        found, indices = await asyncio.to_thread(_collect)
        return {
            "version": QUOTES_VERSION,
            "enabled": True,
            "source": QUOTE_SOURCE,
            "delayed": True,
            "delayed_minutes": 15,
            "requested": len(canonical),
            "quotes": {code: quote.as_dict() for code, quote in found.items()},
            "indices": {
                symbol: {**quote.as_dict(), "name": INTRADAY_INDEX_SYMBOLS.get(symbol, symbol)}
                for symbol, quote in indices.items()
            },
        }

    return await shared_cache.get_or_set(key, _CACHE_SECONDS, build)


# 全市場 1,587 銘柄 = 80 バッチ ≈ 6 秒。遅延 15 分のデータを 1 分ごとに撫でても
# 情報は増えないので 3 分キャッシュ（Yahoo への負荷を 1/3 に）。
_SECTOR_CACHE_SECONDS = 180


@router.get("/sectors/intraday")
async def intraday_sectors() -> dict:
    """業種別のザラ場断面（遅延気配から中央値を作る・表示専用）。

    公式日足の断面（/api/market/overview の sectors）とは別物として返す。
    値は非公式・15 分遅延であり、レーダーやスコアには一切入らない。
    """

    config = get_personal_config()
    if not config.features.intraday_quotes:
        return {**_disabled(), "sectors": []}
    repository = core_repository()
    if not repository.exists():
        raise HTTPException(status_code=503, detail={"code": "data_not_initialized"})

    rows, _total = repository.screener_query(
        where_sql="1=1", params=[], order_sql="canonical_code ASC", limit=10000, offset=0
    )
    universe = [(row["canonical_code"], row.get("sector33_code")) for row in rows]

    def _collect_all() -> dict:
        codes = [code for code, _sector in universe]
        chunks = [codes[start : start + 60] for start in range(0, len(codes), 60)]

        def _one(chunk: list[str]) -> dict:
            return YahooQuoteProvider(max_workers=3).quotes_for_codes(chunk)

        found: dict = {}
        # 60 件窓を並列化。各窓は独自クライアントなので入れ子プールで死なない。
        workers = min(6, max(1, len(chunks)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for part in pool.map(_one, chunks):
                found.update(part)
        return found

    async def build() -> dict:
        # 1,587 銘柄で 5 秒超。ここを await せずに回すとページ全体が落ちる
        # （実測: 市場ページ本体が「請求超時」になった）。
        found = await asyncio.to_thread(_collect_all)
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
            "version": QUOTES_VERSION,
            "enabled": True,
            "source": QUOTE_SOURCE,
            "delayed": True,
            "delayed_minutes": 15,
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
    """夜間断面 × 遅延気配のオーバーレイ（再スキャンではない）。

    scope=radar    : 生存中のレーダー事件に「今ピボットの上か」を付ける
    scope=screener : スクリーナー断面に「今の値段/高値からの距離」を付ける

    スコアは書き換えない。出来高由来の指標にも触れない（場中の部分出来高を
    1 日平均と比べるのは誤り）。
    """

    config = get_personal_config()
    if not config.features.intraday_quotes:
        return {**_disabled(), "scope": scope, "rows": []}
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

    def _collect() -> dict:
        provider = YahooQuoteProvider(max_workers=6)
        found: dict = {}
        for start in range(0, len(codes), 60):
            found.update(provider.quotes_for_codes(codes[start : start + 60]))
        return found

    cache_key = f"quotes:overlay:{scope}:{limit}"

    async def build() -> dict:
        quotes = await asyncio.to_thread(_collect)
        if scope == "radar":
            packs = {}
            for event in events:
                quote = quotes.get(event["canonical_code"])
                pack = overlay_event(event, getattr(quote, "price", None) if quote else None)
                if pack is not None:
                    packs[event["event_id"]] = pack
            above = sum(1 for pack in packs.values() if pack.get("above_pivot"))
            return {
                "version": QUOTES_VERSION, "enabled": True, "scope": scope,
                "source": QUOTE_SOURCE, "delayed": True, "delayed_minutes": 15,
                "requested": len(events), "quoted": len(packs),
                "above_pivot_count": above,
                "rows": packs,
            }
        packs = build_overlay(rows, quotes)
        return {
            "version": QUOTES_VERSION, "enabled": True, "scope": scope,
            "source": QUOTE_SOURCE, "delayed": True, "delayed_minutes": 15,
            "requested": len(rows), "quoted": len(packs),
            "rows": packs,
        }

    return await shared_cache.get_or_set(cache_key, _CACHE_SECONDS, build)
