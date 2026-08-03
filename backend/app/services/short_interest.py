"""空売り残高の集計と 2 週間の変化一覧。

**残高報告はイベント駆動**（毎日出るものではない）。0.5% を超えたときに報告
義務が生じ、以後 0.1% 以上動くたびに報告し、0.5% を割ったら最終報告を 1 本
出して義務が消える。したがって「N 日前の残高」という断面はどこにも存在せず、
**各保有者のその日以前の最後の報告**から組み立てるしかない。

集計で一番やってはいけないのが、全保有者の最新値を単純合計すること。
3905 で言うと Barclays 0.40%・Jump 0.42%・UBS 0.43%・JPM 0.34%・
Citigroup 0.49% … を足すと 4.64% になるが、これらは全て **0.5% を割った
ときの最終報告**で、その後は報告義務が無い —— 実際の建玉は「その値以下の
どこか」で、とっくにゼロかもしれない。合計に混ぜると、いもしない売り方を
数えることになる。

なので 3 つに分けて数える:

    reporting        報告義務が続いている（最新値 ≥ 0.5%）→ 合計してよい
    below_threshold  0.5% を割った最終報告（実際の値は不明・上限だけ判る）
    closed           明示的にゼロ（解消）

合計として出すのは `reporting` だけ。残り 2 つは件数として見せ、合計には
入れない。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

#: 報告義務が生じる水準（発行済株式数に対する比率）。
REPORTING_THRESHOLD = 0.005

#: 既定の比較窓 = 2 週間。このリポジトリは一貫して営業日で数えるので
#: 10 営業日（= 2 週間分の立会）とし、画面には実際の基準日も併記する
#: （「2 週間」が暦か立会かで受け取り方が変わらないように）。
DEFAULT_WINDOW_TRADING_DAYS = 10

STATE_REPORTING = "reporting"
STATE_BELOW_THRESHOLD = "below_threshold"
STATE_CLOSED = "closed"

# 窓の中で何が起きたか
MOVE_NEW = "new"                    # 新規に報告義務が発生
MOVE_INCREASED = "increased"
MOVE_DECREASED = "decreased"
MOVE_BELOW_THRESHOLD = "below_threshold"   # 0.5% 割れ（義務消失）
MOVE_CLOSED = "closed"                     # 解消


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _state(ratio: float | None) -> str:
    if ratio is None or ratio <= 0.0:
        return STATE_CLOSED
    return STATE_REPORTING if ratio >= REPORTING_THRESHOLD else STATE_BELOW_THRESHOLD


@dataclass
class HolderMove:
    holder_name: str
    previous_ratio: float | None
    current_ratio: float | None
    kind: str

    @property
    def delta(self) -> float | None:
        if self.current_ratio is None or self.previous_ratio is None:
            return None
        return self.current_ratio - self.previous_ratio

    def as_dict(self) -> dict[str, Any]:
        return {
            "holder_name": self.holder_name,
            "previous_ratio": self.previous_ratio,
            "current_ratio": self.current_ratio,
            "delta": self.delta,
            "kind": self.kind,
        }


@dataclass
class ShortInterestSummary:
    as_of: str | None = None
    baseline_date: str | None = None
    window_trading_days: int = DEFAULT_WINDOW_TRADING_DAYS
    reporting_total: float | None = None
    reporting_shares: float | None = None
    reporting_holders: int = 0
    below_threshold_holders: int = 0
    closed_holders: int = 0
    baseline_total: float | None = None
    baseline_holders: int = 0
    change: float | None = None
    movers: list[HolderMove] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "baseline_date": self.baseline_date,
            "window_trading_days": self.window_trading_days,
            # 合計は「報告義務が続いている保有者」だけ。閾値割れの最終報告は
            # 実際の建玉が不明なので足さない。
            "reporting_total": self.reporting_total,
            "reporting_shares": self.reporting_shares,
            "reporting_holders": self.reporting_holders,
            "below_threshold_holders": self.below_threshold_holders,
            "closed_holders": self.closed_holders,
            "baseline_total": self.baseline_total,
            "baseline_holders": self.baseline_holders,
            "change": self.change,
            "movers": [move.as_dict() for move in self.movers],
            "reporting_threshold": REPORTING_THRESHOLD,
        }


def _latest_rows_as_of(
    rows: Sequence[Mapping[str, Any]], as_of: str | None = None
) -> dict[str, Mapping[str, Any]]:
    """{保有者: その日以前の最後の報告そのもの}。

    報告はイベント駆動なので「その日の断面」は存在しない。各保有者について
    `as_of` 以前で最も新しい報告を採る。訂正は同じ計算日に新しい開示日で
    入るので、計算日 → 開示日 の順に見る。
    """

    latest: dict[str, tuple[str, str, Mapping[str, Any]]] = {}
    for row in rows:
        holder = str(row.get("holder_name") or "").strip()
        if not holder:
            continue
        calculated = str(row.get("calculated_date") or "")
        disclosed = str(row.get("disclosed_date") or "")
        if as_of is not None and calculated > as_of:
            continue
        key = (calculated, disclosed)
        current = latest.get(holder)
        if current is None or key > (current[0], current[1]):
            latest[holder] = (calculated, disclosed, row)
    return {holder: row for holder, (_c, _d, row) in latest.items()}


def positions_as_of(
    rows: Sequence[Mapping[str, Any]], as_of: str | None = None
) -> dict[str, float | None]:
    """{保有者: その日以前の最後の報告値（比率）}。"""

    return {
        holder: _finite(row.get("short_position_ratio"))
        for holder, row in _latest_rows_as_of(rows, as_of).items()
    }


def _total(positions: Mapping[str, float | None]) -> tuple[float | None, int]:
    """報告義務中の保有者だけの合計と件数。該当なしなら (0.0, 0)。"""

    active = [
        value for value in positions.values()
        if value is not None and value >= REPORTING_THRESHOLD
    ]
    return (round(sum(active), 6) if active else 0.0), len(active)


def _total_shares(latest: Mapping[str, Mapping[str, Any]]) -> float | None:
    """報告義務中の保有者だけの株数合計。

    比率の合計と **同じ保有者集合** で数える。閾値割れの保有者の株数は
    「その値以下のどこか」でしかないので、比率と同様に足さない。
    株数が 1 件でも欠けていれば合計は出さない（欠損を 0 として足すと
    合計が黙って小さく出る）。
    """

    shares: list[float] = []
    for row in latest.values():
        ratio = _finite(row.get("short_position_ratio"))
        if ratio is None or ratio < REPORTING_THRESHOLD:
            continue
        value = _finite(row.get("short_position_shares"))
        if value is None:
            return None
        shares.append(value)
    return sum(shares) if shares else 0.0


def _classify_move(previous: float | None, current: float | None) -> str | None:
    before, after = _state(previous), _state(current)
    if before == after and (previous or 0.0) == (current or 0.0):
        return None
    if before != STATE_REPORTING and after == STATE_REPORTING:
        return MOVE_NEW
    if after == STATE_CLOSED and before != STATE_CLOSED:
        return MOVE_CLOSED
    if before == STATE_REPORTING and after == STATE_BELOW_THRESHOLD:
        return MOVE_BELOW_THRESHOLD
    if current is not None and previous is not None:
        if current > previous:
            return MOVE_INCREASED
        if current < previous:
            return MOVE_DECREASED
    return None


def summarise(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: str | None = None,
    baseline_date: str | None = None,
    window_trading_days: int = DEFAULT_WINDOW_TRADING_DAYS,
) -> ShortInterestSummary:
    """現在の残高と、`baseline_date` 時点との比較。

    `baseline_date` は呼び出し側が取引カレンダーから求めて渡す（ここでは
    カレンダーを持たない）。渡されなければ比較は行わず、現状だけを返す。
    """

    summary = ShortInterestSummary(window_trading_days=window_trading_days)
    if not rows:
        return summary

    dates = [str(row.get("calculated_date") or "") for row in rows if row.get("calculated_date")]
    summary.as_of = as_of or (max(dates) if dates else None)

    latest = _latest_rows_as_of(rows, summary.as_of)
    current = {
        holder: _finite(row.get("short_position_ratio")) for holder, row in latest.items()
    }
    summary.reporting_total, summary.reporting_holders = _total(current)
    summary.reporting_shares = _total_shares(latest)
    summary.below_threshold_holders = sum(
        1 for value in current.values() if _state(value) == STATE_BELOW_THRESHOLD
    )
    summary.closed_holders = sum(
        1 for value in current.values() if _state(value) == STATE_CLOSED
    )

    if baseline_date is None:
        return summary
    summary.baseline_date = baseline_date
    previous = positions_as_of(rows, baseline_date)
    summary.baseline_total, summary.baseline_holders = _total(previous)
    if summary.reporting_total is not None and summary.baseline_total is not None:
        summary.change = round(summary.reporting_total - summary.baseline_total, 6)

    moves: list[HolderMove] = []
    for holder in sorted(set(current) | set(previous)):
        before = previous.get(holder)
        after = current.get(holder)
        kind = _classify_move(before, after)
        if kind is not None:
            moves.append(HolderMove(holder, before, after, kind))
    # 動きの大きい順（方向は問わない）。0.5% 割れ・解消は delta が出せる
    # ものだけ数値で、出せないものは末尾に回す。
    moves.sort(key=lambda move: -abs(move.delta) if move.delta is not None else 0.0)
    summary.movers = moves
    return summary


def changes_within(
    rows: Sequence[Mapping[str, Any]], *, since: str
) -> list[dict[str, Any]]:
    """窓の中の **報告 1 本ごと** の変化（集約しない）。

    同じ保有者が 2 週間に 3 回報告していれば 3 行出す。保有者単位で
    差し引きすると「7/22 に減らして 7/30 にまた減らした」が 1 行に潰れ、
    いつ何が起きたかが読めなくなる。karauri 等の見せ方とも揃う。

    各行の変化はその報告自身が持つ `previous_ratio` から取る（前の行を
    探しに行かない —— 窓の外に前回報告があっても正しく出る）。
    """

    out: list[dict[str, Any]] = []
    for row in rows:
        calculated = str(row.get("calculated_date") or "")
        if not calculated or calculated < since:
            continue
        ratio = _finite(row.get("short_position_ratio"))
        previous = _finite(row.get("previous_ratio"))
        out.append(
            {
                "holder_name": row.get("holder_name"),
                "calculated_date": calculated,
                "disclosed_date": row.get("disclosed_date"),
                "ratio": ratio,
                "shares": _finite(row.get("short_position_shares")),
                "units": _finite(row.get("short_position_units")),
                "previous_ratio": previous,
                "delta": (ratio - previous) if (ratio is not None and previous is not None) else None,
                "kind": _classify_move(previous, ratio) or MOVE_INCREASED,
                "state": _state(ratio),
            }
        )
    out.sort(
        key=lambda item: (item["calculated_date"], item.get("disclosed_date") or ""),
        reverse=True,
    )
    return out


__all__ = [
    "DEFAULT_WINDOW_TRADING_DAYS",
    "changes_within",
    "HolderMove",
    "MOVE_BELOW_THRESHOLD",
    "MOVE_CLOSED",
    "MOVE_DECREASED",
    "MOVE_INCREASED",
    "MOVE_NEW",
    "REPORTING_THRESHOLD",
    "STATE_BELOW_THRESHOLD",
    "STATE_CLOSED",
    "STATE_REPORTING",
    "ShortInterestSummary",
    "positions_as_of",
    "summarise",
]
