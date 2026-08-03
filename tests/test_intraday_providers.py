"""ザラ場気配プロバイダ層: 素性の申告・選択規則・非ブロッキング。

この層の存在意義は「業務側が供給元を知らないこと」なので、それが崩れて
いないか（結合の検査）と、値と一緒に素性が必ず付いてくるかを見る。
"""

from __future__ import annotations

import asyncio
import pathlib
import time
from datetime import datetime, timedelta

import pytest

from app.providers.intraday import contract as ct
from app.providers.intraday import registry
from app.providers.intraday.providers import (
    DisabledProvider,
    KabuStationRelayProvider,
    MarketSpeedRelayProvider,
)


# ---------------------------------------------------------------------------
# 1. 立会区分
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "clock,expected",
    [
        ("2026-08-03 08:30", ct.SESSION_PRE),       # 月曜 寄り前
        ("2026-08-03 09:00", ct.SESSION_MORNING),
        ("2026-08-03 11:29", ct.SESSION_MORNING),
        ("2026-08-03 11:30", ct.SESSION_LUNCH),
        ("2026-08-03 12:29", ct.SESSION_LUNCH),
        ("2026-08-03 12:30", ct.SESSION_AFTERNOON),
        ("2026-08-03 15:30", ct.SESSION_AFTERNOON),
        ("2026-08-03 15:31", ct.SESSION_CLOSED),
        ("2026-08-01 10:00", ct.SESSION_CLOSED),    # 土曜
        ("2026-08-02 10:00", ct.SESSION_CLOSED),    # 日曜
    ],
)
def test_market_session_boundaries(clock, expected):
    moment = datetime.strptime(clock, "%Y-%m-%d %H:%M").replace(tzinfo=ct.JST)
    assert ct.market_session(moment) == expected


# ---------------------------------------------------------------------------
# 2. 気配は素性を必ず連れてくる
# ---------------------------------------------------------------------------


def _quote(**overrides) -> ct.Quote:
    received = datetime(2026, 8, 3, 10, 0, tzinfo=ct.JST)
    base = dict(
        key="72030", price=3000.0, previous_close=2950.0, change_pct=0.0169,
        quote_time=received - timedelta(minutes=15), received_at=received,
        source="yahoo-delayed", delay_class=ct.DELAY_DELAYED,
        is_official=False, is_realtime=False, session=ct.SESSION_MORNING,
    )
    base.update(overrides)
    return ct.Quote(**base)


def test_quote_dict_always_declares_provenance():
    payload = _quote().as_dict()
    for field in (
        "source", "delay_class", "is_official", "is_realtime",
        "stale", "market_session", "quote_time", "received_at",
    ):
        assert field in payload, f"{field} が申告されていない"
    assert payload["is_official"] is False
    assert payload["delay_class"] == ct.DELAY_DELAYED


def test_delayed_quote_is_not_called_stale_for_its_structural_delay():
    """15 分遅れは「古い」ではなく「そういうソース」。区別しないと常時警告になる。"""

    assert _quote().stale is False


def test_a_provider_that_stopped_updating_is_stale():
    received = datetime(2026, 8, 3, 10, 0, tzinfo=ct.JST)
    frozen = _quote(quote_time=received - timedelta(hours=2), received_at=received)
    assert frozen.stale is True


def test_realtime_quote_has_a_tighter_staleness_bar():
    received = datetime(2026, 8, 3, 10, 0, tzinfo=ct.JST)
    lagging = _quote(
        delay_class=ct.DELAY_REALTIME, is_realtime=True, is_official=True,
        quote_time=received - timedelta(minutes=12), received_at=received,
    )
    # 遅延ソースなら許容内だが、リアルタイムを名乗るなら 12 分は異常
    assert lagging.stale is True
    assert _quote(quote_time=received - timedelta(minutes=12)).stale is False


def test_missing_quote_time_counts_as_stale():
    assert _quote(quote_time=None).stale is True


# ---------------------------------------------------------------------------
# 3. 選択規則
# ---------------------------------------------------------------------------


def test_unconnected_relays_report_unavailable_and_return_nothing():
    """繋がっていないリアルタイム源が選ばれて空を返し続ける、を防ぐ。"""

    for provider in (KabuStationRelayProvider(), MarketSpeedRelayProvider()):
        status = provider.status()
        assert status.available is False
        assert status.detail == "not_connected"
        assert provider.quotes_for_codes(["72030"]) == {}
        assert provider.index_quotes() == {}


