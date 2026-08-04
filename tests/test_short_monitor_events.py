"""機関実体の正規化とイベントの意味論。

指令書 §十七「数据语义」「点时语义」の各項目に対応する。
"""

import pytest

from app.services.short_monitor import events as ev
from app.services.short_monitor.institutions import (
    MATCH_AGGREGATE,
    MATCH_EXACT,
    MATCH_NORMALIZED,
    InstitutionResolver,
    normalize_name,
)


TRADING_DAYS = [
    "2026-07-16", "2026-07-17", "2026-07-21", "2026-07-22", "2026-07-23",
    "2026-07-24", "2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30",
    "2026-07-31", "2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06",
]


def _first_tradable_day(day: str) -> str | None:
    # **厳密に後**。JPX の公表は当日の取引終了後なので、公開日当日の終値は
    # その情報では取れない。
    for candidate in TRADING_DAYS:
        if candidate > day:
            return candidate
    return None


def _row(holder, calc, ratio, prev=None, disc=None, shares=None, notes="-"):
    return {
        "canonical_code": "39050", "holder_name": holder,
        "calculated_date": calc, "disclosed_date": disc or calc,
        "short_position_ratio": ratio, "previous_ratio": prev,
        "short_position_shares": shares, "notes": notes,
        "previous_report_date": "",
    }


def _events(rows, resolver=None):
    return ev.build_events(
        rows,
        resolver=resolver or InstitutionResolver(),
        first_tradable_day=_first_tradable_day,
    )


# -- 機関実体 ---------------------------------------------------------------

def test_case_and_width_differences_are_the_same_entity():
    resolver = InstitutionResolver()
    a = resolver.resolve("MORGAN STANLEY & CO. INTERNATIONAL PLC")
    b = resolver.resolve("Morgan Stanley & Co. International plc")
    assert a.legal_id == b.legal_id


def test_group_view_does_not_merge_legal_entities():
    """同じグループでも法的主体は別。下の行は分かれたまま。"""

    resolver = InstitutionResolver()
    jp = resolver.resolve("モルガン・スタンレーMUFG証券株式会社")
    uk = resolver.resolve("Morgan Stanley & Co. International plc")
    assert jp.legal_id != uk.legal_id, "別法人を 1 つに潰している"
    assert jp.group_id == uk.group_id == "morgan-stanley"


def test_similar_but_unrelated_names_are_not_merged():
    resolver = InstitutionResolver()
    a = resolver.resolve("Nomura International plc")
    b = resolver.resolve("Nomura Asset Management Singapore Limited")
    assert a.legal_id != b.legal_id, "名前が似ているだけで統合している"
    assert a.group_id == b.group_id == "nomura"


def test_merging_two_raw_spellings_lowers_confidence():
    """統合が起きたときだけ、統合が誤りうる。そのときだけ信頼度を下げる。"""

    resolver = InstitutionResolver()
    first = resolver.resolve("Barclays Capital Securities Ltd")
    assert first.match_kind == MATCH_EXACT and first.confidence == 1.0

    second = resolver.resolve("BARCLAYS CAPITAL SECURITIES LTD.")
    assert second.legal_id == first.legal_id
    assert second.match_kind == MATCH_NORMALIZED
    assert second.confidence < 1.0


def test_individual_is_an_aggregate_not_an_institution():
    """「個人」は法人名ではなく別人の集合。1 実体として数えると件数を誤る。"""

    mapping = InstitutionResolver().resolve("個人")
    assert mapping.is_aggregate
    assert mapping.match_kind == MATCH_AGGREGATE
    assert mapping.confidence < 0.5


def test_normalize_strips_only_legal_form_words():
    assert normalize_name("Jump Trading Pacific Pte Ltd") == "jump trading pacific"
    # 「証券」は営業実態の語 —— 法人形式（株式会社）だけ剥がす
    assert normalize_name("大和証券株式会社") == "大和証券"
    # 意味のある語は残す
    assert "asset management" in normalize_name("Nomura Asset Management Singapore Limited")


def test_business_words_are_not_stripped():
    """v1 は International/Securities/Capital まで剥がして
    `Barclays Capital Securities Ltd` を `barclays` に潰していた。"""

    assert normalize_name("Barclays Capital Securities Ltd") == "barclays capital securities"
    assert normalize_name("Morgan Stanley & Co. International plc") == "morgan stanley co international"
    assert normalize_name("Morgan Stanley & Co. LLC") == "morgan stanley co"


