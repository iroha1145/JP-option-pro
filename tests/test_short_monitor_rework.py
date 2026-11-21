"""2026-11 の作り直し（inst-v4 / evt-v4 / sbf-v3 / sbs-v4）が守るべき不変量。

どれも本番データで実際に起きていた不具合か、検証で否定された読みに対応する。
数字の出どころは docs/short-monitor.md §12。
"""

from app.services.short_monitor import events as ev
from app.services.short_monitor import factors as fac
from app.services.short_monitor import states
from app.services.short_monitor.institutions import InstitutionResolver

TRADING_DAYS = [
    "2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03",
    "2026-07-29", "2026-07-30", "2026-07-31", "2026-08-03", "2026-08-04",
    "2026-08-05", "2026-08-06", "2026-08-07", "2026-11-18", "2026-11-19", "2026-11-20",
]

LONDON = "Plumtree Court, 25 Shoe Lane, London"
LONDON_SHORT = "25 Shoe Lane London"
NEW_YORK = "388 Greenwich Street, New York"


def _first_tradable_day(day):
    for candidate in TRADING_DAYS:
        if candidate > day:
            return candidate
    return None


def _row(holder, calc, ratio, *, prev=None, disc=None, shares=None, address="", fund="-"):
    return {
        "canonical_code": "77770", "holder_name": holder, "holder_address": address,
        "investment_fund_name": fund,
        "calculated_date": calc, "disclosed_date": disc or calc,
        "short_position_ratio": ratio, "previous_ratio": prev,
        "short_position_shares": shares, "notes": "-", "previous_report_date": "",
    }


def _events(rows):
    return ev.build_events(
        rows, resolver=InstitutionResolver(), first_tradable_day=_first_tradable_day,
    )


# ---------------------------------------------------------------------------
# 実体: 住所の違いだけでは分けない
# ---------------------------------------------------------------------------

def test_rows_without_an_address_continue_the_same_chain_as_rows_with_one():
    """一括配信（住所欄なし）→ 日次配信（住所つき）の切り替えで連鎖が切れない。

    本番では住所なしの連鎖が `-noaddr` という別実体になり、7 月末の値のまま
    「報告義務中」として合計に残った（1,133 銘柄の合計が誤り）。
    """

    events = _events([
        _row("Goldman Sachs International", "2026-07-29", 0.0607, shares=607_000),
        _row("Goldman Sachs International", "2026-08-05", 0.0550, prev=0.0607,
             shares=550_000, address=LONDON),
    ])
    assert len({event["legal_id"] for event in events}) == 1

    known = ev.last_known_as_of(events, published_cutoff="2026-08-07", trading_days=TRADING_DAYS[:13])
    totals = ev.visible_totals(known)
    assert totals["visible_institution_count"] == 1
    assert totals["visible_short_ratio"] == 0.0550      # 0.0607 + 0.0550 ではない


def test_an_exit_reported_with_an_address_closes_the_chain_reported_without_one():
    """住所つきの行で閾値を割ったら、住所なしの時代の値は合計から消える。"""

    events = _events([
        _row("JPM Securities Japan Co Ltd.", "2026-07-29", 0.0120),
        _row("JPM Securities Japan Co Ltd.", "2026-08-05", 0.0047, prev=0.0120, address="Tokyo Building"),
    ])
    known = ev.last_known_as_of(events, published_cutoff="2026-08-07", trading_days=TRADING_DAYS[:13])
    totals = ev.visible_totals(known)
    assert totals["visible_institution_count"] == 0
    assert totals["visible_short_ratio"] == 0.0
    assert totals["below_threshold_count"] == 1


def test_address_spelling_variants_are_one_entity():
    events = _events([
        _row("Goldman Sachs International", "2026-07-01", 0.0100, address=LONDON),
        _row("Goldman Sachs International", "2026-07-02", 0.0110, prev=0.0100, address=LONDON_SHORT),
    ])
    assert len({event["legal_id"] for event in events}) == 1


