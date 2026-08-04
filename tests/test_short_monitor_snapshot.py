"""スナップショット組み立て（横断面分位を含む一気通貫）。"""

import json

import pytest

from app.services.short_monitor import events as ev
from app.services.short_monitor import snapshot as snap
from app.services.short_monitor import states
from app.services.short_monitor.institutions import InstitutionResolver


DAYS = [f"2026-{m:02d}-{d:02d}" for m in (4, 5, 6, 7) for d in range(1, 29)]
DAYS = sorted(DAYS)[-120:]
AS_OF = DAYS[-1]


def _bars(code, *, start=1000.0, drift=0.0, volume=1_000_000, days=None):
    """等間隔の合成足。分割は無し（調整係数 1.0）。"""

    days = days or DAYS
    out = []
    price = start
    for day in days:
        price = price * (1.0 + drift)
        out.append({
            "canonical_code": code, "trade_date": day,
            "open": price, "high": price * 1.01, "low": price * 0.99, "close": price,
            "volume": volume, "turnover_value": price * volume,
            "adjustment_factor": 1.0,
            "adj_open": None, "adj_high": None, "adj_low": None, "adj_close": None,
            "adj_volume": None, "upper_limit": 0,
        })
    return out


def _report(code, holder, calc, ratio, prev=None, shares=None, disc=None):
    return {
        "canonical_code": code, "holder_name": holder,
        "calculated_date": calc, "disclosed_date": disc or calc,
        "short_position_ratio": ratio, "previous_ratio": prev,
        "short_position_shares": shares, "notes": "-", "previous_report_date": "",
    }


def _events(rows):
    def first_tradable(day):
        # 厳密に後（公表は当日引け後）
        for candidate in DAYS:
            if candidate > day:
                return candidate
        return None

    return ev.build_events(rows, resolver=InstitutionResolver(), first_tradable_day=first_tradable)


def _market(**kwargs):
    closes = {day: 1000.0 for day in DAYS}
    return snap.MarketInputs(as_of_date=AS_OF, trading_days=list(DAYS), topix_closes=closes, **kwargs)


def _stock(code, *, bars=None, reports=(), **kwargs):
    return snap.StockInputs(
        canonical_code=code,
        bars=bars if bars is not None else _bars(code),
        events=_events(list(reports)),
        sector33_code=kwargs.pop("sector33_code", "3650"),
        **kwargs,
    )


def _by_code(rows):
    return {row["canonical_code"]: row for row in rows}


def _shorting_reports(code, *, when_old, when_new, old_shares, new_shares, adv=1_000_000):
    """20 営業日で建玉が増える 2 本の報告。"""

    return [
        _report(code, "Alpha", when_old, old_shares / (adv * 100), shares=old_shares),
        _report(code, "Alpha", when_new, new_shares / (adv * 100),
                prev=old_shares / (adv * 100), shares=new_shares),
    ]


OLD_DAY = DAYS[-30]
NEW_DAY = DAYS[-3]


def test_shorting_into_a_falling_stock_is_not_called_absorption():
    """增空且大跌 → 空頭圧力が効いている。吸収とは呼ばない。"""

    falling = _stock(
        "1000",
        bars=_bars("1000", drift=-0.004),
        reports=_shorting_reports("1000", when_old=OLD_DAY, when_new=NEW_DAY,
                                  old_shares=100_000, new_shares=600_000),
    )
    # 横断面を作るための対照群（圧力なし）
    peers = [_stock(f"90{i:02d}", bars=_bars(f"90{i:02d}", drift=0.001)) for i in range(6)]
    rows = _by_code(snap.build_snapshots([falling, *peers], _market()))

    row = rows["1000"]
    assert row["pressure_adv20_20d"] > 0
    assert row["primary_state"] in (
        states.STATE_NORMAL_SHORTING, states.STATE_DIVERGENCE_FAILED,
    )
    assert row["primary_state"] != states.STATE_ABSORPTION


