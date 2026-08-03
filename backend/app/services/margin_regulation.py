"""信用規制状態（日々公表・増担保・日証金規制）を独立したリスク次元にする。

`/markets/margin-alert` は **規制が掛かっている銘柄だけ** が載る日次リストで、
載っていない = 規制なし、を意味する —— ただし *そのリスト自体が新しいとき
だけ*。同期が止まっている日に「載っていないから無規制」と読むのは、単に
知らないことを安全側の事実にすり替える誤りなので、ここは三値で扱う:

    regulated / not_regulated / unknown

`unknown` を「規制なし」に丸めない。判定不能はスコアを下げるのではなく
**信頼度を下げる**（規制の有無が分からない銘柄を、規制ありと同じだけ叩くのも
それはそれで嘘になる）。

区分の根拠は数値コード（TSEMrgnRegCls）ではなく `PubReason` の名前付き
フラグを使う。本番 72,150 行を集計すると数値コードはフラグの再エンコードに
過ぎず（001↔JSF 系 59,377 件が完全一致、002↔DailyPublication 9,350 件が
完全一致、003/004↔Restricted、101↔UnclearOrSecOnAlert）、意味を持って
いるのはフラグのほう。コード表が改訂されてもフラグ名は自己記述的で壊れない。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

# 重い順。J-Quants 公式の PublishReason 定義に対応する。
FLAG_MONITORING = "Monitoring"                    # 監理銘柄
FLAG_UNCLEAR = "UnclearOrSecOnAlert"              # 不明確情報・監理/整理
FLAG_RESTRICTED = "Restricted"                    # 東証による規制銘柄（増担保等）
FLAG_JSF_RESTRICTED = "RestrictedByJSF"           # 日証金 貸株申込停止
FLAG_DAILY_PUBLICATION = "DailyPublication"       # 東証 日々公表銘柄
FLAG_JSF_PRECAUTION = "PrecautionByJSF"           # 日証金 注意喚起

LEVEL_NONE = "none"
LEVEL_PRECAUTION = "precaution"
LEVEL_DAILY_PUBLICATION = "daily_publication"
LEVEL_RESTRICTED = "restricted"
LEVEL_SEVERE = "severe"
LEVEL_UNKNOWN = "unknown"

# severity: 0=規制なし 〜 4=監理/整理。unknown は -1（順序に混ぜない）。
_FLAG_LEVEL: tuple[tuple[str, str, int], ...] = (
    (FLAG_MONITORING, LEVEL_SEVERE, 4),
    (FLAG_UNCLEAR, LEVEL_SEVERE, 4),
    (FLAG_RESTRICTED, LEVEL_RESTRICTED, 3),
    (FLAG_JSF_RESTRICTED, LEVEL_RESTRICTED, 3),
    (FLAG_DAILY_PUBLICATION, LEVEL_DAILY_PUBLICATION, 2),
    (FLAG_JSF_PRECAUTION, LEVEL_PRECAUTION, 1),
)

KNOWN_FLAGS = tuple(flag for flag, _level, _sev in _FLAG_LEVEL)

# リストの鮮度。日々公表は営業日ごとに出るので、2 営業日以上遅れたら判定不能。
MAX_STALE_TRADING_DAYS = 2

# リスク点（0-100、高いほど危険）。crowding とは別次元として持つ。
_SEVERITY_RISK = {0: 0.0, 1: 35.0, 2: 55.0, 3: 75.0, 4: 95.0}

_TRUE_TEXT = frozenset({"1", "true", "True", "TRUE", "yes", "Y"})


@dataclass(frozen=True)
class RegulationState:
    """ある銘柄のある日の規制状態。`known=False` は「分からない」を意味する。"""

    level: str
    severity: int
    flags: tuple[str, ...]
    regulation_class: str | None
    application_date: str | None
    known: bool
    stale: bool

    @property
    def regulated(self) -> bool | None:
        """三値。判定不能は None を返す（False に丸めない）。"""

        if not self.known:
            return None
        return self.severity > 0

    def risk_score(self) -> float | None:
        """0-100 のリスク点。判定不能なら None（中立値で埋めない）。"""

        if not self.known:
            return None
        return _SEVERITY_RISK.get(self.severity, 0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "severity": self.severity,
            "regulated": self.regulated,
            "flags": list(self.flags),
            "regulation_class": self.regulation_class,
            "application_date": self.application_date,
            "known": self.known,
            "stale": self.stale,
        }


UNKNOWN_STATE = RegulationState(
    level=LEVEL_UNKNOWN, severity=-1, flags=(), regulation_class=None,
    application_date=None, known=False, stale=True,
)
CLEAR_STATE = RegulationState(
    level=LEVEL_NONE, severity=0, flags=(), regulation_class=None,
    application_date=None, known=True, stale=False,
)


def parse_publish_reason(raw: Any) -> tuple[str, ...]:
    """立っているフラグ名だけを返す。

    本番 DB には 2 形式が混在する: 取り込み時期によって dict そのものと、
    `"{'Restricted': '0', ...}"` という Python repr 文字列。片方しか読めない
    実装だと 1 年分の履歴が黙って「フラグなし」に化けるので両方受ける。
    カンマ区切りの正規化済み文字列（新しい取り込み）も受ける。
    """

    if raw is None:
        return ()
    value: Any = raw
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        if text.startswith("{"):
            try:
                value = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                return ()
        else:
            # 既に正規化済み: "DailyPublication,Restricted"
            names = [part.strip() for part in text.split(",") if part.strip()]
            return tuple(sorted(name for name in names if name in KNOWN_FLAGS))
    if isinstance(value, Mapping):
        active = [
            str(key)
            for key, flag in value.items()
            if str(flag).strip() in _TRUE_TEXT and str(key) in KNOWN_FLAGS
        ]
        return tuple(sorted(active))
    return ()


def classify_flags(flags: Iterable[str]) -> tuple[str, int]:
    """立っているフラグ群 → (level, severity)。最も重いものが勝つ。"""

    present = set(flags)
    for flag, level, severity in _FLAG_LEVEL:
        if flag in present:
            return level, severity
    return LEVEL_NONE, 0


def state_from_row(row: Mapping[str, Any] | None) -> RegulationState:
    """margin_alerts の 1 行 → 規制状態。行が無い = リストに載っていない。"""

    if row is None:
        return CLEAR_STATE
    flags = parse_publish_reason(row.get("publish_reason"))
    level, severity = classify_flags(flags)
    regulation_class = row.get("tse_regulation_class")
    if severity == 0 and regulation_class:
        # フラグは読めなかったが規制区分は付いている（将来のフラグ名追加など）。
        # 「規制なし」と言い切らず、最低限の日々公表として扱う。
        level, severity = LEVEL_DAILY_PUBLICATION, 2
    return RegulationState(
        level=level,
        severity=severity,
        flags=flags,
        regulation_class=str(regulation_class) if regulation_class else None,
        application_date=(row.get("application_date") or None),
        known=True,
        stale=False,
    )


def build_regulation_map(
    alert_rows: Iterable[Mapping[str, Any]],
    *,
    as_of: str,
    trading_days_since: int | None,
    universe: Iterable[str] = (),
) -> dict[str, RegulationState]:
    """全銘柄の規制状態。

    `trading_days_since` は「リスト最新日から走査日までの営業日数」。取引所
    カレンダーが引けない場合は None を渡す —— そのときは鮮度を判定できない
    ので全銘柄 unknown に倒す（無規制と読むより安全側）。
    """

    by_code: dict[str, Mapping[str, Any]] = {}
    latest_date: str | None = None
    for row in alert_rows:
        code = row.get("canonical_code")
        if not code:
            continue
        by_code[str(code)] = row
        applied = row.get("application_date") or ""
        if applied and (latest_date is None or applied > latest_date):
            latest_date = applied

    stale = (
        latest_date is None
        or trading_days_since is None
        or trading_days_since > MAX_STALE_TRADING_DAYS
    )
    result: dict[str, RegulationState] = {}
    for code, row in by_code.items():
        state = state_from_row(row)
        if stale:
            # 規制ありの事実は残す（載っていた以上、無かったことにはしない）が、
            # 古い情報だと明示する。解除済みかどうかは分からない。
            state = RegulationState(
                level=state.level, severity=state.severity, flags=state.flags,
                regulation_class=state.regulation_class,
                application_date=state.application_date,
                known=True, stale=True,
            )
        result[code] = state
    if stale:
        # リストが古い間は「載っていない = 無規制」が成立しない。
        for code in universe:
            result.setdefault(str(code), UNKNOWN_STATE)
    else:
        for code in universe:
            result.setdefault(str(code), CLEAR_STATE)
    _ = as_of  # 呼び出し側の意図を明示するためだけに受ける
    return result


__all__ = [
    "CLEAR_STATE",
    "KNOWN_FLAGS",
    "LEVEL_DAILY_PUBLICATION",
    "LEVEL_NONE",
    "LEVEL_PRECAUTION",
    "LEVEL_RESTRICTED",
    "LEVEL_SEVERE",
    "LEVEL_UNKNOWN",
    "MAX_STALE_TRADING_DAYS",
    "RegulationState",
    "UNKNOWN_STATE",
    "build_regulation_map",
    "classify_flags",
    "parse_publish_reason",
    "state_from_row",
]