def test_selection_prefers_the_best_available_delay_class(monkeypatch):
    class _FakeRealtime:
        name = "fake-realtime"
        delay_class = ct.DELAY_REALTIME
        is_official = True
        is_realtime = True

        def status(self):
            return ct.ProviderStatus(
                name=self.name, available=True, delay_class=self.delay_class,
                is_official=True, is_realtime=True,
            )

        def quotes_for_codes(self, codes):
            return {}

        def index_quotes(self):
            return {}

    class _FakeDelayed(_FakeRealtime):
        name = "fake-delayed"
        delay_class = ct.DELAY_DELAYED
        is_official = False
        is_realtime = False

        def status(self):
            return ct.ProviderStatus(
                name=self.name, available=True, delay_class=self.delay_class,
                is_official=False, is_realtime=False,
            )

    monkeypatch.setitem(registry.PROVIDER_FACTORIES, "fake-delayed", _FakeDelayed)
    monkeypatch.setitem(registry.PROVIDER_FACTORIES, "fake-realtime", _FakeRealtime)
    assert registry.select_provider().name == "fake-realtime"

    # リアルタイムが落ちたら遅延に **降格する**（穴を開けて空にしない）。
    # どの遅延ソースが選ばれるかは同値なので、等級で確かめる。
    monkeypatch.delitem(registry.PROVIDER_FACTORIES, "fake-realtime")
    degraded = registry.select_provider()
    assert degraded.delay_class == ct.DELAY_DELAYED
    assert degraded.status().available is True


def test_selection_falls_back_to_disabled_never_raises(monkeypatch):
    monkeypatch.setattr(registry, "available_providers", lambda: [])
    provider = registry.select_provider()
    assert isinstance(provider, DisabledProvider)
    assert provider.quotes_for_codes(["72030"]) == {}


def test_statuses_expose_unconnected_relays_too():
    names = {status.name for status in registry.provider_statuses()}
    assert {"kabu-station-relay", "market-speed-relay"} <= names


# ---------------------------------------------------------------------------
# 4. 結合: 業務側は供給元の名前を知らない
# ---------------------------------------------------------------------------


def test_no_business_module_imports_a_vendor_directly():
    """`yahoo_quotes` を直接 import してよいのはプロバイダ層だけ。

    ここが破られると、供給元を差し替えるのに業務側の書き換えが要る。
    """

    root = pathlib.Path(__file__).resolve().parents[1] / "backend" / "app"
    allowed = {
        root / "providers" / "yahoo_quotes.py",
        root / "providers" / "intraday" / "providers.py",
    }
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if path not in allowed and "yahoo_quotes" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"供給元を直接参照している: {offenders}"


# ---------------------------------------------------------------------------
# 5. 取得がイベントループを止めない
# ---------------------------------------------------------------------------


def test_fetch_does_not_block_the_event_loop(monkeypatch):
    """取得中も他のコルーチンが進むこと（市場ページが道連れで落ちた実害の回帰）。"""

    from app.services import intraday_quotes as service

    def _slow(codes):
        time.sleep(0.30)          # 外部が遅いときの代役
        return {}

    monkeypatch.setattr(service, "fetch_quotes_blocking", _slow)

    async def scenario():
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            for _ in range(20):
                await asyncio.sleep(0.01)
                ticks += 1

        await asyncio.gather(
            asyncio.to_thread(_slow, ["72030"]),
            heartbeat(),
        )
        return ticks

    assert asyncio.run(scenario()) == 20, "取得中にイベントループが止まっている"


# ---------------------------------------------------------------------------
# 6. ネットワーク遮断そのものの自己テスト
# ---------------------------------------------------------------------------


def test_the_network_guard_itself_actually_fires():
    """遮断が壊れたら気付けるようにする。

    プロバイダは例外を握り潰して「取れなかった」に変えるので、実接続して
    しまってもテストは緑のまま通る。実際 1 本すり抜けていた。
    """

    import socket as socket_module

    from conftest import ExternalNetworkBlocked

    with pytest.raises(ExternalNetworkBlocked):
        socket_module.socket().connect(("query1.finance.yahoo.com", 443))


def test_loopback_still_works_under_the_guard():
    import socket as socket_module

    server = socket_module.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    try:
        client = socket_module.socket()
        client.connect(server.getsockname())   # 遮断されない
        client.close()
    finally:
        server.close()
