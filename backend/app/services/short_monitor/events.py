"""生の空売り残高報告 → 正規化イベント。

ここで守るのは 2 つ。

**1. 公開日より前にその情報を使わない。**
報告には「いつの残高か」(`CalcDate`) と「いつ公開されたか」(`DiscDate`) が
別々に入っていて、実測では 1〜7 日ずれる（最頻は 2 日、次が 4 日）。市場が
知りうるのは公開後なので、履歴研究に使ってよい日は
`effective_trade_date = 公開日以降の最初の営業日`。`position_date` を使うと
未来の情報を過去に流し込むことになる。

**2. 「見えなくなった」を「ゼロになった」と書かない。**
0.5% を割ると最終報告が 1 本出て、以後の報告義務が消える。そのあとの実際の
建玉は「その値以下のどこか」で、ゼロかもしれないし 0.49% のままかもしれない。
`visibility_status = below_public_threshold` / `exact_position_known = False`
として残し、比率を 0 で埋めない。明示的に 0 と報告された「解消」だけが
`closed`。
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable, Iterable, Mapping, Sequence

from app.services.short_interest import REPORTING_THRESHOLD

from .institutions import InstitutionResolver

#: イベント導出の版。分類規則を変えたら上げる。
EVENT_VERSION = "evt-v1"

# 可視性
VISIBLE_REPORTING = "reporting"
VISIBLE_BELOW_THRESHOLD = "below_public_threshold"
VISIBLE_CLOSED = "closed"

# イベント種別
EVENT_NEW = "new"                    # 初めて公開範囲に入った
EVENT_REENTRY = "reentry"            # 一度消えてから再び公開範囲に入った
EVENT_INCREASED = "increased"
EVENT_DECREASED = "decreased"
EVENT_BELOW_THRESHOLD = "below_threshold"   # 0.5% 割れ（義務消失）
EVENT_CLOSED = "closed"              # 明示的にゼロ

CORRECTION_ORIGINAL = "original"
CORRECTION_REVISED = "correction"

#: 顧客取引のヘッジであることを報告自身が述べている場合の印。方向性の売り
#: 建てとは意味が違うので、そのまま「弱気」と読んではいけない。
_HEDGE_MARKERS = ("ヘッジポジション", "ヘッジ・ポジション", "hedge position")


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def visibility_of(ratio: float | None) -> str:
    if ratio is None or ratio <= 0.0:
        return VISIBLE_CLOSED
    return VISIBLE_REPORTING if ratio >= REPORTING_THRESHOLD else VISIBLE_BELOW_THRESHOLD


def event_id_for(code: str, position_date: str, published_date: str, raw_name: str) -> str:
    seed = "|".join((code, position_date, published_date, raw_name))
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:24]


def _is_hedge(notes: Any) -> bool:
    text = str(notes or "")
    return any(marker in text for marker in _HEDGE_MARKERS)


def _classify(previous: float | None, current: float | None, *, seen_before: bool) -> str:
    before = visibility_of(previous)
    after = visibility_of(current)
    if after == VISIBLE_REPORTING and before != VISIBLE_REPORTING:
        # 初出か、一度消えてからの再登場か。ここを混ぜると「機関が戻ってきた」
        # という一番読みたい事象が「新規」に埋もれる。
        return EVENT_REENTRY if seen_before else EVENT_NEW
    if after == VISIBLE_CLOSED and before != VISIBLE_CLOSED:
        return EVENT_CLOSED
    if before == VISIBLE_REPORTING and after == VISIBLE_BELOW_THRESHOLD:
        return EVENT_BELOW_THRESHOLD
    if current is not None and previous is not None and current < previous:
        return EVENT_DECREASED
    if current is not None and previous is not None and current > previous:
        return EVENT_INCREASED
    # 変化幅が出せない（前回値なし）で、水準は報告義務中 —— 初出扱い。
    if after == VISIBLE_REPORTING:
        return EVENT_REENTRY if seen_before else EVENT_NEW
    return EVENT_DECREASED if after == VISIBLE_BELOW_THRESHOLD else EVENT_CLOSED


def build_events(
    rows: Sequence[Mapping[str, Any]],
    *,
    resolver: InstitutionResolver,
    next_trading_day: Callable[[str], str | None],
    algorithm_version: str = EVENT_VERSION,
) -> list[dict[str, Any]]:
    """1 銘柄分の生報告 → イベント列（公開日順）。

    `next_trading_day(d)` は d 以降の最初の営業日を返す。公開日が休場日なら
    翌営業日に寄せる —— 公開された日に取引できるとは限らない。
    """

    ordered = sorted(
        (row for row in rows if row.get("canonical_code")),
        key=lambda r: (
            str(r.get("disclosed_date") or ""),
            str(r.get("calculated_date") or ""),
            str(r.get("holder_name") or ""),
        ),
    )

    # 同じ (計算日, 機関) で開示日が複数 = 訂正。**後から出た訂正が過去に
    # 遡って効いてはいけない** ので、元の報告も残したまま印だけ付ける。
    disclosure_count: dict[tuple[str, str], list[str]] = {}
    for row in ordered:
        key = (str(row.get("calculated_date") or ""), str(row.get("holder_name") or ""))
        disclosure_count.setdefault(key, []).append(str(row.get("disclosed_date") or ""))

    seen_reporting: set[str] = set()
    events: list[dict[str, Any]] = []
    for row in ordered:
        raw_name = str(row.get("holder_name") or "").strip()
        if not raw_name:
            continue
        code = str(row["canonical_code"])
        position_date = str(row.get("calculated_date") or "")
        published_date = str(row.get("disclosed_date") or "")
        if not position_date or not published_date:
            continue

        mapping = resolver.resolve(raw_name)
        ratio = _finite(row.get("short_position_ratio"))
        shares = _finite(row.get("short_position_shares"))
        previous = _finite(row.get("previous_ratio"))
        legal_id = mapping.legal_id

        event_type = _classify(previous, ratio, seen_before=legal_id in seen_reporting)
        if visibility_of(ratio) == VISIBLE_REPORTING:
            seen_reporting.add(legal_id)

        disclosures = disclosure_count.get((position_date, raw_name)) or []
        is_correction = len(disclosures) > 1 and published_date != min(disclosures)

        effective = next_trading_day(published_date) or published_date
        events.append({
            "event_id": event_id_for(code, position_date, published_date, raw_name),
            "canonical_code": code,
            "legal_id": legal_id,
            "group_id": mapping.group_id,
            "raw_holder_name": raw_name,
            "position_date": position_date,
            "published_date": published_date,
            "effective_trade_date": effective,
            "short_ratio": ratio,
            "short_shares": shares,
            "previous_ratio": previous,
            "previous_report_date": str(row.get("previous_report_date") or "") or None,
            "ratio_delta": (ratio - previous) if (ratio is not None and previous is not None) else None,
            # 株数の前回値は報告に無い。比率の変化から按分すると嘘の精度が出るので
            # 出さない（株数の変化は last_known 側の差分で扱う）。
            "shares_delta": None,
            "event_type": event_type,
            "visibility_status": visibility_of(ratio),
            "correction_status": CORRECTION_REVISED if is_correction else CORRECTION_ORIGINAL,
            "is_hedge_disclosed": 1 if _is_hedge(row.get("notes")) else 0,
            "mapping_confidence": mapping.confidence,
            "algorithm_version": algorithm_version,
        })
    return events


def last_known_as_of(
    events: Iterable[Mapping[str, Any]], *, published_cutoff: str
) -> dict[str, dict[str, Any]]:
    """公開日 `published_cutoff` 時点で市場が知りえた「最後の公開状態」。

    訂正は **その訂正が公開された後** にしか効かない。締切以前で最も新しい
    公開日の報告を機関ごとに採る（同じ公開日なら計算日が新しいほう）。
    """

    latest: dict[str, tuple[tuple[str, str], Mapping[str, Any]]] = {}
    for event in events:
        published = str(event.get("published_date") or "")
        if not published or published > published_cutoff:
            continue
        legal_id = str(event.get("legal_id") or "")
        if not legal_id:
            continue
        key = (published, str(event.get("position_date") or ""))
        current = latest.get(legal_id)
        if current is None or key > current[0]:
            latest[legal_id] = (key, event)

    out: dict[str, dict[str, Any]] = {}
    for legal_id, (_key, event) in latest.items():
        status = str(event.get("visibility_status") or VISIBLE_CLOSED)
        out[legal_id] = {
            "legal_id": legal_id,
            "group_id": event.get("group_id"),
            "last_reported_ratio": event.get("short_ratio"),
            "last_reported_shares": event.get("short_shares"),
            "last_position_date": event.get("position_date"),
            "last_published_date": event.get("published_date"),
            "visibility_status": status,
            # 「見えている」のは報告義務が続いている間だけ。閾値割れの後の
            # 実際の建玉は不明であって、ゼロではない。
            "exact_position_known": status == VISIBLE_REPORTING,
            "is_hedge_disclosed": int(event.get("is_hedge_disclosed") or 0),
            "mapping_confidence": event.get("mapping_confidence"),
        }
    return out


def visible_totals(last_known: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """報告義務が続いている機関だけの合計。閾値割れは **数えるが足さない**。"""

    ratios: list[float] = []
    shares: list[float] = []
    shares_missing = False
    below = 0
    closed = 0
    hedge = 0
    for state in last_known.values():
        status = state.get("visibility_status")
        if status == VISIBLE_REPORTING:
            ratio = _finite(state.get("last_reported_ratio"))
            if ratio is not None:
                ratios.append(ratio)
            value = _finite(state.get("last_reported_shares"))
            if value is None:
                shares_missing = True
            else:
                shares.append(value)
            hedge += int(state.get("is_hedge_disclosed") or 0)
        elif status == VISIBLE_BELOW_THRESHOLD:
            below += 1
        else:
            closed += 1
    return {
        "visible_short_ratio": round(sum(ratios), 8) if ratios else 0.0,
        # 欠損を 0 として足すと合計が黙って小さく出る。1 件でも欠けたら出さない。
        "visible_short_shares": None if shares_missing else (sum(shares) if shares else 0.0),
        "visible_institution_count": len(ratios),
        "below_threshold_count": below,
        "closed_count": closed,
        "hedge_institution_count": hedge,
        "largest_institution_ratio": max(ratios) if ratios else 0.0,
        "concentration": _herfindahl(ratios),
    }


def _herfindahl(ratios: Sequence[float]) -> float | None:
    """可視分の中での集中度（0〜1）。1 社だけなら 1.0。"""

    total = sum(ratios)
    if total <= 0.0 or not ratios:
        return None
    return round(sum((value / total) ** 2 for value in ratios), 6)


__all__ = [
    "CORRECTION_ORIGINAL",
    "CORRECTION_REVISED",
    "EVENT_BELOW_THRESHOLD",
    "EVENT_CLOSED",
    "EVENT_DECREASED",
    "EVENT_INCREASED",
    "EVENT_NEW",
    "EVENT_REENTRY",
    "EVENT_VERSION",
    "VISIBLE_BELOW_THRESHOLD",
    "VISIBLE_CLOSED",
    "VISIBLE_REPORTING",
    "build_events",
    "event_id_for",
    "last_known_as_of",
    "visibility_of",
    "visible_totals",
]
