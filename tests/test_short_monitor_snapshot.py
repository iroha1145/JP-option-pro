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


def test_the_same_shorting_gets_the_same_state_whatever_the_price_does():
    """株価の動きは状態に入らない。増空は下げていても耐えていても「增加中」。

    旧版は同じ増空を、株価しだいで「正常做空」「背离失效」「卖压吸收」に
    振り分けていた。3 回の検証でその振り分けに予測力が無かったので、状態は
    公開持仓比率の純変化だけで決める。株価は事実として横に並ぶだけ。
    """

    def state_for(drift):
        subject = _stock(
            "1000",
            bars=_bars("1000", drift=drift),
            reports=_shorting_reports("1000", when_old=OLD_DAY, when_new=NEW_DAY,
                                      old_shares=100_000, new_shares=600_000),
        )
        peers = [_stock(f"90{i:02d}", bars=_bars(f"90{i:02d}", drift=0.001)) for i in range(6)]
        return _by_code(snap.build_snapshots([subject, *peers], _market()))["1000"]

    falling, flat, rising = state_for(-0.004), state_for(0.0), state_for(0.004)
    assert falling["pressure_adv20_20d"] > 0
    assert falling["ratio_change_20d"] >= states.CHANGE_FLOOR_RATIO
    assert falling["primary_state"] == flat["primary_state"] == rising["primary_state"] == states.STATE_BUILDING
    # 株価は事実として残る（状態には使わない）
    assert falling["drawdown_52w"] != rising["drawdown_52w"]


def test_a_net_reduction_is_covering_and_the_other_holder_still_counts():
    """純減は「减少中」。残っている建玉は合計に残り、回補日数にも効く。"""

    covering = _stock(
        "1000",
        bars=_bars("1000", drift=0.004),
        reports=[
            _report("1000", "Alpha", OLD_DAY, 0.030, shares=3_000_000),
            _report("1000", "Alpha", NEW_DAY, 0.008, prev=0.030, shares=800_000),
            _report("1000", "Beta", OLD_DAY, 0.020, shares=2_000_000),
            _report("1000", "Beta", NEW_DAY, 0.009, prev=0.020, shares=900_000),
        ],
    )
    peers = [_stock(f"90{i:02d}", bars=_bars(f"90{i:02d}")) for i in range(5)]
    row = _by_code(snap.build_snapshots([covering, *peers], _market()))["1000"]
    assert row["primary_state"] == states.STATE_COVERING
    assert row["ratio_change_20d"] == pytest.approx(0.017 - 0.050)
    assert row["visible_short_ratio"] == pytest.approx(0.017)
    assert row["visible_days_to_cover"] is not None and row["visible_days_to_cover"] >= 1.0


def test_every_score_column_is_none():
    """合成点数は取り消した（v4）。列は表に残るが、値は常に None。"""

    shorting = _stock(
        "1000", bars=_bars("1000", drift=-0.004),
        reports=_shorting_reports("1000", when_old=OLD_DAY, when_new=NEW_DAY,
                                  old_shares=100_000, new_shares=600_000),
    )
    peers = [_stock(f"90{i:02d}", bars=_bars(f"90{i:02d}", drift=0.001)) for i in range(6)]
    rows = snap.build_snapshots([shorting, *peers], _market())
    assert len(rows) == 7
    score_columns = (
        "behavior_score", "monitor_priority", "low_position_score", "short_pressure_score",
        "price_damage_score", "absorption_score", "covering_score", "rotation_score",
        "catalyst_score", "risk_score",
    )
    for row in rows:
        for column in score_columns:
            assert row[column] is None, f"{row['canonical_code']}.{column}"

    row = _by_code(rows)["1000"]
    components = json.loads(row["components_json"])
    assert components["crowding_level"] == states.CROWDING_LOW     # 1 社 / 約 0.6%
    assert "days_since_last_report" in components
    assert isinstance(components["days_since_last_report"], int)
    assert 0 <= components["days_since_last_report"] <= 3     # 報告は 2 営業日前
    # 公開持仓の無い銘柄は拥挤度 0
    quiet = json.loads(_by_code(rows)["9000"]["components_json"])
    assert quiet["crowding_level"] == states.CROWDING_NONE


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
    for part in ("inst-v4", "evt-v4", "sbf-v3", "sbs-v4"):
        assert part in snap.SNAPSHOT_VERSION
    assert "sbscore-" not in snap.SNAPSHOT_VERSION, "合成点数の版が残っている"


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
    a = snap.signal_id_for("1000", "2026-08-03", states.STATE_BUILDING)
    b = snap.signal_id_for("1000", "2026-08-03", states.STATE_BUILDING)
    assert a == b
    assert a != snap.signal_id_for("1000", "2026-08-04", states.STATE_BUILDING)


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


