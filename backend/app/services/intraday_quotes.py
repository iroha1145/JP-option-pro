"""ザラ場気配サービス。API と業務ロジックはここだけを呼ぶ。

役割は 3 つだけ:
  1. 供給元の選択をレジストリに委ね、呼び出し側から供給元名を隠す
  2. 全市場規模でも 1 往復ずつになるようバッチ分割する
  3. 同期 HTTP を **イベントループの外**に出す

3 番目は実測で痛い目を見た箇所: `async def` の中で同期 HTTP を回すと、
1,587 銘柄の取得（約 5.9 秒）の間、同じプロセスの他のリクエスト（市場ページ
本体）まで巻き添えでタイムアウトする。取得は必ず `asyncio.to_thread` 越しに。
"""

from __future__ import annotations

import asyncio
from typing import Iterable, Sequence

from app.providers.intraday.contract import ProviderStatus, Quote
from app.providers.intraday.registry import provider_statuses, select_provider

# プロバイダ側の 1 呼び出し上限（spark 20 件 × 3 バッチ）に合わせる。
CHUNK_SIZE = 60


def _chunks(items: Sequence[str], size: int = CHUNK_SIZE):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def fetch_quotes_blocking(canonical_codes: Iterable[str]) -> dict[str, Quote]:
    """同期版。**必ずスレッドに逃がして呼ぶこと**（下の async 版を使う）。"""

    codes = list(dict.fromkeys(canonical_codes))
    if not codes:
        return {}
    provider = select_provider()
    found: dict[str, Quote] = {}
    for chunk in _chunks(codes):
        found.update(provider.quotes_for_codes(chunk))
    return found


def fetch_indices_blocking() -> dict[str, Quote]:
    return select_provider().index_quotes()


async def fetch_quotes(canonical_codes: Iterable[str]) -> dict[str, Quote]:
    codes = list(canonical_codes)
    return await asyncio.to_thread(fetch_quotes_blocking, codes)


async def fetch_indices() -> dict[str, Quote]:
    return await asyncio.to_thread(fetch_indices_blocking)


async def fetch_quotes_and_indices(
    canonical_codes: Iterable[str],
) -> tuple[dict[str, Quote], dict[str, Quote]]:
    """1 回のスレッド往復で両方（別々に to_thread すると 2 本占有する）。"""

    codes = list(canonical_codes)

    def _both() -> tuple[dict[str, Quote], dict[str, Quote]]:
        return fetch_quotes_blocking(codes), fetch_indices_blocking()

    return await asyncio.to_thread(_both)


def current_source() -> ProviderStatus:
    return select_provider().status()


def all_source_statuses() -> list[ProviderStatus]:
    return provider_statuses()


__all__ = [
    "CHUNK_SIZE",
    "all_source_statuses",
    "current_source",
    "fetch_indices",
    "fetch_indices_blocking",
    "fetch_quotes",
    "fetch_quotes_and_indices",
    "fetch_quotes_blocking",
]