def test_us_and_uk_entities_of_the_same_group_stay_apart():
    resolver = InstitutionResolver()
    uk = resolver.resolve("Morgan Stanley & Co. International plc")
    us = resolver.resolve("Morgan Stanley & Co. LLC")
    assert uk.legal_id != us.legal_id, "英国法人と米国法人を 1 つに潰している"


def test_homonym_names_split_by_observed_address():
    """同じ正規化名に複数の住所が観測されたときだけ、住所で実体を分ける。"""

    resolver = InstitutionResolver()
    resolver.observe("ABC Asset", "1-1 Marunouchi, Tokyo")
    resolver.observe("ABC Asset", "2 King Street, London")
    resolver.finalize_observations()

    tokyo = resolver.resolve("ABC Asset", address="1-1 Marunouchi, Tokyo")
    london = resolver.resolve("ABC Asset", address="2 King Street, London")
    assert tokyo.legal_id != london.legal_id

    # 住所が 1 つしか観測されない名前は何も変わらない
    resolver2 = InstitutionResolver()
    resolver2.observe("XYZ Asset", "1-1 Marunouchi, Tokyo")
    resolver2.finalize_observations()
    plain = resolver2.resolve("XYZ Asset", address="1-1 Marunouchi, Tokyo")
    assert plain.legal_id == "xyz-asset"


# -- イベント種別 -----------------------------------------------------------

def test_event_types_are_distinguished():
    rows = [
        _row("A", "2026-07-16", 0.0060, 0.0),        # 新規
        _row("B", "2026-07-16", 0.0090, 0.0070),     # 増
        _row("C", "2026-07-16", 0.0070, 0.0090),     # 減
        _row("D", "2026-07-16", 0.0040, 0.0051),     # 義務消失
        _row("E", "2026-07-16", 0.0, 0.0057),        # 解消
    ]
    kinds = {e["raw_holder_name"]: e["event_type"] for e in _events(rows)}
    assert kinds == {
        "A": ev.EVENT_NEW, "B": ev.EVENT_INCREASED, "C": ev.EVENT_DECREASED,
        "D": ev.EVENT_BELOW_THRESHOLD, "E": ev.EVENT_CLOSED,
    }


def test_reentry_is_distinguished_from_new():
    """一度消えてから戻ってきた機関を「新規」に埋めない。"""

    rows = [
        _row("A", "2026-07-16", 0.0060),             # 初出
        _row("A", "2026-07-21", 0.0040, 0.0060),     # 義務消失
        _row("A", "2026-07-29", 0.0075, 0.0),        # 再登場
    ]
    kinds = [e["event_type"] for e in _events(rows)]
    assert kinds == [ev.EVENT_NEW, ev.EVENT_BELOW_THRESHOLD, ev.EVENT_REENTRY]


def test_below_threshold_is_not_zero():
    """義務消失 = 仓位归零 ではない。ここを潰すと売り方を数え損なう。"""

    rows = [_row("A", "2026-07-30", 0.0040, 0.0051)]
    event = _events(rows)[0]
    assert event["visibility_status"] == ev.VISIBLE_BELOW_THRESHOLD
    assert event["short_ratio"] == pytest.approx(0.0040), "最後の公開値を捨てている"

    known = ev.last_known_as_of(_events(rows), published_cutoff="2026-08-03")
    state = next(iter(known.values()))
    assert state["exact_at_position_date"] is False
    assert state["last_reported_ratio"] == pytest.approx(0.0040)
    assert state["visibility_status"] != ev.VISIBLE_CLOSED


def test_hedge_disclosure_is_flagged():
    """顧客取引のヘッジと明記された建玉を、方向性の売りと同じに扱わない。"""

    rows = [_row(
        "A", "2026-07-30", 0.0090, 0.0070,
        notes="顧客取引に係るヘッジポジション及びETFの場合は当該ETFの設定を伴う空売りを含む",
    )]
    assert _events(rows)[0]["is_hedge_disclosed"] == 1
    assert _events([_row("A", "2026-07-30", 0.0090, 0.0070)])[0]["is_hedge_disclosed"] == 0


# -- 点時セマンティクス -----------------------------------------------------

def test_effective_date_follows_publication_not_position_date():
    """7/29 の残高が 7/31 に公開されたなら、使ってよいのは 7/31 以降。"""

    rows = [_row("A", "2026-07-29", 0.0123, disc="2026-07-30")]
    event = _events(rows)[0]
    assert event["position_date"] == "2026-07-29"
    assert event["published_date"] == "2026-07-30"
    # 公表は当日 16:00 締めの受付分 = 引け後。当日の終値では入れないので
    # 効力日は **翌営業日**。
    assert event["effective_trade_date"] == "2026-07-31"
    assert event["effective_trade_date"] > event["published_date"]


