"""遅延ザラ場気配プロバイダ（Yahoo Finance chart API）。

**このモジュールは J-Quants と同格の情報源ではない。**
- 公式ではない取得元であり、無断で仕様が変わりうる
- 東証銘柄は概ね 15 分遅延（実測。`delayed_minutes` として毎回申告する）
- 取得できた気配は「表示専用」。レーダー・スクリーナー・強度スコアは
  従来どおり J-Quants の確定日足だけを使う（混ぜない）

したがって返り値は必ず `as_of` と `source` を持ち、UI 側はこれを根拠に
「遅延・非公式」であることを明示する。取得に失敗した銘柄は黙って古い値に
すり替えず、単に欠落させる（呼び出し側は公式終値のまま表示する）。

yfinance には依存しない: 必要なのは chart エンドポイント 1 本で、httpx で
直接叩ける。依存を増やすほど本番の壊れ方が増える。
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import httpx

from app.domain.symbols import display_code

QUOTE_SOURCE = "yahoo-delayed"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
# spark は複数シンボルを 1 リクエストで返す（v7/quote は 401＝要 crumb 認証）。
# 実測上限は 20 シンボル/リクエスト（25 で HTTP 400）。
SPARK_URL = "https://query1.finance.yahoo.com/v7/finance/spark"
SPARK_BATCH_SIZE = 20
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OptixJapan/1.0)"}

# spark で 20 件ずつまとめるので、1 回の呼び出しは 3 バッチ（60 件）まで。
MAX_SYMBOLS_PER_CALL = 60
_MAX_WORKERS = 8
_TIMEOUT_SECONDS = 4.0

# ザラ場指数: Yahoo に実データがあるものだけ。TOPIX は連動 ETF しか無く、
# ETF 価格を「TOPIX」と称するのは誤りなので載せない。
INTRADAY_INDEX_SYMBOLS: dict[str, str] = {"^N225": "日経225"}

# 連動 ETF: 指数そのもののザラ場値が無い銘柄の「方向」を出すための参考値。
# ETF 価格を指数値として出してはいけないので、UI では必ず ETF と明示する。
# 対応は longName で確認済み。グロース/スタンダード/Small は対応 ETF を
# 確認できなかったので、憶測でマップしない（空のままにする）。
INDEX_PROXY_ETF: dict[str, tuple[str, str]] = {
    "0000": ("1306.T", "NEXT FUNDS TOPIX ETF"),      # TOPIX
    "0028": ("1311.T", "NEXT FUNDS TOPIX Core30 ETF"),
}


@dataclass(frozen=True)
class IntradayQuote:
    """遅延気配 1 件。`as_of` は取得元が申告した約定時刻（JST epoch 秒）。"""

    key: str
    symbol: str
    price: float
    previous_close: float | None
    change_pct: float | None
    as_of_epoch: int | None
    currency: str | None
    exchange: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "symbol": self.symbol,
            "price": self.price,
            "previous_close": self.previous_close,
            "change_pct": self.change_pct,
            "as_of_epoch": self.as_of_epoch,
            "currency": self.currency,
            "exchange": self.exchange,
            "source": QUOTE_SOURCE,
        }


def canonical_to_symbol(canonical_code: str) -> str:
    """72030 → 7203.T（J-Quants の 5 桁コードは末尾 0 が取引所桁）。"""

    return f"{display_code(canonical_code)}.T"


def _parse_chart(key: str, symbol: str, payload: Mapping[str, Any]) -> IntradayQuote | None:
    chart = payload.get("chart") or {}
    results = chart.get("result") or []
    if not results:
        return None
    meta = results[0].get("meta") or {}
    price = meta.get("regularMarketPrice")
    if price is None:
        return None  # 板が立っていない/データ無し —— 古い値で埋めない
    previous = meta.get("chartPreviousClose") or meta.get("previousClose")
    try:
        price_value = float(price)
        previous_value = float(previous) if previous is not None else None
    except (TypeError, ValueError):
        return None
    change_pct = (
        (price_value / previous_value - 1.0)
        if previous_value not in (None, 0)
        else None
    )
    as_of = meta.get("regularMarketTime")
    return IntradayQuote(
        key=key,
        symbol=symbol,
        price=price_value,
        previous_close=previous_value,
        change_pct=change_pct,
        as_of_epoch=int(as_of) if as_of is not None else None,
        currency=meta.get("currency"),
        exchange=meta.get("fullExchangeName"),
    )


class YahooQuoteProvider:
    """遅延気配の取得。失敗は例外にせず「その銘柄が無い」として返す。

    API プロセスから同期的に呼ばれるため、1 銘柄あたり短いタイムアウトを置き、
    並列度も抑える。外部が遅いときにページ全体を巻き込まない方が重要。
    """

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = _TIMEOUT_SECONDS,
        max_workers: int = _MAX_WORKERS,
    ) -> None:
        self._client = client
        self._timeout = timeout_seconds
        self._max_workers = max(1, int(max_workers))

    def _fetch_one(self, client: httpx.Client, key: str, symbol: str) -> IntradayQuote | None:
        try:
            response = client.get(
                CHART_URL.format(symbol=symbol),
                params={"range": "1d", "interval": "1m"},
                timeout=self._timeout,
            )
            if response.status_code != 200:
                return None
            return _parse_chart(key, symbol, response.json())
        except Exception:  # noqa: BLE001 — 外部の落ち方は多様。欠落として扱う
            return None

    def _fetch_batch(
        self, client: httpx.Client, pairs: Sequence[tuple[str, str]]
    ) -> dict[str, IntradayQuote]:
        """spark で最大 20 シンボルを 1 往復で取る。失敗時は個別取得へ落とす。"""

        by_symbol = {symbol: key for key, symbol in pairs}
        try:
            response = client.get(
                SPARK_URL,
                params={"symbols": ",".join(by_symbol), "range": "1d", "interval": "1m"},
                timeout=self._timeout,
            )
            if response.status_code != 200:
                raise ValueError(f"spark status {response.status_code}")
            results = (response.json().get("spark") or {}).get("result") or []
        except Exception:  # noqa: BLE001 — バッチが壊れても個別で拾えることがある
            return {
                quote.key: quote
                for quote in (self._fetch_one(client, key, symbol) for key, symbol in pairs)
                if quote is not None
            }
        found: dict[str, IntradayQuote] = {}
        for entry in results:
            symbol = entry.get("symbol")
            key = by_symbol.get(symbol)
            responses = entry.get("response") or []
            if key is None or not responses:
                continue
            quote = _parse_chart(key, symbol, {"chart": {"result": responses}})
            if quote is not None:
                found[key] = quote
        return found

    def quotes(self, pairs: Sequence[tuple[str, str]]) -> dict[str, IntradayQuote]:
        """[(key, yahoo_symbol)] → {key: quote}。取れなかった key は入らない。"""

        targets = list(pairs)[:MAX_SYMBOLS_PER_CALL]
        if not targets:
            return {}
        owned = self._client is None
        client = self._client or httpx.Client(headers=_HEADERS, timeout=self._timeout)
        try:
            batches = [
                targets[start : start + SPARK_BATCH_SIZE]
                for start in range(0, len(targets), SPARK_BATCH_SIZE)
            ]
            if len(batches) == 1:
                return self._fetch_batch(client, batches[0])
            merged: dict[str, IntradayQuote] = {}
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(self._max_workers, len(batches))
            ) as pool:
                for part in pool.map(lambda b: self._fetch_batch(client, b), batches):
                    merged.update(part)
            return merged
        finally:
            if owned:
                client.close()

    def quotes_for_codes(self, canonical_codes: Iterable[str]) -> dict[str, IntradayQuote]:
        pairs = [(code, canonical_to_symbol(code)) for code in canonical_codes]
        return self.quotes(pairs)

    def index_quotes(self) -> dict[str, IntradayQuote]:
        """真のザラ場指数 + 連動 ETF（キーは指数コード/シンボルのまま）。"""

        pairs = [(symbol, symbol) for symbol in INTRADAY_INDEX_SYMBOLS]
        pairs += [(code, etf) for code, (etf, _name) in INDEX_PROXY_ETF.items()]
        return self.quotes(pairs)


__all__ = [
    "CHART_URL",
    "INDEX_PROXY_ETF",
    "SPARK_BATCH_SIZE",
    "INTRADAY_INDEX_SYMBOLS",
    "IntradayQuote",
    "MAX_SYMBOLS_PER_CALL",
    "QUOTE_SOURCE",
    "YahooQuoteProvider",
    "canonical_to_symbol",
]
