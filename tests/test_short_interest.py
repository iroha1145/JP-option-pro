"""空売り残高サマリ: 欠損は「解消」ではなく「不明」。規制不明は信頼度を下げる。"""

from app.services.short_interest import STATE_CLOSED, STATE_UNKNOWN, _state, summarise
from app.services.short_monitor.factors import data_confidence


def test_missing_latest_ratio_is_unknown_not_closed():
    """最新報告の比率が読めない保有者は unknown。0 と混ぜて「解消」に数えない。"""

    assert _state(None) == STATE_UNKNOWN
    assert _state(0.0) == STATE_CLOSED

    rows = [
        # A: 最新報告の比率が欠損（データ穴）→ unknown
        {
            "holder_name": "A", "calculated_date": "2026-07-30",
            "disclosed_date": "2026-07-30", "short_position_ratio": None,
        },
        # B: 明示的なゼロ → closed
        {
            "holder_name": "B", "calculated_date": "2026-07-30",
            "disclosed_date": "2026-07-30", "short_position_ratio": 0.0,
        },
    ]
    summary = summarise(rows, as_of="2026-07-30").as_dict()
    assert summary["unknown_holders"] == 1  # A
    assert summary["closed_holders"] == 1   # B only (was 2 before the fix)


def test_regulation_unknown_lowers_data_confidence():
    base = data_confidence(
        mapping_confidence=1.0, visible_institution_count=2,
        days_since_last_report=1, bars_available=300,
    )
    unknown = data_confidence(
        mapping_confidence=1.0, visible_institution_count=2,
        days_since_last_report=1, bars_available=300, regulation_unknown=True,
    )
    assert unknown["confidence"] < base["confidence"]
    assert "regulation_unknown" in unknown["reasons"]