def test_shorting_that_does_not_hurt_the_price_becomes_an_absorption_candidate():
    """增空但不跌 → 卖压吸收候补。"""

    holding = _stock(
        "1000",
        bars=_bars("1000", drift=0.0),
        reports=_shorting_reports("1000", when_old=OLD_DAY, when_new=NEW_DAY,
                                  old_shares=100_000, new_shares=600_000),
    )
    # 同じ圧力で価格が削られた銘柄を並べて横断面を作る
    hurt = [
        _stock(
            f"20{i:02d}", bars=_bars(f"20{i:02d}", drift=-0.006),
            reports=_shorting_reports(f"20{i:02d}", when_old=OLD_DAY, when_new=NEW_DAY,
                                      old_shares=100_000, new_shares=600_000),
        )
        for i in range(6)
    ]
    rows = _by_code(snap.build_snapshots([holding, *hurt], _market()))

    assert rows["1000"]["absorption_score"] is not None
    assert rows["1000"]["absorption_score"] > rows["2000"]["absorption_score"]
    assert rows["1000"]["price_damage_score"] < rows["2000"]["price_damage_score"]


def test_absorption_is_cross_sectional_not_an_imported_threshold():
    """同じ銘柄でも、その日の全体がどうだったかで評価が変わる。

    絶対閾値を輸入していないことの確認。
    """

    def run(peer_drift):
        subject = _stock(
            "1000", bars=_bars("1000", drift=-0.001),
            reports=_shorting_reports("1000", when_old=OLD_DAY, when_new=NEW_DAY,
                                      old_shares=100_000, new_shares=600_000),
        )
        peers = [
            _stock(
                f"20{i:02d}", bars=_bars(f"20{i:02d}", drift=peer_drift),
                reports=_shorting_reports(f"20{i:02d}", when_old=OLD_DAY, when_new=NEW_DAY,
                                          old_shares=100_000, new_shares=600_000),
            )
            for i in range(8)
        ]
        return _by_code(snap.build_snapshots([subject, *peers], _market()))["1000"]

    among_survivors = run(+0.004)   # 周りは耐えている → 相対的に弱い
    among_casualties = run(-0.008)  # 周りは崩れている → 相対的に強い
    assert among_casualties["absorption_score"] > among_survivors["absorption_score"]


def test_covering_with_breakout_reaches_squeeze_confirmed():
    """减空 + 突破 + 成交额确认 + 相对转强 → 挤空确认。"""

    covering = _stock(
        "1000",
        bars=_bars("1000", drift=0.004),
        reports=[
            _report("1000", "Alpha", OLD_DAY, 0.030, shares=3_000_000),
            _report("1000", "Alpha", NEW_DAY, 0.008, prev=0.030, shares=800_000),
            # なお残っている建玉。全部消えたなら「まだ踏み上げる燃料がある」
            # とは言えないので、この銘柄は挤空確認に届かないのが正しい。
            _report("1000", "Beta", OLD_DAY, 0.020, shares=2_000_000),
            _report("1000", "Beta", NEW_DAY, 0.009, prev=0.020, shares=900_000),
        ],
        breakout_confirmed=True,
        turnover_confirmed=True,
    )
    peers = [_stock(f"90{i:02d}", bars=_bars(f"90{i:02d}")) for i in range(5)]
    rows = _by_code(snap.build_snapshots([covering, *peers], _market()))

    row = rows["1000"]
    assert row["visible_days_to_cover"] is not None and row["visible_days_to_cover"] >= 1.0
    assert row["primary_state"] == states.STATE_SQUEEZE_CONFIRMED


def test_the_same_covering_without_a_breakout_stops_at_covering_start():
    covering = _stock(
        "1000",
        bars=_bars("1000", drift=0.004),
        reports=[
            _report("1000", "Alpha", OLD_DAY, 0.030, shares=3_000_000),
            _report("1000", "Alpha", NEW_DAY, 0.008, prev=0.030, shares=800_000),
        ],
        breakout_confirmed=False, turnover_confirmed=False,
    )
    peers = [_stock(f"90{i:02d}", bars=_bars(f"90{i:02d}")) for i in range(5)]
    rows = _by_code(snap.build_snapshots([covering, *peers], _market()))
    assert rows["1000"]["primary_state"] == states.STATE_COVERING_START


