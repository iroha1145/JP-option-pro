"""生の空売り残高報告 → 正規化イベント。

ここで守るのは 3 つ。

**1. 公開日より前にその情報を使わない。しかも公開日当日も使わない。**
報告には「いつの残高か」(`CalcDate`) と「いつ公開されたか」(`DiscDate`) が
別々に入っていて、実測では 1〜13 日ずれる（最頻は 2 日、次が 4 日）。さらに
JPX の公表は当日 16:00 締めの受付分 —— つまり **その日の取引が終わってから**
出る。公開日の終値を「その情報で取れた値段」として使うのは後知恵になるので、
`effective_trade_date = 公開日より後の最初の営業日`（厳密に後）。

**2. 「見えなくなった」を「ゼロになった」と書かない。**
0.5% を割ると最終報告が 1 本出て、以後の報告義務が消える。そのあとの実際の
建玉は「その値以下のどこか」。`below_public_threshold` として残し、0 で
埋めない。明示的に 0 と報告された「解消」だけが `closed`。比率が読めない
行は `unknown` —— **欠損は解消ではない**。

**3. 変化は「報告と報告の差」で数える。可視合計の差では数えない。**
可視合計は「今も報告義務中の機関」だけの和なので、閾値割れ・再参入・報告
停止のたびに合計から機関ごと出入りする。合計の差を取ると
0.60%→0.49% の実際の減仓 11 万株が「60 万株減った」ことになる。
差分は **同一機関・同一ファンドの隣り合う報告** の差から積み上げる。

報告の連鎖（chain）は `(legal_id, investment_fund_name)`。同じ機関が複数の
ファンド名義で並行して報告することがあり（実データ 2,094 行）、機関単位に
潰すと片方のファンドの建玉が黙って消える。
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable, Iterable, Mapping, Sequence

from app.services.short_interest import REPORTING_THRESHOLD

from .institutions import InstitutionResolver

#: イベント導出の版。分類規則を変えたら上げる。
#: v3: 効力日を厳密に公開日の翌営業日へ / (legal, fund) 連鎖 / unknown 可視性 /
#:     訂正の 2 段選択 / 逐機関の窓内差分。
EVENT_VERSION = "evt-v3"

#: 「まだ報告義務中」の最終報告が、これより古ければ現在の建玉の証拠にならない。
#:
#: 報告義務は 0.1% 動くたびに発生する。0.5% 以上の建玉が半年間 1 度も 0.1%
#: 動かない、ということは実務上ほぼ無い。にもかかわらず本番データでは
#: `reporting` 状態 4,352 件のうち **940 件が 250 営業日超**（685 銘柄）で、
#: 経過日数の分布は 20 日以内 3,035 件 → 61〜250 日 106 件 → 250 日超 940 件
#: と明確に二峰。間の谷がそのまま境目になる。
#:
#: ただしこれは **データ品質のヒューリスティック** であって、公式ルールに
#: 「125 日で失効」は無い（変動が 0.1% に届かなければ再報告義務は生じない）。
#: だから 2 本立てで持つ: `visible_*`（新鮮な部分集合）と
#: `reported_in_scope_*`（最終報告がまだ公開範囲内の全機関）。どちらか片方を
#: 正とはしない —— 前者は「証拠が新しい」、後者は「ルール上まだ義務中」。
STALE_REPORT_TRADING_DAYS = 125

# 可視性
VISIBLE_REPORTING = "reporting"
VISIBLE_BELOW_THRESHOLD = "below_public_threshold"
VISIBLE_CLOSED = "closed"
#: 比率が読めない行。**欠損を「解消」と同じ箱に入れない。**
VISIBLE_UNKNOWN = "unknown"

# イベント種別
EVENT_NEW = "new"                    # 初めて公開範囲に入った
EVENT_REENTRY = "reentry"            # 一度消えてから再び公開範囲に入った
EVENT_INCREASED = "increased"
EVENT_DECREASED = "decreased"
EVENT_BELOW_THRESHOLD = "below_threshold"   # 0.5% 割れ（義務消失）
EVENT_CLOSED = "closed"              # 明示的にゼロ
EVENT_UNKNOWN = "unknown"            # 比率が読めない（行動としては数えない）

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
    if ratio is None:
        return VISIBLE_UNKNOWN
    if ratio <= 0.0:
        return VISIBLE_CLOSED
    return VISIBLE_REPORTING if ratio >= REPORTING_THRESHOLD else VISIBLE_BELOW_THRESHOLD


def event_id_for(
    code: str,
    position_date: str,
    published_date: str,
    raw_name: str,
    fund: str = "",
    address: str = "",
    manager: str = "",
) -> str:
    """同じ主体・同じ日でもファンド・住所・運用者が違えば別の報告。
    ここを畳むと生 PK と同じ静かな上書きがイベント層でも起きる。"""

    seed = "|".join((code, position_date, published_date, raw_name, fund, address, manager))
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:24]


def _is_hedge(notes: Any) -> bool:
    text = str(notes or "")
    return any(marker in text for marker in _HEDGE_MARKERS)


def _classify(previous: float | None, current: float | None, *, seen_before: bool) -> str:
    if current is None and previous is None:
        return EVENT_UNKNOWN
    before = visibility_of(previous)
    after = visibility_of(current)
    if after == VISIBLE_UNKNOWN:
        return EVENT_UNKNOWN
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


def chain_key_of(event: Mapping[str, Any]) -> str:
    """報告の連鎖の識別子。同一機関でもファンドが違えば別の連鎖。"""

    fund = str(event.get("investment_fund_name") or "").strip()
    if fund in ("-", "－"):
        fund = ""
    return f"{event.get('legal_id') or ''}||{fund}"


def build_events(
    rows: Sequence[Mapping[str, Any]],
    *,
    resolver: InstitutionResolver,
    first_tradable_day: Callable[[str], str | None],
    algorithm_version: str = EVENT_VERSION,
) -> list[dict[str, Any]]:
    """1 銘柄分の生報告 → イベント列（公開日順）。

    `first_tradable_day(d)` は **d より厳密に後** の最初の営業日を返すこと。
    JPX の公表は当日の取引終了後なので、公開日当日の終値はこの情報では
    取れない —— 効力日を当日に置くと、検証がその日の終値を「入れた値段」
    として使ってしまう。
    """

    ordered = sorted(
        (row for row in rows if row.get("canonical_code")),
        key=lambda r: (
            str(r.get("disclosed_date") or ""),
            str(r.get("calculated_date") or ""),
            str(r.get("holder_name") or ""),
            str(r.get("investment_fund_name") or ""),
        ),
    )

    # 同じ (計算日, 機関, ファンド) で開示日が複数 = 訂正。**後から出た訂正が
    # 過去に遡って効いてはいけない** ので、元の報告も残したまま印だけ付ける。
    # ファンドを鍵に入れないと、同日に並行して出た別ファンドの報告どうしが
    # 互いの「訂正」に化ける。
    disclosure_count: dict[tuple[str, str, str], list[str]] = {}
    for row in ordered:
        key = (
            str(row.get("calculated_date") or ""),
            str(row.get("holder_name") or ""),
            str(row.get("investment_fund_name") or ""),
        )
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

        address = str(row.get("holder_address") or "").strip()
        manager = str(row.get("manager_name") or "").strip()
        fund = str(row.get("investment_fund_name") or "").strip()
        if fund in ("-", "－"):
            fund = ""

        mapping = resolver.resolve(raw_name, address=address)
        ratio = _finite(row.get("short_position_ratio"))
        shares = _finite(row.get("short_position_shares"))
        previous = _finite(row.get("previous_ratio"))
        legal_id = mapping.legal_id

        event_type = _classify(previous, ratio, seen_before=legal_id in seen_reporting)
        if visibility_of(ratio) == VISIBLE_REPORTING:
            seen_reporting.add(legal_id)

        disclosures = disclosure_count.get((position_date, raw_name, str(row.get("investment_fund_name") or ""))) or []
        is_correction = len(disclosures) > 1 and published_date != min(disclosures)

        effective = first_tradable_day(published_date) or published_date
        events.append({
            "event_id": event_id_for(
                code, position_date, published_date, raw_name, fund, address, manager,
            ),
            "canonical_code": code,
            "legal_id": legal_id,
            "group_id": mapping.group_id,
            "raw_holder_name": raw_name,
            "investment_fund_name": fund or None,
            "holder_address": address or None,
            "manager_name": manager or None,
            "position_date": position_date,
            "published_date": published_date,
            "effective_trade_date": effective,
            "short_ratio": ratio,
            "short_shares": shares,
            "previous_ratio": previous,
            "previous_report_date": str(row.get("previous_report_date") or "") or None,
            "ratio_delta": (ratio - previous) if (ratio is not None and previous is not None) else None,
            # 株数の前回値は報告に無い。窓内の変化は window_changes() が
            # 同一連鎖の隣り合う報告の差から出す。
            "shares_delta": None,
            "event_type": event_type,
            "visibility_status": visibility_of(ratio),
            "correction_status": CORRECTION_REVISED if is_correction else CORRECTION_ORIGINAL,
            "is_hedge_disclosed": 1 if _is_hedge(row.get("notes")) else 0,
            "mapping_confidence": mapping.confidence,
            "algorithm_version": algorithm_version,
        })
    return events


# ---------------------------------------------------------------------------
# 締切時点の状態（連鎖 → 機関へ集約）
# ---------------------------------------------------------------------------

def _chain_states(
    events: Iterable[Mapping[str, Any]], *, published_cutoff: str
) -> dict[str, Mapping[str, Any]]:
    """連鎖ごとの「締切時点の現在状態」。訂正は 2 段階で適用する。

    1. 同じ (連鎖, 仓位日) の中では、締切以前で最も新しい公開の版を採る
       （訂正が古い版を置き換える）。
    2. その有効版の中で **仓位日が最新** のものが現在状態。

    1 段階で「公開日が最新」を採ると、古い仓位日の訂正が後から公開された
    だけで、より新しい仓位状態を上書きしてしまう（7/15 の状態が 7/10 の
    訂正で巻き戻る）。
    """

    by_position: dict[str, dict[str, Mapping[str, Any]]] = {}
    for event in events:
        published = str(event.get("published_date") or "")
        if not published or published > published_cutoff:
            continue
        legal_id = str(event.get("legal_id") or "")
        if not legal_id:
            continue
        chain = chain_key_of(event)
        position = str(event.get("position_date") or "")
        slot = by_position.setdefault(chain, {})
        current = slot.get(position)
        if current is None or published > str(current.get("published_date") or ""):
            slot[position] = event

    out: dict[str, Mapping[str, Any]] = {}
    for chain, versions in by_position.items():
        position, event = max(
            versions.items(),
            key=lambda item: (item[0], str(item[1].get("published_date") or "")),
        )
        out[chain] = event
    return out


def last_known_as_of(
    events: Iterable[Mapping[str, Any]],
    *,
    published_cutoff: str,
    trading_days: Sequence[str] | None = None,
    stale_after: int = STALE_REPORT_TRADING_DAYS,
) -> dict[str, dict[str, Any]]:
    """公開日 `published_cutoff` 時点で市場が知りえた「最後の公開状態」を
    機関（legal_id）単位に集約して返す。内部はファンド連鎖ごとに追う。"""

    chains = _chain_states(events, published_cutoff=published_cutoff)
    calendar = list(trading_days or ())

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for chain, event in chains.items():
        legal_id = chain.split("||", 1)[0]
        grouped.setdefault(legal_id, []).append(event)

    out: dict[str, dict[str, Any]] = {}
    for legal_id, chain_events in grouped.items():
        fresh_ratio = 0.0
        fresh_shares: float | None = 0.0
        in_scope_ratio = 0.0
        in_scope_shares: float | None = 0.0
        statuses: list[str] = []
        reporting_all_stale = True
        has_reporting = False
        unknown_chains = 0
        newest_age: int | None = None
        last_position = ""
        last_published = ""
        hedge = 0
        mapping_confidence: float | None = None

        for event in chain_events:
            status = str(event.get("visibility_status") or VISIBLE_UNKNOWN)
            statuses.append(status)
            age = _age_in_trading_days(calendar, event.get("published_date"))
            if age is not None:
                newest_age = age if newest_age is None else min(newest_age, age)
            last_position = max(last_position, str(event.get("position_date") or ""))
            last_published = max(last_published, str(event.get("published_date") or ""))
            hedge = hedge or int(event.get("is_hedge_disclosed") or 0)
            conf = _finite(event.get("mapping_confidence"))
            if conf is not None:
                mapping_confidence = conf if mapping_confidence is None else min(mapping_confidence, conf)

            if status == VISIBLE_UNKNOWN:
                unknown_chains += 1
                continue
            if status != VISIBLE_REPORTING:
                continue
            has_reporting = True
            ratio = _finite(event.get("short_ratio"))
            shares = _finite(event.get("short_shares"))
            stale_chain = bool(age is not None and age > stale_after)
            if ratio is not None:
                in_scope_ratio += ratio
                if in_scope_shares is not None:
                    in_scope_shares = (in_scope_shares + shares) if shares is not None else None
            if not stale_chain:
                reporting_all_stale = False
                if ratio is not None:
                    fresh_ratio += ratio
                    if fresh_shares is not None:
                        fresh_shares = (fresh_shares + shares) if shares is not None else None

        if has_reporting:
            status = VISIBLE_REPORTING
        elif VISIBLE_BELOW_THRESHOLD in statuses:
            status = VISIBLE_BELOW_THRESHOLD
        elif unknown_chains and VISIBLE_CLOSED not in statuses:
            status = VISIBLE_UNKNOWN
        else:
            status = VISIBLE_CLOSED
        stale = bool(has_reporting and reporting_all_stale)

        # 表示用の「最後に報告された値」。報告義務中ならその合算（義務中の
        # 全連鎖）、そうでなければ最新の仓位日の値。
        if has_reporting:
            shown_ratio: float | None = in_scope_ratio
            shown_shares = in_scope_shares
        else:
            newest = max(
                chain_events,
                key=lambda e: (str(e.get("position_date") or ""), str(e.get("published_date") or "")),
            )
            shown_ratio = _finite(newest.get("short_ratio"))
            shown_shares = _finite(newest.get("short_shares"))

        out[legal_id] = {
            "legal_id": legal_id,
            "group_id": chain_events[0].get("group_id"),
            "last_reported_ratio": shown_ratio,
            "last_reported_shares": shown_shares,
            "last_position_date": last_position or None,
            "last_published_date": last_published or None,
            "visibility_status": status,
            "state_age_trading_days": newest_age,
            # 報告義務中でも、最終報告が古すぎれば「新鮮な証拠」ではない。
            # ルール上はまだ義務中なので in_scope には残る。
            "stale_reporting": stale,
            # 正確なのは **その仓位日時点** の値であって、今日の建玉ではない。
            "exact_at_position_date": status == VISIBLE_REPORTING and not stale,
            "in_scope_ratio": round(in_scope_ratio, 8) if has_reporting else None,
            "in_scope_shares": in_scope_shares if has_reporting else None,
            "fresh_ratio": round(fresh_ratio, 8) if has_reporting else None,
            "fresh_shares": fresh_shares if has_reporting else None,
            "chain_count": len(chain_events),
            "unknown_chain_count": unknown_chains,
            "is_hedge_disclosed": hedge,
            "mapping_confidence": mapping_confidence,
        }
    return out


def _age_in_trading_days(calendar: Sequence[str], day: Any) -> int | None:
    text = str(day or "")
    if not text or not calendar:
        return None
    import bisect

    index = bisect.bisect_left(calendar, text)
    if index >= len(calendar):
        return 0
    return max(0, len(calendar) - 1 - index)


def visible_totals(last_known: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """2 本立ての合計。

    * `visible_*` — 報告が新鮮（125 営業日以内）な報告義務中だけの和。
      因子と状態判定はこちらを使う（古い値を「今の圧力」と読まない）。
    * `reported_in_scope_*` — 最終報告がまだ公開範囲内（≥0.5%）の全機関の和。
      公式ルール上はこちらが「報告義務中の合計」。125 日は運用上の目安で
      あって失効規定ではないので、この口径も常に一緒に出す。
    """

    fresh_ratios: list[float] = []
    fresh_shares: list[float] = []
    fresh_shares_missing = False
    scope_ratio = 0.0
    scope_shares: float | None = 0.0
    below = 0
    closed = 0
    unknown = 0
    hedge = 0
    stale = 0
    for state in last_known.values():
        status = state.get("visibility_status")
        if status == VISIBLE_REPORTING:
            ratio = _finite(state.get("in_scope_ratio"))
            if ratio is not None:
                scope_ratio += ratio
                value = _finite(state.get("in_scope_shares"))
                if scope_shares is not None:
                    scope_shares = (scope_shares + value) if value is not None else None
            hedge += int(state.get("is_hedge_disclosed") or 0)
            if state.get("stale_reporting"):
                # 報告義務中の表示のまま何年も更新が無いもの。新鮮な合計には
                # 足さないが、公式口径（in_scope）には入っている。
                stale += 1
            else:
                fresh = _finite(state.get("fresh_ratio"))
                if fresh is not None:
                    fresh_ratios.append(fresh)
                value = _finite(state.get("fresh_shares"))
                if value is None:
                    fresh_shares_missing = True
                else:
                    fresh_shares.append(value)
        elif status == VISIBLE_BELOW_THRESHOLD:
            below += 1
        elif status == VISIBLE_UNKNOWN:
            unknown += 1
        else:
            closed += 1
    return {
        "visible_short_ratio": round(sum(fresh_ratios), 8) if fresh_ratios else 0.0,
        # 欠損を 0 として足すと合計が黙って小さく出る。1 件でも欠けたら出さない。
        "visible_short_shares": (
            None if fresh_shares_missing else (sum(fresh_shares) if fresh_shares else 0.0)
        ),
        "visible_institution_count": len(fresh_ratios),
        "reported_in_scope_ratio": round(scope_ratio, 8),
        "reported_in_scope_shares": scope_shares,
        "stale_reporting_count": stale,
        "below_threshold_count": below,
        "closed_count": closed,
        "unknown_count": unknown,
        "hedge_institution_count": hedge,
        "largest_institution_ratio": max(fresh_ratios) if fresh_ratios else 0.0,
        "concentration": _herfindahl(fresh_ratios),
    }


# ---------------------------------------------------------------------------
# 窓内の変化（逐連鎖の報告差）
# ---------------------------------------------------------------------------

def window_changes(
    events: Iterable[Mapping[str, Any]],
    *,
    from_cutoff: str,
    to_cutoff: str,
) -> dict[str, Any]:
    """`(from_cutoff, to_cutoff]` の間に公開で分かった建玉変化。

    連鎖ごとに「締切時点の現在値」を 2 点取り、差を積み上げる。可視合計の
    差ではないので、閾値割れは「最終報告の値までの減少」、再参入は
    「最後に見えていた値からの増加」、初出は「開示された全量」になる。
    """

    events = list(events)
    now = _chain_states(events, published_cutoff=to_cutoff)
    before = _chain_states(events, published_cutoff=from_cutoff)

    ratio_change = 0.0
    ratio_known = False
    shares_change = 0.0
    shares_known = False
    gross_increase = 0.0
    gross_reduction = 0.0
    unknown_chains = 0

    for chain, current in now.items():
        prior = before.get(chain)
        ratio_now = _finite(current.get("short_ratio"))
        ratio_prev = _finite(prior.get("short_ratio")) if prior is not None else 0.0
        if ratio_now is None or ratio_prev is None:
            unknown_chains += 1
        else:
            ratio_change += ratio_now - ratio_prev
            ratio_known = True

        shares_now = _shares_of(current)
        shares_prev = _shares_of(prior) if prior is not None else 0.0
        if shares_now is None or shares_prev is None:
            continue
        delta = shares_now - shares_prev
        shares_change += delta
        shares_known = True
        if delta > 0:
            gross_increase += delta
        elif delta < 0:
            gross_reduction += -delta

    return {
        "ratio_change": round(ratio_change, 8) if ratio_known else (None if unknown_chains else 0.0),
        "shares_change": shares_change if shares_known else (None if unknown_chains else 0.0),
        "gross_increase_shares": gross_increase if shares_known else None,
        "gross_reduction_shares": gross_reduction if shares_known else None,
        "unknown_chains": unknown_chains,
    }


def _shares_of(event: Mapping[str, Any]) -> float | None:
    shares = _finite(event.get("short_shares"))
    if shares is not None:
        return shares
    # 明示的な解消（比率 0）は株数も 0 と読む。それ以外の欠損は不明のまま。
    ratio = _finite(event.get("short_ratio"))
    if ratio is not None and ratio <= 0.0:
        return 0.0
    return None


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
    "EVENT_UNKNOWN",
    "EVENT_VERSION",
    "STALE_REPORT_TRADING_DAYS",
    "VISIBLE_BELOW_THRESHOLD",
    "VISIBLE_CLOSED",
    "VISIBLE_REPORTING",
    "VISIBLE_UNKNOWN",
    "build_events",
    "chain_key_of",
    "event_id_for",
    "last_known_as_of",
    "visibility_of",
    "visible_totals",
    "window_changes",
]