# -- 第十四轮: informed 口径 / 潜伏空頭 ------------------------------------------

def test_aggregate_only_covering_does_not_start_covering():
    """「個人」名義だけが減らしたときは、informed 口径が空であることを印で示す。"""

    individuals = _stock(
        "1000",
        bars=_bars("1000", drift=0.004),
        reports=[
            _report("1000", "個人", OLD_DAY, 0.030, shares=3_000_000),
            _report("1000", "個人", NEW_DAY, 0.008, prev=0.030, shares=800_000),
        ],
    )
    peers = [_stock(f"90{i:02d}", bars=_bars(f"90{i:02d}")) for i in range(5)]
    rows = _by_code(snap.build_snapshots([individuals, *peers], _market()))
    row = rows["1000"]
    components = json.loads(row["components_json"])
    assert components["informed"]["institution_count"] == 0
    assert components["informed"]["pressure_20d"]["pressure_adv20"] is None
    assert components["reporter_classes"] == {"aggregate": 1}
    # 旧版は informed 口径が空なら回補開始にしなかった。v4 は閘門を持たず、
    # 状態は公開持仓の純変化どおり「减少中」。印だけが付く。
    assert row["primary_state"] == states.STATE_COVERING
    flags = json.loads(row["flags_json"])
    assert states.FLAG_NO_INFORMED_REPORTER in flags
    # 全鎖口径の圧力そのものは従来どおり出る（どちらか一方を正とはしない）
    assert row["pressure_adv20_20d"] is not None and row["pressure_adv20_20d"] < 0


def test_domestic_broker_covering_counts_as_informed_after_calibration():
    """クラス単位の校正で国内証券は海外 PB と同水準（−2.15% vs −2.27%）: informed に含める。"""

    domestic = _stock(
        "1000",
        bars=_bars("1000", drift=0.004),
        reports=[
            _report("1000", "野村證券株式会社", OLD_DAY, 0.030, shares=3_000_000),
            _report("1000", "野村證券株式会社", NEW_DAY, 0.008, prev=0.030, shares=800_000),
        ],
    )
    peers = [_stock(f"90{i:02d}", bars=_bars(f"90{i:02d}")) for i in range(5)]
    rows = _by_code(snap.build_snapshots([domestic, *peers], _market()))
    row = rows["1000"]
    components = json.loads(row["components_json"])
    assert components["reporter_classes"] == {"domestic_broker": 1}
    assert components["informed"]["institution_count"] == 1
    assert row["primary_state"] == states.STATE_COVERING
    assert states.FLAG_NO_INFORMED_REPORTER not in json.loads(row["flags_json"])


def test_informed_pressure_matches_all_chain_pressure_when_all_reporters_are_informed():
    covering = _stock(
        "1000",
        bars=_bars("1000", drift=0.004),
        reports=[
            _report("1000", "Nomura International plc", OLD_DAY, 0.030, shares=3_000_000),
            _report("1000", "Nomura International plc", NEW_DAY, 0.008, prev=0.030, shares=800_000),
        ],
    )
    peers = [_stock(f"90{i:02d}", bars=_bars(f"90{i:02d}")) for i in range(5)]
    rows = _by_code(snap.build_snapshots([covering, *peers], _market()))
    row = rows["1000"]
    components = json.loads(row["components_json"])
    assert components["informed"]["institution_count"] == 1
    assert components["informed"]["pressure_20d"]["pressure_adv20"] == pytest.approx(row["pressure_adv20_20d"])
    assert row["primary_state"] == states.STATE_COVERING
    assert components["reporter_classes"] == {"global_pb": 1}


def test_parked_below_holder_is_counted_and_flagged():
    parked = _stock(
        "1000",
        reports=[
            _report("1000", "Alpha", OLD_DAY, 0.0060, shares=600_000),
            # 閾値割れの最終報告 —— 公開線のすぐ下に止まる
            _report("1000", "Alpha", NEW_DAY, 0.0047, prev=0.0060, shares=470_000),
        ],
    )
    peers = [_stock(f"90{i:02d}", bars=_bars(f"90{i:02d}")) for i in range(5)]
    rows = _by_code(snap.build_snapshots([parked, *peers], _market()))
    row = rows["1000"]
    components = json.loads(row["components_json"])
    assert components["parked_below_count"] == 1
    assert states.FLAG_PARKED_BELOW in json.loads(row["flags_json"])
    assert row["below_threshold_count"] == 1
    assert row["visible_short_ratio"] == 0.0
