"""ザラ場気配プロバイダの契約（誰から来た値かを、値と一緒に運ぶ）。

いま繋がっているのは Yahoo の遅延気配だけだが、将来 Windows の証券端末
（kabu ステーション / マーケットスピード）からリアルタイムを流す余地がある。
そのとき **業務側（レーダー・画面・API）を書き換えずに済む**よう、供給元の
違いはこの契約の中だけに閉じ込める。

肝は「価格」だけを返さないこと。同じ 3,000 円でも、

    公式 or 非公式 / リアルタイム or 15 分遅延 / 立会中 or 引け後 / 新鮮 or 古い

で意味がまるで違う。呼び出し側がそれを判断できるだけの申告を必ず添える。
値だけ返して素性を落とすと、遅延値が確定値の顔をして評価に混ざる。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Protocol, runtime_checkable

JST = timezone(timedelta(hours=9))

# 遅延の等級。数字ではなく等級で持つのは、業務側の判断が「何分か」ではなく
# 「確定値として扱ってよいか」だから。
DELAY_REALTIME = "realtime"        # 取引所直結（将来の証券端末リレー）
DELAY_DELAYED = "delayed"          # 概ね 15〜20 分遅れ（Yahoo 等）
DELAY_END_OF_DAY = "end_of_day"    # 確定した引け値（J-Quants）
DELAY_UNKNOWN = "unknown"

# 立会区分（JST）。
SESSION_PRE = "pre"                # 寄り前
SESSION_MORNING = "morning"        # 前場 09:00-11:30
SESSION_LUNCH = "lunch"            # 昼休み 11:30-12:30
SESSION_AFTERNOON = "afternoon"    # 後場 12:30-15:30
SESSION_CLOSED = "closed"          # 引け後・休場日

# この秒数より古い気配は stale として申告する（遅延分は別途 delay_class）。
STALE_AFTER_SECONDS = 10 * 60


def market_session(now: datetime | None = None) -> str:
    """JST の立会区分。祝日は判定しない（取引所カレンダーは呼び出し側の責務）。"""

    current = (now or datetime.now(JST)).astimezone(JST)
    if current.weekday() >= 5:
        return SESSION_CLOSED
    minutes = current.hour * 60 + current.minute
    if minutes < 9 * 60:
        return SESSION_PRE
    if minutes < 11 * 60 + 30:
        return SESSION_MORNING
    if minutes < 12 * 60 + 30:
        return SESSION_LUNCH
    if minutes <= 15 * 60 + 30:
        return SESSION_AFTERNOON
    return SESSION_CLOSED


@dataclass(frozen=True)
class Quote:
    """気配 1 件 + その素性。

    `quote_time` は取得元が申告した約定時刻、`received_at` はこちらが受け取った
    時刻。2 つ持つのは、供給元が古い値を返し続けているのか、こちらの取得が
    止まっているのかを区別するため（片方だけだと切り分けられない）。
    """

    key: str
    price: float
    previous_close: float | None = None
    change_pct: float | None = None
    quote_time: datetime | None = None
    received_at: datetime | None = None
    source: str = "unknown"
    delay_class: str = DELAY_UNKNOWN
    is_official: bool = False
    is_realtime: bool = False
    session: str = SESSION_CLOSED
    currency: str | None = None
    exchange: str | None = None
    symbol: str | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def stale(self) -> bool:
        """申告時刻が古すぎる（供給元が更新を止めている）か。"""

        if self.quote_time is None or self.received_at is None:
            return self.quote_time is None
        age = (self.received_at - self.quote_time).total_seconds()
        # 遅延ソースは構造的に遅れているので、その分を差し引いてから判定する。
        allowance = STALE_AFTER_SECONDS + (900 if self.delay_class == DELAY_DELAYED else 0)
        return age > allowance

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "symbol": self.symbol,
            "price": self.price,
            "previous_close": self.previous_close,
            "change_pct": self.change_pct,
            "quote_time": self.quote_time.isoformat() if self.quote_time else None,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "as_of_epoch": int(self.quote_time.timestamp()) if self.quote_time else None,
            "source": self.source,
            "delay_class": self.delay_class,
            "is_official": self.is_official,
            "is_realtime": self.is_realtime,
            "stale": self.stale,
            "market_session": self.session,
            "currency": self.currency,
            "exchange": self.exchange,
            "error": self.error,
        }


@dataclass(frozen=True)
class ProviderStatus:
    """プロバイダの現在の健康状態（画面の「データ状態」に出す）。"""

    name: str
    available: bool
    delay_class: str
    is_official: bool
    is_realtime: bool
    # 申告する遅延分数。UI に「15分」を焼き込ませないための値で、リアルタイム
    # 源が繋がれば 0 になり、表示も自動的に追随する。
    delay_minutes: int = 0
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "delay_class": self.delay_class,
            "is_official": self.is_official,
            "is_realtime": self.is_realtime,
            "delay_minutes": self.delay_minutes,
            "detail": self.detail,
        }


@runtime_checkable
class IntradayQuoteProvider(Protocol):
    """供給元 1 つ分の契約。

    実装は **例外を投げない**。1 銘柄の失敗で全体を巻き込まないよう、取れな
    かったものは結果に入れないだけにする（古い値で埋めるのは禁止 —— 呼び出し
    側は「無い」を見て公式終値のまま表示できる）。
    """

    name: str
    delay_class: str
    is_official: bool
    is_realtime: bool

    def status(self) -> ProviderStatus: ...

    def quotes_for_codes(self, canonical_codes: Iterable[str]) -> dict[str, Quote]: ...

    def index_quotes(self) -> dict[str, Quote]: ...


__all__ = [
    "DELAY_DELAYED",
    "DELAY_END_OF_DAY",
    "DELAY_REALTIME",
    "DELAY_UNKNOWN",
    "IntradayQuoteProvider",
    "JST",
    "ProviderStatus",
    "Quote",
    "SESSION_AFTERNOON",
    "SESSION_CLOSED",
    "SESSION_LUNCH",
    "SESSION_MORNING",
    "SESSION_PRE",
    "STALE_AFTER_SECONDS",
    "market_session",
]