def test_the_same_report_delivered_with_and_without_an_address_is_one_event():
    """2026-07 は一括配信と日次配信が重なり、同じ報告が 2 行入っている。"""

    events = _events([
        _row("Barclays Capital Securities Ltd", "2026-07-01", 0.0100, shares=100_000),
        _row("Barclays Capital Securities Ltd", "2026-07-01", 0.0100, shares=100_000, address=LONDON),
    ])
    assert len(events) == 1
    assert events[0]["holder_address"] == LONDON        # 住所のある行を残す


def test_same_name_is_split_only_on_evidence_of_parallel_positions():
    """同じ仓位日に住所違いで **違う値** = 本当に別法人が並行している。

    本番 10 年分でこれに当たるのは 17,024 組のうち 1 組（Citigroup Global
    Markets のロンドンとニューヨーク）。その組だけ分ける。
    """

    events = _events([
        _row("Citigroup Global Markets", "2026-07-01", 0.0000, address=LONDON),
        _row("Citigroup Global Markets", "2026-07-01", 0.0076, address=NEW_YORK),
        _row("Citigroup Global Markets", "2026-07-02", 0.0080, prev=0.0076, address=NEW_YORK),
    ])
    assert len({event["legal_id"] for event in events}) == 2

    known = ev.last_known_as_of(events, published_cutoff="2026-07-03", trading_days=TRADING_DAYS[:5])
    assert ev.visible_totals(known)["visible_short_ratio"] == 0.0080


# ---------------------------------------------------------------------------
# 窓内の変化: 初出の起点は報告自身の前回値
# ---------------------------------------------------------------------------

def test_a_first_disclosure_counts_from_its_stated_previous_ratio():
    """0.43% → 0.53% の初出は +0.10 ポイント。「0 から 0.53%」ではない。"""

    events = _events([
        _row("Qube Research & Technologies Limited", "2026-08-03", 0.0053, prev=0.0043, shares=530_000),
    ])
    change = ev.window_changes(events, from_cutoff="2026-07-31", to_cutoff="2026-08-07")
    assert abs(change["ratio_change"] - 0.0010) < 1e-9
    assert abs(change["shares_change"] - 100_000) < 1e-6    # 530,000 × (0.10 / 0.53)


def test_a_first_disclosure_without_a_previous_ratio_still_counts_in_full():
    events = _events([_row("Alpha Capital", "2026-08-03", 0.0061, shares=610_000)])
    change = ev.window_changes(events, from_cutoff="2026-07-31", to_cutoff="2026-08-07")
    assert abs(change["ratio_change"] - 0.0061) < 1e-9
    assert change["shares_change"] == 610_000


def test_a_reentry_counts_from_its_stated_previous_ratio_not_the_old_exit_value():
    events = _events([
        _row("Alpha Capital", "2026-06-29", 0.0060, shares=600_000),
        _row("Alpha Capital", "2026-06-30", 0.0047, prev=0.0060, shares=470_000),   # 閾値割れ
        _row("Alpha Capital", "2026-08-04", 0.0056, prev=0.0031, shares=560_000),   # 再参入
    ])
    change = ev.window_changes(events, from_cutoff="2026-07-31", to_cutoff="2026-08-07")
    assert abs(change["ratio_change"] - 0.0025) < 1e-9


def test_a_chain_already_reporting_before_the_window_still_uses_its_public_value():
    """窓の前から報告義務中だった連鎖は、公開されていた値が起点（従来どおり）。"""

    events = _events([
        _row("Alpha Capital", "2026-07-29", 0.0060, shares=600_000),
        _row("Alpha Capital", "2026-08-04", 0.0049, prev=0.0060, shares=490_000),
    ])
    change = ev.window_changes(events, from_cutoff="2026-07-31", to_cutoff="2026-08-07")
    assert abs(change["ratio_change"] + 0.0011) < 1e-9
    assert change["shares_change"] == -110_000              # −600,000 ではない


# ---------------------------------------------------------------------------
# 状態: 公開持仓比率の純変化だけで決める
# ---------------------------------------------------------------------------

def _state(**evidence):
    return states.classify({"visible_institution_count": 2, **evidence})["primary_state"]


