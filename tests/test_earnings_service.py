"""決算: 開示済み実績と、その比較の意味論。"""

import pytest

# -- 開示済みの実績と、その比較 ------------------------------------------------

def _summary(code, period, disclosed, *, fye, op=None, np_=None, f_op=None, sales=None):
    return {
        "canonical_code": code, "disclosed_date": disclosed, "disclosure_number": disclosed,
        "period_type": period, "fiscal_year_end": fye, "type_of_document": "決算短信",
        "sales": sales, "operating_profit": op, "net_profit": np_,
        "forecast_operating_profit": f_op, "forecast_net_profit": None,
        "next_forecast_operating_profit": None, "next_forecast_net_profit": None,
        "disclosed_time": None,
    }


def test_quarterly_actual_is_progress_not_a_miss():
    """1Q の累計 30 億 と 通期予想 120 億 は「未達」ではなく **進捗 25%**。

    通期予想を分母にしたまま達成率と呼ぶと、1Q は全社が未達に見える。
    """

    from app.services.earnings_service import _released_pack

    row = _summary("10000", "1Q", "2026-08-04", fye="2027-03-31", op=3_000_000_000, f_op=12_000_000_000)
    pack = _released_pack(row, [row])
    assert pack["basis"] == "progress"
    assert pack["progress"] == pytest.approx(0.25)
    assert pack["achievement"] is None, "四半期に達成率を出している"


def test_full_year_achievement_uses_the_forecast_from_before_the_release():
    """通期の達成率は「発表前に市場が見ていた予想」と比べる。"""

    from app.services.earnings_service import _released_pack

    third_quarter = _summary(
        "10000", "3Q", "2026-02-05", fye="2026-03-31", op=9_000_000_000, f_op=12_000_000_000,
    )
    full_year = _summary(
        "10000", "FY", "2026-05-12", fye="2026-03-31", op=12_600_000_000, f_op=15_000_000_000,
    )
    pack = _released_pack(full_year, [full_year, third_quarter])
    assert pack["basis"] == "full_year"
    assert pack["compared_forecast"] == 12_000_000_000, "同じ行の予想欄を分母にしている"
    assert pack["achievement"] == pytest.approx(1.05)
    assert pack["progress"] is None


def test_year_on_year_compares_the_same_quarter():
    from app.services.earnings_service import _released_pack

    now = _summary("10000", "1Q", "2026-08-04", fye="2027-03-31", op=3_300_000_000, f_op=12_000_000_000)
    last_year = _summary("10000", "1Q", "2025-08-05", fye="2026-03-31", op=3_000_000_000, f_op=11_000_000_000)
    between = _summary("10000", "3Q", "2026-02-05", fye="2026-03-31", op=9_000_000_000, f_op=11_000_000_000)
    pack = _released_pack(now, [now, between, last_year])
    assert pack["yoy_value"] == 3_000_000_000, "同じ四半期どうしで比べていない"
    assert pack["yoy_change"] == pytest.approx(0.10)


def test_no_actual_value_yields_no_pack():
    """予想修正だけの開示に実績は無い。数字を作らない。"""

    from app.services.earnings_service import _released_pack

    row = _summary("10000", "1Q", "2026-08-04", fye="2027-03-31", f_op=12_000_000_000)
    assert _released_pack(row, [row]) is None


def test_ratios_are_withheld_when_the_base_is_a_loss():
    """赤字予想に対する達成率、赤字からの前年同期比は符号が逆に読める。出さない。"""

    from app.services.earnings_service import _released_pack

    prior = _summary("10000", "3Q", "2026-02-05", fye="2026-03-31", op=-1_000_000_000, f_op=-2_000_000_000)
    row = _summary("10000", "FY", "2026-05-12", fye="2026-03-31", op=500_000_000, f_op=1_000_000_000)
    pack = _released_pack(row, [row, prior])
    assert pack["achievement"] is None
    assert pack["yoy_change"] is None


def test_falls_back_to_net_profit_when_operating_profit_is_absent():
    """銀行・保険は営業利益を出さない。純利益で通す（ラベルも変える）。"""

    from app.services.earnings_service import _released_pack

    row = _summary("10000", "1Q", "2026-08-04", fye="2027-03-31", np_=2_000_000_000)
    row["forecast_net_profit"] = 8_000_000_000
    pack = _released_pack(row, [row])
    assert pack["metric"] == "net_profit"
    assert pack["progress"] == pytest.approx(0.25)
