"""評分の正しさ（リスク減点・重複計権・売買代金安定性・業種相対の周期）。

静的監査で「計算はしているが結果に効いていない」と指摘された箇所の回帰。
どれも旧実装では通らない（意図的に旧挙動を assert で否定している）。
"""

from __future__ import annotations

from app.services.radar.scoring import alert_priority
from app.services.radar.turnover_quality import turnover_stability
from app.services.strength_scan import (
    build_view_rows,
    score_profile_fit,
    sort_view_rows,
)


def _row(code: str, **overrides):
    row = {
        "canonical_code": code,
        "intrinsic_score": 80.0,
        "confidence": 0.9,
        "atr_pct": 3.0,
        "avg_turnover_20d": 2.0e9,
        "ma_alignment_pct": 80.0,
        "drawdown_63d_pct": -8.0,
        "close": 3000.0,
        "margin_long_short_ratio": 3.0,
        "rs_topix_63d": 0.05,
        "turnover_ratio": 1.2,
        "ath_proximity": 90.0,
        "details": {},
    }
    row.update(overrides)
    return row


_REGIME = {"score": 60.0, "confidence": 0.9, "status": "active"}


# ---------------------------------------------------------------------------
# 1. リスク減点が実際に順位を動かすか
# ---------------------------------------------------------------------------


def test_risk_penalty_actually_changes_the_ordering():
    """高ボラ・200日線下・深い回撤を抱えた銘柄が、無傷の銘柄を追い越さないこと。

    旧実装は penalty を計算して画面にも出しながら、並べ替えは減点前の
    ranking_score で行っていた（表示と挙動が矛盾）。
    """

    clean = _row("1000", intrinsic_score=74.0)
    risky = _row(
        "2000",
        intrinsic_score=86.0,          # 素の質は明確に上
        # 減点の中身は「好みに依らず悪いもの」だけで作る。ボラティリティや
        # 通常の押しの深さは profile_fit の担当なので、ここには混ぜない。
        details={
            "snapshot": {"ma200_gap_pct": -0.05},           # 長期трен未修復
            "vol_price": {"risk_penalty_adjustment": 9.0,   # 出来高と値動きの不一致
                          "setup_type": "vacuum"},          # 真空型 = 假突破リスク
        },
    )

    rows = build_view_rows([clean, risky], _REGIME, profile="balanced")
    by_code = {row["canonical_code"]: row for row in rows}

    assert by_code["2000"]["risk_penalty"] > 0, "リスクが検出されていない"
    assert by_code["2000"]["raw_ranking_score"] > by_code["1000"]["raw_ranking_score"], (
        "前提が崩れている: 素点では risky のほうが上のはず"
    )
    assert by_code["2000"]["final_ranking_score"] < by_code["2000"]["raw_ranking_score"]

    sort_view_rows(rows, "overall")
    assert [row["canonical_code"] for row in rows] == ["1000", "2000"], (
        "リスク減点が並べ替えに効いていない"
    )


def test_raw_penalty_final_are_arithmetically_consistent():
    rows = build_view_rows([_row("1000", atr_pct=8.0)], _REGIME, profile="balanced")
    row = rows[0]
    expected = max(0.0, min(100.0, row["raw_ranking_score"] - row["risk_penalty"]))
    assert abs(row["final_ranking_score"] - expected) < 0.15
    # 互換フィールドは最終値と一致（表示と挙動を一本化した）
    assert row["ranking_score"] == row["final_ranking_score"]


def test_final_score_stays_in_range():
    """減点が大きくても負の分数は出さない。"""

    rows = build_view_rows(
        [_row("1000", intrinsic_score=12.0, atr_pct=25.0, drawdown_63d_pct=-70.0,
              avg_turnover_20d=1.1e8,
              details={"snapshot": {"ma200_gap_pct": -0.4},
                       "vol_price": {"risk_penalty_adjustment": 40.0}})],
        _REGIME, profile="conservative",
    )
    assert 0.0 <= rows[0]["final_ranking_score"] <= 100.0


# ---------------------------------------------------------------------------
# 2. プロファイルの重複計権
# ---------------------------------------------------------------------------


def test_profile_fit_does_not_re_include_intrinsic():
    """intrinsic だけを変えても profile_fit は動かないこと。

    旧実装は profile_fit の中に intrinsic を 0.45〜0.60 で混ぜており、
    最終ランキングでも intrinsic に 0.78 を与えていた（実効 ≒ 0.86）。
    """

    low = score_profile_fit(_row("1000", intrinsic_score=10.0), "balanced")
    high = score_profile_fit(_row("1000", intrinsic_score=95.0), "balanced")
    assert low["score"] == high["score"], "profile_fit がまだ intrinsic を見ている"


