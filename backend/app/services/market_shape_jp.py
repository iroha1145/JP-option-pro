"""市場状態を 6 区分に落とし、突破の **確認要求を変える門**として使う。

参考実装（米国版 `strength/market_shape.py`）から移したのは 2 つだけ:

  1. 6 状態の枠組み（市場中性の概念）
  2. **迟滞**（進入確認日数・退出確認日数・最短滞在日数）

移していないのは各状態の適合スコア（88/62/72/36…）と VIX・SPY 依存の判定。
あれは米国市場で調整された数字で、日本株での根拠が無い（doc §四）。

なぜ迟滞が要るか: 日股版はこれまで毎日ゼロから分数を作り直していたため、
分数が閾値付近で揺れる局面で状態が日替わりする。状態が確認要求を左右する
以上、状態が揺れると **判定基準そのものが日替わりになる**。1 日の値動きで
「昨日は 2 日保ち required、今日は 1 日で OK」が入れ替わるのは、市場が
変わったのではなくノイズを制度化しているだけ。

**この門の数値は未検証**（`validated=False`）。走步検証で単調性が確認される
までは「日本株の最適パラメータ」と称してはいけない（doc §十五）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

MARKET_SHAPE_VERSION = "jp-market-shape-v1"

STATE_BULL_TREND = "BULL_TREND"
STATE_BULL_PULLBACK = "BULL_PULLBACK"
STATE_RANGE_ACCUMULATION = "RANGE_ACCUMULATION"
STATE_RANGE_DISTRIBUTION = "RANGE_DISTRIBUTION"
STATE_BEAR_TREND = "BEAR_TREND"
STATE_CAPITULATION_RECOVERY = "CAPITULATION_RECOVERY"

ALL_STATES = (
    STATE_BULL_TREND, STATE_BULL_PULLBACK, STATE_RANGE_ACCUMULATION,
    STATE_RANGE_DISTRIBUTION, STATE_BEAR_TREND, STATE_CAPITULATION_RECOVERY,
)

STATE_LABELS = {
    STATE_BULL_TREND: "上昇トレンド",
    STATE_BULL_PULLBACK: "上昇中の押し目",
    STATE_RANGE_ACCUMULATION: "レンジ・蓄積",
    STATE_RANGE_DISTRIBUTION: "レンジ・分配",
    STATE_BEAR_TREND: "下降トレンド",
    STATE_CAPITULATION_RECOVERY: "セリクラ後の戻り",
}


@dataclass(frozen=True)
class Hysteresis:
    """状態の切り替えに要する日数。市場中性の機構なのでそのまま移植した。"""

    enter_confirm_days: int = 2   # 新しい状態が何日続いたら採用するか
    exit_confirm_days: int = 2    # 今の状態を何日外れたら離脱を認めるか
    min_dwell_days: int = 3       # 採用した状態に最低何日留まるか


@dataclass(frozen=True)
class Gate:
    """その状態での突破の扱い方。**分数は変えない。確認要求を変える。**

    doc §七 の意図: 市場状態を「最終スコアに乗る小さな重み」ではなく
    「確認の厳しさを決める門」にする。日本株は状態転換が頻繁なので、
    弱い相場で初日の突破をそのまま採るのと、保ち日数を要求するのとで
    結果が大きく変わる。
    """

    #: 確認に要する保ち日数の増減（正 = より厳しく）
    confirmation_days_delta: int = 0
    #: 出来高確認の倍率要求の増減（正 = より厳しく）
    turnover_ratio_delta: float = 0.0
    #: 初日突破をそのまま採ってよいか
    allow_single_day_confirmation: bool = True
    #: 回踩して保った形（RETEST_HELD）を優遇するか
    prefer_retest: bool = False
    #: 純粋なモメンタムの重みを落とすか
    damp_momentum: bool = False
    #: 新規採用の姿勢
    eligibility: str = "normal"   # normal | selective | defensive

    def as_dict(self) -> dict[str, Any]:
        return {
            "confirmation_days_delta": self.confirmation_days_delta,
            "turnover_ratio_delta": self.turnover_ratio_delta,
            "allow_single_day_confirmation": self.allow_single_day_confirmation,
            "prefer_retest": self.prefer_retest,
            "damp_momentum": self.damp_momentum,
            "eligibility": self.eligibility,
        }


#: 各状態の門。**未検証**（走步検証が単調性を示すまで暫定）。
STATE_GATES: dict[str, Gate] = {
    STATE_BULL_TREND: Gate(
        confirmation_days_delta=0, allow_single_day_confirmation=True,
        eligibility="normal",
    ),
    STATE_BULL_PULLBACK: Gate(
        confirmation_days_delta=0, allow_single_day_confirmation=True,
        prefer_retest=True, eligibility="normal",
    ),
    STATE_RANGE_ACCUMULATION: Gate(
        confirmation_days_delta=1, turnover_ratio_delta=0.3,
        allow_single_day_confirmation=False, prefer_retest=True,
        eligibility="normal",
    ),
    STATE_RANGE_DISTRIBUTION: Gate(
        # 転換局面。初日の突破を信用せず、保ちと出来高を要求する（doc §七）。
        confirmation_days_delta=1, turnover_ratio_delta=0.5,
        allow_single_day_confirmation=False, prefer_retest=True,
        eligibility="selective",
    ),
    STATE_BEAR_TREND: Gate(
        # 下降局面では純モメンタムの重みを落とし、相対強度と流動性を要求する。
        confirmation_days_delta=2, turnover_ratio_delta=0.7,
        allow_single_day_confirmation=False, prefer_retest=True,
        damp_momentum=True, eligibility="defensive",
    ),
    STATE_CAPITULATION_RECOVERY: Gate(
        confirmation_days_delta=1, turnover_ratio_delta=0.2,
        allow_single_day_confirmation=False, prefer_retest=True,
        damp_momentum=True, eligibility="selective",
    ),
}

#: 門の数値に歴史的裏付けがあるか。走步検証が通るまで False のまま。
GATES_VALIDATED = False


def _score(regime: Mapping[str, Any], key: str) -> float | None:
    dims = regime.get("dimensions") if isinstance(regime.get("dimensions"), Mapping) else regime
    value = dims.get(key) if isinstance(dims, Mapping) else None
    if value is None:
        value = regime.get(key)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def classify_state(regime: Mapping[str, Any]) -> tuple[str | None, list[str]]:
    """その日の生の状態。判定に足る材料が無ければ (None, 欠損項目)。

    米国版と違い VIX も SPY も無いので、TOPIX のトレンド・モメンタム・
    市場全体の広がり（200日線上の銘柄比率）・グロース対プライムの価差で
    判定する。**欠損を中立値で埋めない** —— 分からない日は分からないと返す。
    """

    trend = _score(regime, "index_trend")
    momentum = _score(regime, "momentum")
    breadth = _score(regime, "breadth")
    risk_on = _score(regime, "risk_on_spread")
    overall = _score(regime, "score")

    missing = [
        name for name, value in (
            ("index_trend", trend), ("momentum", momentum),
            ("breadth", breadth), ("score", overall),
        ) if value is None
    ]
    if missing:
        return None, missing

    # セリクラ後の戻り: 広がりはまだ悪いのに、モメンタムだけ先に戻っている。
    # （米国版は VIX を使うが日本株に安価な等価物が無いので、広がりの弱さで代替）
    if breadth <= 35.0 and momentum >= 55.0 and trend < 55.0:
        return STATE_CAPITULATION_RECOVERY, []

    if trend <= 40.0 and momentum <= 45.0 and overall < 45.0:
        return STATE_BEAR_TREND, []

    if trend >= 70.0 and momentum >= 50.0 and overall >= 60.0 and breadth >= 50.0:
        return STATE_BULL_TREND, []

    # 地合いは崩れていないが勢いだけ落ちている = 押し目
    if trend >= 55.0 and momentum < 50.0:
        return STATE_BULL_PULLBACK, []

    if (
        overall >= 50.0
        and breadth >= 48.0
        and momentum >= 48.0
        and (risk_on is None or risk_on >= 50.0)
    ):
        return STATE_RANGE_ACCUMULATION, []

    return STATE_RANGE_DISTRIBUTION, []


@dataclass
class ShapeState:
    state: str | None
    label: str | None
    raw_state: str | None
    days_in_state: int
    pending_state: str | None
    pending_days: int
    entered_on: str | None
    missing: list[str]

    def gate(self) -> Gate:
        return STATE_GATES.get(self.state or "", Gate())

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": MARKET_SHAPE_VERSION,
            "state": self.state,
            "state_label": self.label,
            "raw_state": self.raw_state,
            "days_in_state": self.days_in_state,
            "pending_state": self.pending_state,
            "pending_days": self.pending_days,
            "entered_on": self.entered_on,
            "missing": list(self.missing),
            "gate": self.gate().as_dict(),
            "gates_validated": GATES_VALIDATED,
        }


def replay_shape(
    daily_regimes: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    hysteresis: Hysteresis | None = None,
) -> ShapeState:
    """[(日付, regime)] を時系列に流して、確定状態を求める。

    生の判定がぶれても、確認日数と最短滞在日数を満たすまで確定状態は動かない。
    材料不足の日は **状態を進めも退けもしない**（前の状態を保ったまま、
    その日を数えない）。欠損を「変化なし」とも「変化」とも読まない。
    """

    cfg = hysteresis or Hysteresis()
    stable: str | None = None
    entered_on: str | None = None
    days_in_state = 0
    pending: str | None = None
    pending_days = 0
    phase: str | None = None       # None | "exit" | "enter"
    exit_days = 0
    last_raw: str | None = None
    last_missing: list[str] = []

    for observed_on, regime in daily_regimes:
        raw, missing = classify_state(regime)
        last_missing = missing
        if raw is None:
            continue                # 材料不足の日は何も進めない
        last_raw = raw

        if stable is None:          # 初日: そのまま採用（比較対象が無い）
            stable, entered_on, days_in_state = raw, observed_on, 1
            continue

        days_in_state += 1
        if raw == stable:
            pending, pending_days, phase, exit_days = None, 0, None, 0
            continue

        # 今の状態から外れた日。まず「離脱が本物か」を確かめる。
        if phase is None:
            phase, pending, exit_days = "exit", raw, 1
        elif phase == "exit":
            pending, exit_days = raw, exit_days + 1

        if phase == "exit":
            pending_days = exit_days
            if exit_days >= cfg.exit_confirm_days:
                phase, pending_days = "enter", 0
            continue

        # 離脱は確定。次は「新しい状態が定まっているか」。
        if pending != raw:
            pending, pending_days = raw, 1
        else:
            pending_days += 1
        if pending_days >= cfg.enter_confirm_days and days_in_state >= cfg.min_dwell_days:
            stable, entered_on, days_in_state = raw, observed_on, 1
            pending, pending_days, phase, exit_days = None, 0, None, 0

    return ShapeState(
        state=stable,
        label=STATE_LABELS.get(stable or ""),
        raw_state=last_raw,
        days_in_state=days_in_state,
        pending_state=pending,
        pending_days=pending_days,
        entered_on=entered_on,
        missing=last_missing,
    )


def apply_gate(
    *,
    gate: Gate,
    confirm_hold_days: int,
    strong_turnover_ratio: float,
) -> tuple[int, float]:
    """基準の確認要求に門を適用した結果を返す。

    **スコアは触らない。** 変えるのは「何をもって確認とみなすか」だけ。
    """

    days = max(1, confirm_hold_days + gate.confirmation_days_delta)
    if not gate.allow_single_day_confirmation:
        days = max(2, days)
    ratio = max(1.0, strong_turnover_ratio + gate.turnover_ratio_delta)
    return days, ratio


__all__ = [
    "ALL_STATES",
    "GATES_VALIDATED",
    "Gate",
    "Hysteresis",
    "MARKET_SHAPE_VERSION",
    "STATE_BEAR_TREND",
    "STATE_BULL_PULLBACK",
    "STATE_BULL_TREND",
    "STATE_CAPITULATION_RECOVERY",
    "STATE_GATES",
    "STATE_LABELS",
    "STATE_RANGE_ACCUMULATION",
    "STATE_RANGE_DISTRIBUTION",
    "ShapeState",
    "apply_gate",
    "classify_state",
    "replay_shape",
]
