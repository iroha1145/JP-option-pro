"""供給元の登録簿と選択。業務側はここより下の名前を知らない。

選択規則は「使えるもののうち最も良い等級」。良い順は
リアルタイム・公式 > 遅延・非公式 > 無効。繋がっていない供給元は
`available=False` を返すので自動的に外れる —— 未接続のリアルタイム源が
選ばれて空を返し続ける、という壊れ方をしない。
"""

from __future__ import annotations

from typing import Callable

from app.personal_config import get_personal_config

from .contract import (
    DELAY_DELAYED,
    DELAY_END_OF_DAY,
    DELAY_REALTIME,
    DELAY_UNKNOWN,
    IntradayQuoteProvider,
    ProviderStatus,
)
from .providers import (
    DisabledProvider,
    KabuStationRelayProvider,
    MarketSpeedRelayProvider,
    YahooDelayedProvider,
)

# 良い順。business 側の分岐はこの序列だけを見る。
DELAY_RANK = {
    DELAY_REALTIME: 0,
    DELAY_END_OF_DAY: 1,
    DELAY_DELAYED: 2,
    DELAY_UNKNOWN: 3,
}

ProviderFactory = Callable[[], IntradayQuoteProvider]

#: 登録順は優先順ではない（実際の選択は等級と available で決まる）。
PROVIDER_FACTORIES: dict[str, ProviderFactory] = {
    "kabu-station-relay": KabuStationRelayProvider,
    "market-speed-relay": MarketSpeedRelayProvider,
    "yahoo-delayed": YahooDelayedProvider,
    "disabled": DisabledProvider,
}


def available_providers() -> list[IntradayQuoteProvider]:
    """設定で有効な供給元のうち、いま実際に使えるものを良い順で。"""

    config = get_personal_config()
    if not config.features.intraday_quotes:
        return []
    ready: list[IntradayQuoteProvider] = []
    for factory in PROVIDER_FACTORIES.values():
        provider = factory()
        if provider.name == "disabled":
            continue
        if provider.status().available:
            ready.append(provider)
    ready.sort(key=lambda item: DELAY_RANK.get(item.delay_class, 99))
    return ready


def select_provider() -> IntradayQuoteProvider:
    """いま使う供給元 1 つ。無ければ DisabledProvider（例外にしない）。"""

    ready = available_providers()
    return ready[0] if ready else DisabledProvider()


def provider_statuses() -> list[ProviderStatus]:
    """全供給元の状態（データ状態ページ用。未接続も含めて見せる）。"""

    return [
        factory().status()
        for name, factory in PROVIDER_FACTORIES.items()
        if name != "disabled"
    ]


__all__ = [
    "DELAY_RANK",
    "PROVIDER_FACTORIES",
    "available_providers",
    "provider_statuses",
    "select_provider",
]
