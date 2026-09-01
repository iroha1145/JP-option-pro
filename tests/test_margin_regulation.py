"""信用規制（日々公表・増担保・日証金規制）の解釈。

`regulated = False` の決め打ちを外した際の回帰。要点は 3 つ:
  1. 本番に実在する 2 つの格納形式を両方読めること
  2. 「載っていない」と「分からない」を混同しないこと
  3. 重さの順序が保たれること
"""

from __future__ import annotations

from app.services import margin_regulation as mreg


# 本番 DB（72,150 行）に実在する形式。取り込み時期で 2 通りある。
_LEGACY_REPR = (
    "{'Restricted': '0', 'DailyPublication': '0', 'Monitoring': '0', "
    "'RestrictedByJSF': '0', 'PrecautionByJSF': '1', 'UnclearOrSecOnAlert': '0'}"
)
_LEGACY_RESTRICTED = (
    "{'Restricted': '1', 'DailyPublication': '0', 'Monitoring': '0', "
    "'RestrictedByJSF': '0', 'PrecautionByJSF': '0', 'UnclearOrSecOnAlert': '0'}"
)


def test_parses_the_python_repr_shape_stored_in_production():
    """全 72,150 行がこの形式。読めないと 1 年分が黙って「規制なし」に化ける。"""

    assert mreg.parse_publish_reason(_LEGACY_REPR) == ("PrecautionByJSF",)
    assert mreg.parse_publish_reason(_LEGACY_RESTRICTED) == ("Restricted",)


def test_parses_the_dict_shape():
    raw = {"Restricted": "0", "DailyPublication": "1", "PrecautionByJSF": "1"}
    assert mreg.parse_publish_reason(raw) == ("DailyPublication", "PrecautionByJSF")


def test_parses_the_normalised_comma_shape():
    assert mreg.parse_publish_reason("DailyPublication,Restricted") == (
        "DailyPublication", "Restricted",
    )


def test_unparseable_input_is_empty_not_a_crash():
    for raw in (None, "", "   ", "{not a dict", 42, []):
        assert mreg.parse_publish_reason(raw) == ()


def test_severity_ordering_matches_regulation_weight():
    order = [
        mreg.classify_flags([])[1],
        mreg.classify_flags(["PrecautionByJSF"])[1],
        mreg.classify_flags(["DailyPublication"])[1],
        mreg.classify_flags(["Restricted"])[1],
        mreg.classify_flags(["Monitoring"])[1],
    ]
    assert order == sorted(order), f"重さの順序が壊れている: {order}"


def test_heaviest_flag_wins_when_several_are_set():
    level, severity = mreg.classify_flags(["PrecautionByJSF", "Restricted"])
    assert level == mreg.LEVEL_RESTRICTED
    assert severity == 3


def test_absent_from_a_fresh_list_means_genuinely_unregulated():
    rows = [{"canonical_code": "7203", "application_date": "2026-07-30",
             "publish_reason": _LEGACY_REPR, "tse_regulation_class": "001"}]
    result = mreg.build_regulation_map(
        rows, as_of="2026-07-31", trading_days_since=1, universe=["7203", "9984"]
    )
    assert result["9984"].regulated is False       # 載っていない = 規制なし
    assert result["9984"].known is True
    assert result["7203"].regulated is True


def test_a_stale_list_makes_absence_unknown_not_clean():
    """同期が止まっている日に「載っていない = 無規制」と読まないこと。

    知らないことを安全側の事実にすり替えるのが一番危ない。
    """

    rows = [{"canonical_code": "7203", "application_date": "2026-06-01",
             "publish_reason": _LEGACY_RESTRICTED, "tse_regulation_class": "003"}]
    result = mreg.build_regulation_map(
        rows, as_of="2026-07-31", trading_days_since=40, universe=["7203", "9984"]
    )
    assert result["9984"].known is False
    assert result["9984"].regulated is None       # False ではない
    assert result["9984"].risk_score() is None    # 中立値で埋めない
    # 規制ありだった事実は消さないが、古いことは申告する
    assert result["7203"].regulated is True
    assert result["7203"].stale is True


def test_missing_calendar_falls_back_to_unknown_not_clean():
    rows = [{"canonical_code": "7203", "application_date": "2026-07-30",
             "publish_reason": _LEGACY_REPR, "tse_regulation_class": "001"}]
    result = mreg.build_regulation_map(
        rows, as_of="2026-07-31", trading_days_since=None, universe=["9984"]
    )
    assert result["9984"].known is False


def test_empty_dataset_is_unknown_for_everyone():
    result = mreg.build_regulation_map(
        [], as_of="2026-07-31", trading_days_since=1, universe=["7203", "9984"]
    )
    assert all(state.known is False for state in result.values())


def test_unreadable_flags_with_a_regulation_class_are_not_called_clean():
    """フラグ名が将来増えて読めなくても、規制区分が付いていれば無罪にしない。"""

    state = mreg.state_from_row(
        {"canonical_code": "7203", "application_date": "2026-07-30",
         "publish_reason": "{'SomeNewFlagWeDoNotKnow': '1'}",
         "tse_regulation_class": "002"}
    )
    assert state.regulated is True
    assert state.severity >= 2


def test_risk_score_is_monotonic_in_severity():
    scores = []
    for flags in ([], ["PrecautionByJSF"], ["DailyPublication"], ["Restricted"], ["Monitoring"]):
        row = {"canonical_code": "1", "application_date": "2026-07-30",
               "publish_reason": ",".join(flags) or None, "tse_regulation_class": None}
        scores.append(mreg.state_from_row(row).risk_score())
    assert scores == sorted(scores)
    assert scores[0] == 0.0 and scores[-1] > 90.0
