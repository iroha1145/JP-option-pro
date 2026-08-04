"""シグナル発生後に **実際に何が起きたか** を測る。

評価の窓は全て **営業日**。暦日で数えると、金曜のシグナルの「3日後」が
祝日を挟んで実質 1 営業日だったり、GW を跨いで 2 営業日だったりして、
同じ「3日リターン」が別物になる。

先読みの禁止はこの層でも守る: シグナル日 D の結果は D より **後**のバーだけ
から作る。D 当日の終値は「そのシグナルを見た時点で既に確定していた値」なので
基準価格に使ってよいが、翌日の始値で入る想定の指標は別に持つ。

相対リターンは 2 系統（TOPIX と業種中位）。日本株は市場全体の影響が大きく、
絶対リターンだけだと「全部上がった月」に高得点が並ぶ。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from app.services.radar.adjustment import cumulative_factors

# 評価する保有期間（営業日）
HORIZONS = (1, 3, 5, 10, 20)

# 1R の定義: シグナル日の ATR14 の何倍を 1 単位リスクとみなすか。
# ピボット・無効化価格が取れる場合はそちらを優先する（実際の損切り位置）。
R_MULTIPLE_ATR = 1.5


@dataclass(frozen=True)
class Bar:
    trade_date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None


@dataclass
class Outcome:
    """1 シグナル分の結果。値が取れない項目は None（0 で埋めない）。"""

    canonical_code: str
    signal_date: str
    entry_basis: str = "signal_close"
    entry_price: float | None = None
    entry_date: str | None = None
    entry_reference_close: float | None = None
    next_open: float | None = None
    next_close: float | None = None
    returns: dict[int, float | None] = field(default_factory=dict)
    excess_topix: dict[int, float | None] = field(default_factory=dict)
    excess_sector: dict[int, float | None] = field(default_factory=dict)
    mfe_pct: float | None = None
    mae_pct: float | None = None
    max_drawdown_pct: float | None = None
    hit_r_multiple: str | None = None      # "target" | "stop" | None（どちらも未達）
    forward_bars: int = 0
    truncated: bool = False                # 窓の途中でデータが尽きた

    def as_dict(self) -> dict[str, Any]:
        return {
            "canonical_code": self.canonical_code,
            "signal_date": self.signal_date,
            "entry_basis": self.entry_basis,
            "entry_price": self.entry_price,
            "entry_date": self.entry_date,
            "entry_reference_close": self.entry_reference_close,
            "next_open": self.next_open,
            "next_close": self.next_close,
            **{f"return_{h}d": self.returns.get(h) for h in HORIZONS},
            **{f"excess_topix_{h}d": self.excess_topix.get(h) for h in HORIZONS},
            **{f"excess_sector_{h}d": self.excess_sector.get(h) for h in HORIZONS},
            "mfe_pct": self.mfe_pct,
            "mae_pct": self.mae_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "hit_r_multiple": self.hit_r_multiple,
            "forward_bars": self.forward_bars,
            "truncated": self.truncated,
        }


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def forward_bars(bars: Sequence[Mapping[str, Any]], signal_date: str, horizon: int) -> list[Bar]:
    """シグナル日 **より後** の営業日を最大 horizon 本。

    `bars` は日付昇順。シグナル日そのものは含めない —— 含めるとその日の
    値動きが「シグナル後の成績」に混ざる（先読み）。
    """

    # 分割・併合を除いてから測る。生値のままだと 1:2 分割が −50% の
    # 最大不利変動（MAE）として、10:1 併合が +900% の含み益として記録され、
    # その銘柄の成績は全て無意味になる（本番 10 年で 1,959 銘柄が該当）。
    factors = cumulative_factors(bars)

    def _price(row: Mapping[str, Any], adj_key: str, raw_key: str, factor: float):
        stored = _finite(row.get(adj_key))
        if stored is not None and stored > 0:
            return stored
        raw = _finite(row.get(raw_key))
        return (raw * factor) if raw is not None else None

    out: list[Bar] = []
    for row, factor in zip(bars, factors):
        date = str(row.get("trade_date") or "")
        if date <= signal_date:
            continue
        out.append(
            Bar(
                trade_date=date,
                open=_price(row, "adj_open", "open", factor),
                high=_price(row, "adj_high", "high", factor),
                low=_price(row, "adj_low", "low", factor),
                close=_price(row, "adj_close", "close", factor),
            )
        )
        if len(out) >= horizon:
            break
    return out


def _series_return(bars: Sequence[Bar], base: float, horizon: int) -> float | None:
    if base <= 0 or len(bars) < horizon:
        return None
    close = bars[horizon - 1].close
    return (close / base - 1.0) if close else None


def compute_outcome(
    *,
    canonical_code: str,
    signal_date: str,
    bars: Sequence[Mapping[str, Any]],
    signal_close: float | None = None,
    atr14: float | None = None,
    stop_price: float | None = None,
    topix_bars: Sequence[Mapping[str, Any]] | None = None,
    sector_bars: Sequence[Mapping[str, Any]] | None = None,
    entry_basis: str = "signal_close",
) -> Outcome:
    """1 シグナルの結果一式。

    `entry_basis`:
        * ``signal_close`` — シグナル日の終値を基準にする（従来）。
          **公開が引け後の情報には使ってはいけない** —— その終値では入れない。
        * ``next_open`` — 翌営業日の始値。実際に注文が通る最初の値段。
        * ``next_close`` — 翌営業日の終値。
    ベンチマーク超過（topix/sector）は signal_close 基準のときだけこの関数が
    計算する。next 基準では呼び出し側が日付整合の取れる形で別に計算すること。
    """

    horizon_max = max(HORIZONS)
    need = horizon_max + (1 if entry_basis == "next_close" else 0)
    ahead = forward_bars(bars, signal_date, need)
    outcome = Outcome(
        canonical_code=canonical_code, signal_date=signal_date, entry_basis=entry_basis,
    )
    outcome.forward_bars = len(ahead)
    outcome.truncated = len(ahead) < need

    # 基準価格も前向きバーと **同じ調整基準**で取る。片方だけ調整すると、
    # 分割を挟んだシグナルのリターンが丸ごと係数分ずれる。
    reference = _finite(signal_close)
    if reference is None:
        factors_all = cumulative_factors(bars)
        for row, factor in zip(bars, factors_all):
            if str(row.get("trade_date") or "") == signal_date:
                stored = _finite(row.get("adj_close"))
                reference = stored if (stored and stored > 0) else (
                    (_finite(row.get("close")) or 0.0) * factor or None
                )
                break
    outcome.entry_reference_close = reference
    if not ahead:
        return outcome

    outcome.next_open = ahead[0].open
    outcome.next_close = ahead[0].close

    if entry_basis == "next_open":
        base = _finite(ahead[0].open)
        outcome.entry_date = ahead[0].trade_date
        eval_bars: Sequence[Bar] = ahead
    elif entry_basis == "next_close":
        base = _finite(ahead[0].close)
        outcome.entry_date = ahead[0].trade_date
        eval_bars = ahead[1:]
    else:
        base = reference
        outcome.entry_date = signal_date
        eval_bars = ahead
    outcome.entry_price = base
    if base is None or base <= 0:
        return outcome

    for horizon in HORIZONS:
        outcome.returns[horizon] = _series_return(eval_bars, base, horizon)

    # ベンチマーク超過。指数側も同じ「シグナル日より後」の窓で測る。
    # next 基準では日付の対応が 1 日ずれるので、ここでは計算しない
    # （呼び出し側が entry_date に揃えた終値マップで計算する）。
    for label, benchmark, target in (() if entry_basis != "signal_close" else (
        ("topix", topix_bars, outcome.excess_topix),
        ("sector", sector_bars, outcome.excess_sector),
    )):
        if not benchmark:
            continue
        bench_ahead = forward_bars(benchmark, signal_date, horizon_max)
        bench_base = None
        for row in benchmark:
            if str(row.get("trade_date") or "") == signal_date:
                bench_base = _finite(row.get("close"))
                break
        if bench_base is None or bench_base <= 0:
            continue
        for horizon in HORIZONS:
            own = outcome.returns.get(horizon)
            bench = _series_return(bench_ahead, bench_base, horizon)
            target[horizon] = (own - bench) if (own is not None and bench is not None) else None
        _ = label

    # MFE/MAE は「入った後にどこまで含み益/含み損になったか」。終値ではなく
    # 高値・安値で測る（終値だけだと途中の踏み上げ/踏み落としが見えない）。
    highs = [bar.high for bar in eval_bars if bar.high is not None]
    lows = [bar.low for bar in eval_bars if bar.low is not None]
    if highs:
        outcome.mfe_pct = (max(highs) / base - 1.0) * 100.0
    if lows:
        outcome.mae_pct = (min(lows) / base - 1.0) * 100.0

    # 最大ドローダウン: 到達したピークからの落ち込み（順序を保って走査する）。
    peak = base
    worst = 0.0
    for bar in eval_bars:
        if bar.high is not None:
            peak = max(peak, bar.high)
        if bar.low is not None and peak > 0:
            worst = min(worst, bar.low / peak - 1.0)
    outcome.max_drawdown_pct = worst * 100.0

    # +1R と -1R のどちらに先に触れたか。同じ日に両方触れた場合は、日足では
    # 順序が分からないので **不利な側（stop）** を採る（楽観に倒さない）。
    risk = None
    if stop_price is not None and _finite(stop_price) and base > _finite(stop_price):
        risk = base - _finite(stop_price)
    elif atr14 is not None and _finite(atr14):
        risk = _finite(atr14) * R_MULTIPLE_ATR
    if risk and risk > 0:
        target_price = base + risk
        stop_level = base - risk
        for bar in eval_bars:
            touched_stop = bar.low is not None and bar.low <= stop_level
            touched_target = bar.high is not None and bar.high >= target_price
            if touched_stop:
                outcome.hit_r_multiple = "stop"
                break
            if touched_target:
                outcome.hit_r_multiple = "target"
                break
    return outcome


__all__ = ["Bar", "HORIZONS", "Outcome", "R_MULTIPLE_ATR", "compute_outcome", "forward_bars"]
