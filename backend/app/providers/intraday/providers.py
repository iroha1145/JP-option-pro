"""具体的な供給元。いまは Yahoo 遅延と「無効」の 2 つだけが動く。

Yahoo の遅延気配を共通の契約に載せ、機能が無効なら空の実装を返す。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Iterable

from app.providers.yahoo_quotes import (
    INDEX_PROXY_ETF,
    INTRADAY_INDEX_SYMBOLS,
    QUOTE_SOURCE,
    YahooQuoteProvider,
    canonical_to_symbol,
)

from .contract import (
    DELAY_DELAYED,
    DELAY_UNKNOWN,
    JST,
    ProviderStatus,
    Quote,
    market_session,
)


class DisabledProvider:
    """機能フラグが落ちているとき。空を返すだけで、例外にはしない。"""

    name = "disabled"
    delay_class = DELAY_UNKNOWN
    is_official = False
    is_realtime = False

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name, available=False, delay_class=self.delay_class,
            is_official=False, is_realtime=False, detail="feature_disabled",
        )

    def quotes_for_codes(self, canonical_codes: Iterable[str]) -> dict[str, Quote]:
        return {}

    def index_quotes(self) -> dict[str, Quote]:
        return {}


class YahooDelayedProvider:
    """Yahoo の遅延気配を契約の形に載せ替える。

    取得の中身（spark バッチ・タイムアウト・並列度）は既存実装のまま使う。
    ここでやるのは **素性の申告を必ず付けること** だけ。
    """

    name = QUOTE_SOURCE
    delay_class = DELAY_DELAYED
    is_official = False
    is_realtime = False
    # 実測値（銘柄・指数・ETF いずれも 15.0 分）。UI に出す根拠として持つ。
    delay_minutes = 15

    def __init__(self, *, max_workers: int = 6) -> None:
        self._inner = YahooQuoteProvider(max_workers=max_workers)

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name, available=True, delay_class=self.delay_class,
            is_official=False, is_realtime=False, delay_minutes=self.delay_minutes,
            detail=f"約{self.delay_minutes}分遅延・非公式ソース",
        )

    def _wrap(self, raw, *, key: str, received_at: datetime, session: str) -> Quote:
        quote_time = (
            datetime.fromtimestamp(raw.as_of_epoch, tz=timezone.utc).astimezone(JST)
            if raw.as_of_epoch is not None
            else None
        )
        return Quote(
            key=key,
            price=raw.price,
            previous_close=raw.previous_close,
            change_pct=raw.change_pct,
            quote_time=quote_time,
            received_at=received_at,
            source=self.name,
            delay_class=self.delay_class,
            is_official=False,
            is_realtime=False,
            session=session,
            currency=raw.currency,
            exchange=raw.exchange,
            symbol=raw.symbol,
        )

    def quotes_for_codes(self, canonical_codes: Iterable[str]) -> dict[str, Quote]:
        codes = list(canonical_codes)
        if not codes:
            return {}
        received_at = datetime.now(JST)
        session = market_session(received_at)
        found = self._inner.quotes_for_codes(codes)
        return {
            key: self._wrap(raw, key=key, received_at=received_at, session=session)
            for key, raw in found.items()
        }

    def index_quotes(self) -> dict[str, Quote]:
        received_at = datetime.now(JST)
        session = market_session(received_at)
        found = self._inner.index_quotes()
        out: dict[str, Quote] = {}
        for key, raw in found.items():
            quote = self._wrap(raw, key=key, received_at=received_at, session=session)
            name = INTRADAY_INDEX_SYMBOLS.get(key)
            proxy = INDEX_PROXY_ETF.get(key)
            if name is not None:
                extra = {"display_name": name, "is_proxy": False}
            elif proxy is not None:
                # ETF 価格を指数値として出さない。参考値であることを値に刻む。
                extra = {"display_name": proxy[1], "is_proxy": True}
            else:
                extra = {}
            out[key] = replace(quote, extra=extra) if extra else quote
        return out


__all__ = ["DisabledProvider", "YahooDelayedProvider", "canonical_to_symbol"]