def test_effective_date_moves_to_the_next_open_day():
    """公開日が休場なら翌営業日。公開された日に取引できるとは限らない。"""

    rows = [_row("A", "2026-07-29", 0.0123, disc="2026-07-18")]   # 土曜
    assert _events(rows)[0]["effective_trade_date"] == "2026-07-21"


def test_missing_ratio_is_unknown_not_closed():
    """比率が読めない行は unknown。欠損を「解消」と同じ箱に入れない。"""

    rows = [_row("A", "2026-07-30", None)]
    event = _events(rows)[0]
    assert event["visibility_status"] == ev.VISIBLE_UNKNOWN
    assert event["event_type"] == ev.EVENT_UNKNOWN

    known = ev.last_known_as_of([event], published_cutoff="2026-08-03")
    state = next(iter(known.values()))
    assert state["visibility_status"] == ev.VISIBLE_UNKNOWN
    totals = ev.visible_totals(known)
    assert totals["unknown_count"] == 1
    assert totals["closed_count"] == 0, "欠損を解消として数えている"


def test_a_correction_does_not_reach_back_into_history():
    """訂正は **訂正が公開された後** にしか効かない。"""

    rows = [
        _row("A", "2026-07-29", 0.0100, disc="2026-07-31"),
        _row("A", "2026-07-29", 0.0123, disc="2026-08-04"),   # 訂正
    ]
    events = _events(rows)
    kinds = {e["published_date"]: e["correction_status"] for e in events}
    assert kinds["2026-07-31"] == ev.CORRECTION_ORIGINAL
    assert kinds["2026-08-04"] == ev.CORRECTION_REVISED

    before = ev.last_known_as_of(events, published_cutoff="2026-08-03")
    after = ev.last_known_as_of(events, published_cutoff="2026-08-04")
    assert next(iter(before.values()))["last_reported_ratio"] == pytest.approx(0.0100), (
        "訂正前の断面に訂正後の値が漏れている"
    )
    assert next(iter(after.values()))["last_reported_ratio"] == pytest.approx(0.0123)


def test_event_ids_are_stable_so_rebuilds_are_idempotent():
    rows = [_row("A", "2026-07-29", 0.0123, disc="2026-07-31")]
    assert [e["event_id"] for e in _events(rows)] == [e["event_id"] for e in _events(rows)]


# -- 合計の意味 -------------------------------------------------------------

def test_totals_count_only_institutions_still_reporting():
    """閾値割れの最終報告を合計に混ぜると、居ない売り方を数えることになる。"""

    rows = [
        _row("Reporting", "2026-07-31", 0.0123, shares=395_600),
        _row("Below", "2026-07-30", 0.0040, 0.0051, shares=131_200),
        _row("Closed", "2026-07-29", 0.0, 0.0057, shares=0),
    ]
    totals = ev.visible_totals(ev.last_known_as_of(_events(rows), published_cutoff="2026-08-03"))
    assert totals["visible_short_ratio"] == pytest.approx(0.0123)
    assert totals["visible_short_shares"] == pytest.approx(395_600)
    assert totals["visible_institution_count"] == 1
    assert totals["below_threshold_count"] == 1
    assert totals["closed_count"] == 1


def test_share_total_is_withheld_when_any_reporting_holder_lacks_shares():
    rows = [
        _row("A", "2026-07-31", 0.0123, shares=395_600),
        _row("B", "2026-07-31", 0.0080, shares=None),
    ]
    totals = ev.visible_totals(ev.last_known_as_of(_events(rows), published_cutoff="2026-08-03"))
    assert totals["visible_short_shares"] is None
    assert totals["visible_short_ratio"] == pytest.approx(0.0203)


def test_concentration_is_one_when_a_single_institution_is_visible():
    rows = [_row("A", "2026-07-31", 0.0123)]
    totals = ev.visible_totals(ev.last_known_as_of(_events(rows), published_cutoff="2026-08-03"))
    assert totals["concentration"] == pytest.approx(1.0)
    assert totals["largest_institution_ratio"] == pytest.approx(0.0123)


def test_concentration_falls_when_the_position_is_spread_across_institutions():
    rows = [_row(name, "2026-07-31", 0.0100) for name in ("A", "B", "C", "D")]
    totals = ev.visible_totals(ev.last_known_as_of(_events(rows), published_cutoff="2026-08-03"))
    assert totals["concentration"] == pytest.approx(0.25)


# -- 報告義務中のまま古くなったもの -----------------------------------------