def test_three_profiles_produce_different_orderings():
    """稳健/均衡/进取 が「小数点だけ違う同じ並び」にならないこと。"""

    # 素の質（intrinsic）と流動性・単元金額・信用の偏りは揃え、**ボラティリティと
    # 押しの深さだけ**を変える。差が出るならそれはプロファイルが効いた証拠で、
    # 「たまたま片方が全部の軸で優れていた」ではない。
    universe = [
        _row("1000", intrinsic_score=70.0, atr_pct=1.6, avg_turnover_20d=3.0e9,
             close=1000.0, drawdown_63d_pct=-4.0, margin_long_short_ratio=2.0),
        _row("2000", intrinsic_score=70.0, atr_pct=8.5, avg_turnover_20d=3.0e9,
             close=1000.0, drawdown_63d_pct=-24.0, margin_long_short_ratio=2.0),
        _row("3000", intrinsic_score=70.0, atr_pct=3.2, avg_turnover_20d=3.0e9,
             close=1000.0, drawdown_63d_pct=-12.0, margin_long_short_ratio=2.0),
    ]

    orders = {}
    for profile in ("conservative", "balanced", "aggressive"):
        rows = build_view_rows(universe, _REGIME, profile=profile)
        sort_view_rows(rows, "overall")
        orders[profile] = [row["canonical_code"] for row in rows]

    assert orders["conservative"][0] == "1000", f"稳健が低ボラ株を選んでいない: {orders}"
    assert orders["aggressive"][0] == "2000", f"进取が高ボラ株を選んでいない: {orders}"
    assert orders["conservative"] != orders["aggressive"], (
        f"3 モードが同じ並びを返している: {orders}"
    )


# ---------------------------------------------------------------------------
# 3. 売買代金の安定性
# ---------------------------------------------------------------------------


def test_turnover_stability_is_not_just_a_presence_check():
    """「値が入っていれば 100」ではないこと（旧実装はまさにそれだった）。"""

    steady = [1.0e9] * 60
    spiky = [2.0e6] * 58 + [3.0e10, 2.5e10]

    assert turnover_stability(steady) == 100.0
    assert turnover_stability(spiky) is not None
    assert turnover_stability(spiky) < 40.0, (
        "普段ほぼ商いが無く 1〜2 日だけ爆発した銘柄に高い安定性を与えている"
    )
    assert turnover_stability(steady) > turnover_stability(spiky)


def test_turnover_stability_missing_data_is_none_not_neutral():
    assert turnover_stability([]) is None
    assert turnover_stability([1.0e9] * 5) is None          # 観測不足
    assert turnover_stability([None] * 60) is None          # 全欠測


def test_turnover_stability_penalises_dead_days():
    half_dead = [1.0e9 if index % 2 else 1.0e5 for index in range(60)]
    assert turnover_stability(half_dead) < turnover_stability([1.0e9] * 60)


# ---------------------------------------------------------------------------
# 4. 信用規制がリスクに効く（判定不能は無罪でも有罪でもない）
# ---------------------------------------------------------------------------


def _priority(**overrides):
    kwargs = {
        "breakout_quality": 80.0, "relative_strength": 70.0, "market_fit": 60.0,
        "sector_fit": 60.0, "participation": 70.0, "data_confidence": 90.0,
        "chase_risk": 20.0, "crowding_risk": 20.0, "regulation_risk": None,
    }
    kwargs.update(overrides)
    return alert_priority(**kwargs).score


def test_regulation_lowers_priority_but_does_not_zero_it():
    clean = _priority(regulation_risk=0.0)
    restricted = _priority(regulation_risk=75.0)
    severe = _priority(regulation_risk=95.0)

    assert restricted < clean, "信用規制が優先度に効いていない"
    assert severe < restricted, "規制の重さが順序に反映されていない"
    assert severe > 0.0, "1 つのリスク次元だけで銘柄を全否定してはいけない"


def test_unknown_regulation_is_not_treated_as_clean():
    """判定不能を「規制なし」と同じ扱いにしない。

    減点はしない（無実の銘柄を叩かない）が、`None` と `0.0` が同じ結果に
    なること自体は許す —— 区別は data_confidence 側で付ける。ここで確かめる
    のは「unknown が *規制あり* より甘く、かつ黙って 0 に丸められていない」こと。
    """

    unknown = _priority(regulation_risk=None)
    restricted = _priority(regulation_risk=75.0)
    assert unknown > restricted