def test_states_follow_the_net_change_in_the_disclosed_ratio():
    assert _state(ratio_change_20d=0.0030, ratio_change_5d=0.0005) == states.STATE_BUILDING
    assert _state(ratio_change_20d=-0.0030, ratio_change_5d=0.0) == states.STATE_COVERING
    assert _state(ratio_change_20d=0.0004, ratio_change_5d=0.0002) == states.STATE_STEADY


def test_a_net_decrease_is_never_labelled_as_building():
    """旧版は 20 日で −2.5 日分の純減でも、直近 5 日が少し増えただけで
    「正常做空」「背离失效」（空頭が増え続けている）と表示していた。"""

    assert _state(ratio_change_20d=-0.0100, ratio_change_5d=0.0015) == states.STATE_MIXED
    assert _state(ratio_change_20d=0.0100, ratio_change_5d=-0.0015) == states.STATE_MIXED


def test_a_change_below_the_reporting_step_is_not_a_state():
    step = states.CHANGE_FLOOR_RATIO
    assert _state(ratio_change_20d=step * 0.9, ratio_change_5d=0.0) == states.STATE_STEADY
    assert _state(ratio_change_20d=step, ratio_change_5d=0.0) == states.STATE_BUILDING


def test_no_visible_short_and_no_change_is_no_signal():
    verdict = states.classify({"visible_institution_count": 0})
    assert verdict["primary_state"] == states.STATE_NO_SIGNAL
    assert states.FLAG_NOT_VISIBLE in verdict["flags"]
    assert verdict["crowding_level"] == states.CROWDING_NONE


def test_price_does_not_enter_the_state():
    """同じ空頭の変化なら、株価がどう動いていても同じ状態。"""

    base = {"ratio_change_20d": 0.0030, "ratio_change_5d": 0.0010}
    strong = _state(**base, rel_topix_20d=0.30, rel_sector_20d=0.25, breakout_confirmed=True)
    weak = _state(**base, rel_topix_20d=-0.30, rel_sector_20d=-0.25, made_new_low=True)
    assert strong == weak == states.STATE_BUILDING


# ---------------------------------------------------------------------------
# 拥挤度: 固定の区切り
# ---------------------------------------------------------------------------

def test_crowding_level_uses_fixed_cutoffs_on_two_checkable_facts():
    assert states.crowding_level(0, 0.0) == states.CROWDING_NONE
    assert states.crowding_level(1, 0.0060) == states.CROWDING_LOW
    assert states.crowding_level(2, 0.0110) == states.CROWDING_MID      # 機関数で
    assert states.crowding_level(1, 0.0200) == states.CROWDING_MID      # 比率で
    assert states.crowding_level(4, 0.0250) == states.CROWDING_HIGH     # 機関数で
    assert states.crowding_level(3, 0.0400) == states.CROWDING_HIGH     # 比率で


def test_a_ratio_with_no_fresh_institution_is_not_crowded():
    """比率だけ残っていても、新鮮な報告義務中の機関が居なければ「無」。"""

    assert states.crowding_level(0, 0.05) == states.CROWDING_NONE


# ---------------------------------------------------------------------------
# データ信頼度: 表記の正規化だけでは下げない
# ---------------------------------------------------------------------------

def _confidence(**overrides):
    params = {
        "mapping_confidence": 1.0, "visible_institution_count": 3,
        "days_since_last_report": 2, "bars_available": 400, "adv20_value": 5e9,
    }
    params.update(overrides)
    return fac.data_confidence(**params)


def test_a_normalised_spelling_match_does_not_lower_confidence():
    """大手はほぼ全社が大小文字違いの表記を持つ。旧版はそれだけで 1,564 銘柄中
    1,450 銘柄を一律に下げ、信頼度が銘柄を区別しなくなっていた。"""

    merged = _confidence(mapping_confidence=InstitutionResolver.MERGED_CONFIDENCE)
    assert merged["confidence"] == 1.0
    assert merged["reasons"] == []


def test_an_aggregate_reporter_still_lowers_confidence():
    aggregate = _confidence(mapping_confidence=InstitutionResolver.AGGREGATE_CONFIDENCE)
    assert aggregate["confidence"] < 1.0
    assert "aggregate_reporter" in aggregate["reasons"]