def test_a_reporting_state_that_stopped_updating_is_not_summed():
    """報告義務は 0.1% 動くたびに発生する。

    0.5% 以上の建玉が半年間 1 度も 0.1% 動かない、は実務上ほぼ無い。本番
    データでは `reporting` 4,352 件のうち 940 件が 250 営業日超（685 銘柄）で、
    ある銘柄では合計が「公開空売り 39.77%」になっていた。閾値割れを足すのと
    同じ誤り —— いない売り方を数えている。
    """

    rows = [
        _row("Fresh", "2026-07-31", 0.0123, shares=395_600),
        _row("Abandoned", "2026-07-16", 0.0400, shares=1_000_000),
    ]
    events = _events(rows)
    # 「Abandoned」の報告だけ、窓の先頭より前に置く
    for event in events:
        if event["raw_holder_name"] == "Abandoned":
            event["published_date"] = "2019-01-04"

    known = ev.last_known_as_of(
        events, published_cutoff=TRADING_DAYS[-1],
        trading_days=TRADING_DAYS, stale_after=5,
    )
    totals = ev.visible_totals(known)

    abandoned = InstitutionResolver().resolve("Abandoned").legal_id
    assert known[abandoned]["stale_reporting"] is True
    assert totals["visible_short_ratio"] == pytest.approx(0.0123), "古い報告を合計に足している"
    assert totals["visible_institution_count"] == 1
    assert totals["stale_reporting_count"] == 1
    assert totals["below_threshold_count"] == 0, "閾値割れと混同している"


def test_a_fresh_reporting_state_is_still_summed():
    rows = [_row("Fresh", "2026-07-31", 0.0123, shares=395_600)]
    known = ev.last_known_as_of(
        _events(rows), published_cutoff=TRADING_DAYS[-1], trading_days=TRADING_DAYS,
    )
    state = next(iter(known.values()))
    assert state["stale_reporting"] is False
    assert state["exact_at_position_date"] is True
    assert ev.visible_totals(known)["visible_short_ratio"] == pytest.approx(0.0123)


def test_staleness_needs_a_calendar_and_defaults_to_not_stale():
    """営業日列が無ければ古さを判定できない。判定できないものを stale にしない。"""

    rows = [_row("A", "2026-07-31", 0.0123)]
    known = ev.last_known_as_of(_events(rows), published_cutoff="2026-08-03")
    state = next(iter(known.values()))
    assert state["state_age_trading_days"] is None
    assert state["stale_reporting"] is False


# -- 訂正の 2 段階選択 --------------------------------------------------------

def test_late_correction_of_an_old_position_does_not_roll_back_newer_state():
    """7/10 仓位の訂正が 7/20 に公開されても、7/15 仓位の状態は巻き戻らない。"""

    rows = [
        _row("A", "2026-07-16", 0.0100, disc="2026-07-17"),
        _row("A", "2026-07-22", 0.0150, 0.0100, disc="2026-07-23"),
        _row("A", "2026-07-16", 0.0110, disc="2026-07-30"),   # 古い仓位日の訂正
    ]
    events = _events(rows)
    known = ev.last_known_as_of(events, published_cutoff="2026-08-03")
    state = next(iter(known.values()))
    assert state["last_position_date"] == "2026-07-22"
    assert state["last_reported_ratio"] == pytest.approx(0.0150), (
        "後から公開された古い仓位日の訂正が、より新しい仓位状態を上書きしている"
    )


# -- 窓内の変化は逐機関の報告差 ------------------------------------------------

def test_threshold_exit_is_not_counted_as_full_liquidation():
    """0.60%/60万株 → 0.49%/49万株 の実際の減少は 11 万株。可視合計の差で
    数えると 60 万株の減少に化ける（監査 P0-4 の実例そのまま）。"""

    rows = [
        _row("A", "2026-07-16", 0.0060, shares=600_000, disc="2026-07-17"),
        _row("A", "2026-07-23", 0.0049, 0.0060, shares=490_000, disc="2026-07-24"),
    ]
    events = _events(rows)
    changes = ev.window_changes(events, from_cutoff="2026-07-21", to_cutoff="2026-07-31")
    assert changes["shares_change"] == pytest.approx(-110_000), (
        "閾値割れを全量清算として数えている"
    )
    assert changes["ratio_change"] == pytest.approx(-0.0011)