def test_a_stock_with_no_institutional_activity_gets_no_signal():
    """深度低位でも空頭に動きが無ければ、この模块は信号を出さない。"""

    quiet = _stock("1000", bars=_bars("1000", drift=-0.006))
    peers = [_stock(f"90{i:02d}") for i in range(4)]
    rows = _by_code(snap.build_snapshots([quiet, *peers], _market()))
    row = rows["1000"]
    assert row["primary_state"] == states.STATE_NO_SIGNAL
    assert row["visible_institution_count"] == 0
    assert states.FLAG_NOT_VISIBLE in json.loads(row["flags_json"])


def test_below_threshold_holders_are_counted_but_not_summed():
    subject = _stock(
        "1000",
        reports=[
            _report("1000", "Reporting", NEW_DAY, 0.0123, shares=395_600),
            _report("1000", "Below", NEW_DAY, 0.0040, prev=0.0051, shares=131_200),
        ],
    )
    peers = [_stock(f"90{i:02d}") for i in range(4)]
    row = _by_code(snap.build_snapshots([subject, *peers], _market()))["1000"]
    assert row["visible_short_ratio"] == pytest.approx(0.0123)
    assert row["visible_institution_count"] == 1
    assert row["below_threshold_count"] == 1


def test_snapshot_carries_the_algorithm_version():
    rows = snap.build_snapshots([_stock("1000")], _market())
    assert rows and rows[0]["algorithm_version"] == snap.SNAPSHOT_VERSION
    assert "inst-" in snap.SNAPSHOT_VERSION and "sbscore-" in snap.SNAPSHOT_VERSION


def test_signals_are_only_emitted_on_state_change():
    rows = snap.build_snapshots(
        [_stock("1000", bars=_bars("1000", drift=-0.006),
                reports=_shorting_reports("1000", when_old=OLD_DAY, when_new=NEW_DAY,
                                          old_shares=100_000, new_shares=600_000)),
         *[_stock(f"90{i:02d}") for i in range(4)]],
        _market(),
    )
    state = _by_code(rows)["1000"]["primary_state"]

    fresh = snap.build_signals(rows, {}, source_cutoff=AS_OF)
    assert any(s["canonical_code"] == "1000" for s in fresh)

    unchanged = snap.build_signals(rows, {"1000": state}, source_cutoff=AS_OF)
    assert not any(s["canonical_code"] == "1000" for s in unchanged)


def test_signal_ids_are_stable():
    a = snap.signal_id_for("1000", "2026-08-03", states.STATE_ABSORPTION)
    b = snap.signal_id_for("1000", "2026-08-03", states.STATE_ABSORPTION)
    assert a == b
    assert a != snap.signal_id_for("1000", "2026-08-04", states.STATE_ABSORPTION)


def test_short_price_history_is_skipped_rather_than_guessed():
    """足が足りない銘柄で無理に判定しない。"""

    tiny = snap.StockInputs(canonical_code="1000", bars=_bars("1000", days=DAYS[:10]))
    assert snap.build_snapshots([tiny], _market()) == []


def test_signals_record_the_information_cutoff():
    rows = snap.build_snapshots(
        [_stock("1000", bars=_bars("1000", drift=-0.006),
                reports=_shorting_reports("1000", when_old=OLD_DAY, when_new=NEW_DAY,
                                          old_shares=100_000, new_shares=600_000)),
         *[_stock(f"90{i:02d}") for i in range(4)]],
        _market(),
    )
    signals = snap.build_signals(rows, {}, source_cutoff=AS_OF)
    assert signals and all(s["source_cutoff"] == AS_OF for s in signals)
