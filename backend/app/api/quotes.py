"""遅延ザラ場気配 API（表示専用・非公式ソース）。

J-Quants は場中に一切 publish しない（実測: 場中の分足・日足とも 0 行）。
そこで「今いくらか」を出すためだけに Yahoo の遅延気配を併用する。ここで返す
数字は **公式の確定値ではない**ので、レスポンスは必ず source と delayed を
申告し、UI 側で J-Quants 由来の値と視覚的に区別させる。

レーダー・スクリーナー・強度スコアはこの値を一切参照しない（混ぜない）。
"""

from __future__ import annotations

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
from app.services.cache import cache as shared_cache

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

    async def build() -> dict:
        provider = YahooQuoteProvider()
        found = provider.quotes_for_codes(canonical) if canonical else {}
        indices = provider.index_quotes()
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