def test_reentry_change_is_measured_from_the_last_visible_value():
    """再参入 70 万株は「+70 万」ではない —— 最後に見えていた 49 万株からの
    +21 万株。"""

    rows = [
        _row("A", "2026-07-16", 0.0049, 0.0060, shares=490_000, disc="2026-07-17"),
        _row("A", "2026-07-29", 0.0070, 0.0049, shares=700_000, disc="2026-07-30"),
    ]
    events = _events(rows)
    changes = ev.window_changes(events, from_cutoff="2026-07-21", to_cutoff="2026-08-03")
    assert changes["shares_change"] == pytest.approx(210_000)


def test_first_disclosure_counts_its_full_size():
    rows = [_row("A", "2026-07-29", 0.0070, shares=700_000, disc="2026-07-30")]
    changes = ev.window_changes(_events(rows), from_cutoff="2026-07-21", to_cutoff="2026-08-03")
    assert changes["shares_change"] == pytest.approx(700_000)
    assert changes["gross_increase_shares"] == pytest.approx(700_000)


def test_explicit_close_counts_down_to_zero():
    rows = [
        _row("A", "2026-07-16", 0.0060, shares=600_000, disc="2026-07-17"),
        _row("A", "2026-07-29", 0.0, 0.0060, shares=0, disc="2026-07-30"),
    ]
    changes = ev.window_changes(_events(rows), from_cutoff="2026-07-21", to_cutoff="2026-08-03")
    assert changes["shares_change"] == pytest.approx(-600_000)


# -- 同一機関の複数ファンド連鎖 ------------------------------------------------

def _fund_row(holder, fund, calc, ratio, prev=None, disc=None, shares=None):
    row = _row(holder, calc, ratio, prev, disc, shares)
    row["investment_fund_name"] = fund
    return row


def test_parallel_fund_chains_are_summed_not_overwritten():
    """同じ機関が 2 つのファンド名義で並行して報告 —— 潰すと片方が消える。"""

    rows = [
        _fund_row("MegaFund", "Fund Alpha", "2026-07-29", 0.0060, shares=600_000, disc="2026-07-30"),
        _fund_row("MegaFund", "Fund Beta", "2026-07-30", 0.0070, shares=700_000, disc="2026-07-31"),
    ]
    known = ev.last_known_as_of(_events(rows), published_cutoff="2026-08-03")
    assert len(known) == 1, "同一機関は 1 行に集約する"
    state = next(iter(known.values()))
    assert state["chain_count"] == 2
    assert state["last_reported_ratio"] == pytest.approx(0.0130), (
        "後から報告したファンドが先のファンドを上書きしている"
    )
    totals = ev.visible_totals(known)
    assert totals["visible_short_ratio"] == pytest.approx(0.0130)
    assert totals["visible_institution_count"] == 1


def test_fund_chains_do_not_cross_when_diffing():
    """Fund Alpha の減少と Fund Beta の増加を混ぜて差を取らない。"""

    rows = [
        _fund_row("MegaFund", "Fund Alpha", "2026-07-16", 0.0060, shares=600_000, disc="2026-07-17"),
        _fund_row("MegaFund", "Fund Beta", "2026-07-16", 0.0070, shares=700_000, disc="2026-07-17"),
        _fund_row("MegaFund", "Fund Alpha", "2026-07-29", 0.0050, 0.0060, shares=500_000, disc="2026-07-30"),
    ]
    changes = ev.window_changes(_events(rows), from_cutoff="2026-07-21", to_cutoff="2026-08-03")
    assert changes["shares_change"] == pytest.approx(-100_000)
    assert changes["gross_reduction_shares"] == pytest.approx(100_000)
    assert changes["gross_increase_shares"] == pytest.approx(0.0)


# -- 2 口径の合計 ---------------------------------------------------------------

def test_in_scope_total_keeps_stale_reporting_institutions():
    """125 日は運用上の目安であって公式ルールの失効期限ではない。公式口径
    （reported_in_scope）は報告停止でも公開範囲内なら合計に残す。"""

    rows = [
        _row("Fresh", "2026-07-31", 0.0123, shares=395_600),
        _row("Abandoned", "2026-07-16", 0.0400, shares=1_000_000),
    ]
    events = _events(rows)
    for event in events:
        if event["raw_holder_name"] == "Abandoned":
            event["published_date"] = "2019-01-04"

    totals = ev.visible_totals(ev.last_known_as_of(
        events, published_cutoff=TRADING_DAYS[-1],
        trading_days=TRADING_DAYS, stale_after=5,
    ))
    assert totals["visible_short_ratio"] == pytest.approx(0.0123)
    assert totals["reported_in_scope_ratio"] == pytest.approx(0.0523), (
        "公式口径の合計から報告停止の機関を落としている"
    )
