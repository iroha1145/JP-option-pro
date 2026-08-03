"""ティック分析: VWAP・大口・出来高分布・板寄せ。"""

from app.services.tick_analytics import (
    analyse,
    auction_summary,
    large_prints,
    volume_profile,
    vwap_series,
)


def _tick(time, price, volume):
    return {"tick_time": time, "price": price, "volume": volume}


def test_vwap_is_volume_weighted_not_a_simple_mean():
    """分足の平均で代用できないことを、重みが効くケースで固定する。"""

    rows = [_tick("09:00:00", 100.0, 1_000_000), _tick("09:01:00", 200.0, 1.0)]
    pack = vwap_series(rows)
    # 加重平均は 100.0001…（単純平均なら 150）。重みが効いていることが要点。
    assert 100.0 <= pack["vwap"] < 100.1
    assert pack["last_price"] == 200.0
    assert pack["deviation_pct"] > 0.9


def test_vwap_missing_volume_does_not_crash_or_fabricate():
    rows = [_tick("09:00:00", 100.0, None), _tick("09:01:00", 101.0, None)]
    pack = vwap_series(rows)
    assert pack["vwap"] is None and pack["deviation_pct"] is None


def test_auctions_use_first_and_last_print_not_the_clock():
    """特別気配で寄りが遅れる銘柄がある（実測 7203 は 09:03 寄り）。"""

    rows = [
        _tick("09:03:00.050", 3032.0, 1_875_600),   # 寄付（09:00 ではない）
        _tick("09:04:00.000", 3040.0, 1_000),
        _tick("12:30:00.053", 3055.0, 508_000),     # 後場寄り
        _tick("14:00:00.000", 3050.0, 2_000),
        _tick("15:30:00.000", 3067.0, 10_487_800),  # 引け
    ]
    summary = auction_summary(rows)
    assert summary["opening"]["time"].startswith("09:03")
    assert summary["opening"]["volume"] == 1_875_600
    assert summary["closing"]["volume"] == 10_487_800
    assert summary["afternoon_open"]["time"].startswith("12:30")
    # 引けが当日出来高に占める比重が出ること（この標本では 10,487,800/12,874,400）
    share = summary["closing"]["day_volume_share"]
    assert abs(share - 10_487_800 / 12_874_400) < 1e-9
    assert share > summary["opening"]["day_volume_share"]


def test_large_prints_exclude_the_auctions_and_scale_with_the_stock():
    """板寄せは常に最大なので、除外しないと「大口」が毎日それだけになる。"""

    rows = [_tick("09:00:00", 100.0, 5_000_000)]                 # 寄付
    rows += [_tick(f"10:{m:02d}:00", 100.0, 200) for m in range(60)]  # 通常売買
    rows += [_tick("11:00:00", 101.0, 300_000)]                  # 日中の大口
    rows += [_tick("15:30:00", 100.0, 4_000_000)]                # 引け
    pack = large_prints(rows)
    times = [row["time"] for row in pack["rows"]]
    assert any(t.startswith("11:00") for t in times)
    assert not any(t.startswith("09:00") or t.startswith("15:30") for t in times)
    assert pack["median_size"] == 200


def test_large_print_threshold_needs_both_conditions():
    """中央値比だけだと閑散銘柄で通常売買が大量に「大口」になる。"""

    rows = [_tick(f"10:{m:02d}:00", 100.0, 100) for m in range(30)]
    rows += [_tick("11:00:00", 100.0, 3_000)]  # 中央値の 30 倍だが当日比では小さい
    pack = large_prints(rows)
    day_volume = 30 * 100 + 3_000
    assert pack["threshold"] >= day_volume * 0.002
    assert pack["count"] <= 1


def test_volume_profile_finds_the_price_with_the_most_volume():
    rows = [_tick("09:00:00", 100.0, 10), _tick("09:01:00", 150.0, 900), _tick("09:02:00", 200.0, 10)]
    profile = volume_profile(rows, buckets=10)
    assert profile["low"] == 100.0 and profile["high"] == 200.0
    assert 145.0 <= profile["poc"] <= 155.0
    assert sum(b["volume"] for b in profile["buckets"]) == 920


def test_analyse_reports_unavailable_rather_than_zeros_when_empty():
    pack = analyse([])
    assert pack["available"] is False
    assert pack["vwap"] is None and pack["auctions"] is None
