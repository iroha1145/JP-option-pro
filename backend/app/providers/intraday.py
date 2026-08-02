"""将来のリアルタイム/分足データの拡張ポイント。

レーダー・フロントエンドは具体的なベンダーに依存しない。将来
J-Quants 分足オプションや証券会社 API を追加する時は、この Protocol の
実装を providers/ に追加し、ファクトリだけ差し替える。現在は
DisabledProvider が「利用不可」を正直に返す。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence


@dataclass(frozen=True)
class IntradayQuote:
    canonical_code: str
    price: float
    as_of: str  # ISO8601, Asia/Tokyo
    session: str  # morning | lunch | afternoon | closed
    delayed_seconds: int | None


class IntradayQuoteProvider(Protocol):
    def enabled(self) -> bool: ...

    def latest_quotes(self, canonical_codes: Sequence[str]) -> dict[str, IntradayQuote]: ...


class IntradayBarProvider(Protocol):
    def enabled(self) -> bool: ...

    def minute_bars(self, canonical_code: str, *, date: str) -> list[dict[str, Any]]: ...


class RealtimeRankingProvider(Protocol):
    def enabled(self) -> bool: ...

    def turnover_ranking(self, *, limit: int) -> list[dict[str, Any]]: ...


class DisabledIntradayProvider:
    """すべての盤中機能が未契約であることを明示する実装。"""

    def enabled(self) -> bool:
        return False

    def latest_quotes(self, canonical_codes: Sequence[str]) -> dict[str, IntradayQuote]:
        return {}

    def minute_bars(self, canonical_code: str, *, date: str) -> list[dict[str, Any]]:
        return []

    def turnover_ranking(self, *, limit: int) -> list[dict[str, Any]]:
        return []


def get_intraday_provider() -> DisabledIntradayProvider:
    return DisabledIntradayProvider()


__all__ = [
    "DisabledIntradayProvider",
    "IntradayBarProvider",
    "IntradayQuote",
    "IntradayQuoteProvider",
    "RealtimeRankingProvider",
    "get_intraday_provider",
]
