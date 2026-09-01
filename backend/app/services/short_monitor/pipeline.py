"""ワーカーが回す再構築と再計算。

    生の報告
      → イベント正規化 / 最後の公開状態      （rebuild_events）
      → 銘柄 × 日のスナップショット           （refresh_snapshots）
      → 状態変化だけを信号として保存

API 側はこの結果を読むだけで、ページ表示が全市場計算を起こさない。
途中で落ちても、前回の有効なスナップショットは消さない（上書きのみ）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from app.repositories.core import CoreRepository
from app.services.margin_regulation import build_regulation_map

from . import events as ev
from . import snapshot as snap
from .institutions import INSTITUTION_VERSION, InstitutionResolver

#: スナップショットに要る足の本数（52 週高値・200 日線・252 日分位）。
BAR_LOOKBACK_TRADING_DAYS = 300

#: 1 度に書き込む行数。
BATCH_SIZE = 2000


@dataclass
class RebuildResult:
    codes: int = 0
    events: int = 0
    last_known: int = 0
    institutions: int = 0
    aliases: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "codes": self.codes, "events": self.events, "last_known": self.last_known,
            "institutions": self.institutions, "aliases": self.aliases,
            "institution_version": INSTITUTION_VERSION, "event_version": ev.EVENT_VERSION,
        }


def rebuild_events(
    repository: CoreRepository,
    *,
    progress: Callable[[str], None] | None = None,
) -> RebuildResult:
    """生の報告からイベントと最後の公開状態を作り直す。

    再構築は **全量**。イベント ID は内容から決まるので、同じ入力なら同じ行に
    上書きされる（何度走らせても同じ結果）。訂正が後から来ても、その銘柄の
    履歴をまるごと引き直すので取りこぼさない。
    """

    calendar = repository.trading_days_between("2000-01-01", "2100-01-01")
    if not calendar:
        return RebuildResult()
    calendar_set = sorted(calendar)

    def first_tradable_day(day: str) -> str | None:
        # **厳密に後**（bisect_right）。JPX の公表は当日 16:00 締めの受付分
        # —— その日の取引が終わってから出る。公開日当日を効力日にすると、
        # 検証がその日の終値を「この情報で取れた値段」として使ってしまう。
        import bisect

        index = bisect.bisect_right(calendar_set, day)
        return calendar_set[index] if index < len(calendar_set) else None

    resolver = InstitutionResolver(curated=repository.institution_alias_map())
    # 事前パス: 同じ正規化名に複数の住所が観測される名前を確定する。
    # ここで確定してから resolve するので、実体 ID が走査順に依存しない。
    for _code, rows in repository.iter_short_positions_by_code():
        for row in rows:
            resolver.observe(row.get("holder_name"), row.get("holder_address"))
    homonyms = resolver.finalize_observations()
    if progress and homonyms:
        progress(f"{len(homonyms)} homonym names split by address")

    #: 今回のビルド識別子。全行に押して、最後に旧ビルドの行を掃除する。
    #: utc_now_iso() は秒精度なので、同じ秒に 2 回走ると同じ値になり
    #: 掃除が空振りする —— 乱数の尾を付けて一意にする。
    from uuid import uuid4

    from app.repositories.base import utc_now_iso

    build_version = f"{utc_now_iso()}-{uuid4().hex[:8]}"
    latest_published = repository.latest_short_position_date() or calendar_set[-1]
    # 「最後の報告から何営業日経ったか」は **今日まで** で数える。
    # 取引カレンダーは 1 年先まで入っているので、そのまま末尾を使うと
    # 昨日出たばかりの報告が 247 営業日前ということになり、全銘柄の
    # データ信頼度が一律に落ちる（実データでそうなっていた）。
    past = [day for day in calendar_set if day <= latest_published]
    age_calendar = past or calendar_set

    result = RebuildResult()
    entities: dict[str, dict[str, Any]] = {}
    aliases: dict[str, dict[str, Any]] = {}
    event_batch: list[dict[str, Any]] = []
    known_batch: list[dict[str, Any]] = []

    for code, rows in repository.iter_short_positions_by_code():
        events = ev.build_events(
            rows, resolver=resolver, first_tradable_day=first_tradable_day,
        )
        for event in events:
            event["build_version"] = build_version
        if not events:
            continue
        result.codes += 1
        event_batch.extend(events)

        known = ev.last_known_as_of(
            events, published_cutoff=latest_published, trading_days=age_calendar,
        )
        for legal_id, state in known.items():
            row = {"canonical_code": code, **state}
            # DB 列は旧名のまま（意味は「その仓位日時点で正確」）。
            row["exact_position_known"] = 1 if state.get("exact_at_position_date") else 0
            row["build_version"] = build_version
            known_batch.append(row)

        for event in events:
            raw = str(event["raw_holder_name"])
            mapping = resolver.resolve(raw, address=event.get("holder_address"))
            entity = entities.setdefault(mapping.legal_id, {
                "legal_id": mapping.legal_id,
                "display_name": mapping.display_name,
                "normalized_name": mapping.normalized_name,
                "group_id": mapping.group_id,
                "group_name": mapping.group_name,
                "country_hint": None,
                "first_seen_date": event["published_date"],
                "last_seen_date": event["published_date"],
                "report_count": 0,
            })
            entity["report_count"] += 1
            entity["first_seen_date"] = min(entity["first_seen_date"], event["published_date"])
            entity["last_seen_date"] = max(entity["last_seen_date"], event["published_date"])
            if raw not in aliases:
                source = next((r for r in rows if r.get("holder_name") == raw), {})
                aliases[raw] = {
                    "raw_name": raw, "legal_id": mapping.legal_id,
                    "match_kind": mapping.match_kind, "confidence": mapping.confidence,
                    "raw_address": source.get("holder_address"),
                    "manager_name": source.get("manager_name"),
                    "build_version": build_version,
                }

        if len(event_batch) >= BATCH_SIZE:
            result.events += repository.upsert_short_position_events(event_batch)
            event_batch = []
        if len(known_batch) >= BATCH_SIZE:
            result.last_known += repository.upsert_short_position_last_known(known_batch)
            known_batch = []
        if progress and result.codes % 500 == 0:
            progress(f"events rebuilt for {result.codes} codes")

    if event_batch:
        result.events += repository.upsert_short_position_events(event_batch)
    if known_batch:
        result.last_known += repository.upsert_short_position_last_known(known_batch)

    for entity in entities.values():
        entity["build_version"] = build_version
    result.institutions = repository.upsert_institution_entities(entities.values())
    result.aliases = repository.upsert_institution_aliases(aliases.values())
    # UPSERT だけだと、規則変更やデータ訂正で導出されなくなった行が幽霊として
    # 残る。今回のビルドに含まれない行をここで掃除する（curated は残す）。
    swept = repository.sweep_short_monitor_build(build_version)
    if progress and any(swept.values()):
        progress(f"swept stale derived rows: {swept}")
    return result


def _age_in_trading_days(calendar: Sequence[str], day: str | None) -> int | None:
    if not day or not calendar:
        return None
    import bisect

    index = bisect.bisect_left(calendar, day)
    if index >= len(calendar):
        return 0
    return max(0, len(calendar) - 1 - index)


@dataclass
class RefreshResult:
    as_of_date: str | None = None
    snapshots: int = 0
    signals: int = 0
    algorithm_version: str = snap.SNAPSHOT_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date, "snapshots": self.snapshots,
            "signals": self.signals, "algorithm_version": self.algorithm_version,
        }


def refresh_snapshots(
    repository: CoreRepository,
    *,
    as_of_date: str | None = None,
    radar_confirmations: Mapping[str, Mapping[str, bool]] | None = None,
    news_counts: Mapping[str, int] | None = None,
    has_news_feed: bool = True,
    progress: Callable[[str], None] | None = None,
) -> RefreshResult:
    """全市場のスナップショットを 1 営業日分作る。"""

    target = as_of_date or repository.latest_trading_day(
        repository.latest_bar_date() or "2100-01-01"
    )
    if not target:
        return RefreshResult()

    calendar = repository.trading_days_between("2000-01-01", target)
    if not calendar:
        return RefreshResult()
    window = calendar[-BAR_LOOKBACK_TRADING_DAYS:]
    start = window[0]

    bars = repository.bars_matrix_since(start)
    securities = {row["canonical_code"]: row for row in repository.list_securities()}
    topix = {
        row["trade_date"]: row.get("close")
        for row in repository.index_series("0000", start_date=start)
    }
    events_by_code = _events_by_code(repository, published_through=target)
    margin = _margin_map(repository)
    regulation = _regulation_map(repository, securities.keys(), as_of=target, calendar=calendar)
    earnings = _earnings_distance(repository, calendar=calendar, as_of=target)
    confirmations = radar_confirmations or {}
    news = news_counts or {}

    stocks: list[snap.StockInputs] = []
    for code, series in bars.items():
        security = securities.get(code) or {}
        trimmed = [bar for bar in series if str(bar.get("trade_date") or "") <= target]
        if not trimmed:
            continue
        confirm = confirmations.get(code) or {}
        stocks.append(snap.StockInputs(
            canonical_code=code,
            bars=trimmed,
            events=events_by_code.get(code, []),
            sector33_code=security.get("sector33_code"),
            margin=margin.get(code),
            regulation_severity=int((regulation.get(code) or {}).get("severity") or 0),
            trading_days_to_earnings=earnings.get(code),
            news_count_5d=int(news.get(code) or 0),
            breakout_confirmed=bool(confirm.get("breakout")),
            turnover_confirmed=bool(confirm.get("turnover")),
        ))

    if progress:
        progress(f"{len(stocks)} codes prepared for {target}")

    market = snap.MarketInputs(
        as_of_date=target, trading_days=list(window),
        topix_closes=topix, has_news_feed=has_news_feed,
    )
    rows = snap.build_snapshots(stocks, market)
    if not rows:
        # 失敗時に前回の有効なスナップショットを消さない（上書きしない）。
        return RefreshResult(as_of_date=target)

    previous_date = _previous_snapshot_date(repository, target)
    previous_states = repository.short_behavior_state_map(previous_date) if previous_date else {}
    signals = snap.build_signals(rows, previous_states, source_cutoff=target)

    # 全行 + 信号 + run マーカーを 1 トランザクションで公開する。バッチを
    # 分けると、途中で落ちた半端な断面が MAX(as_of_date) 越しに「最新」に
    # 見える（audit P0-6）。
    from uuid import uuid4

    run_id = uuid4().hex[:16]
    written = repository.publish_short_behavior_day(
        rows, signals, as_of_date=target, run_id=run_id,
        algorithm_version=snap.SNAPSHOT_VERSION,
    )

    return RefreshResult(
        as_of_date=target, snapshots=written["snapshots"], signals=written["signals"],
    )


def _previous_snapshot_date(repository: CoreRepository, target: str) -> str | None:
    with repository.read() as connection:
        row = connection.execute(
            "SELECT MAX(as_of_date) FROM short_behavior_snapshots WHERE as_of_date < ?",
            (target,),
        ).fetchone()
    return row[0] if row and row[0] else None


def _events_by_code(
    repository: CoreRepository, *, published_through: str
) -> dict[str, list[dict[str, Any]]]:
    """公開済みイベントだけを銘柄ごとに束ねる。

    `published_date <= 対象日` で切る —— 仓位日で切ると未来の情報が入る。
    """

    out: dict[str, list[dict[str, Any]]] = {}
    with repository.read() as connection:
        rows = connection.execute(
            "SELECT canonical_code, legal_id, group_id, raw_holder_name, "
            "investment_fund_name, position_date, "
            "published_date, effective_trade_date, short_ratio, short_shares, previous_ratio, "
            "ratio_delta, event_type, visibility_status, correction_status, "
            "is_hedge_disclosed, mapping_confidence "
            "FROM short_position_events WHERE published_date <= ? "
            "ORDER BY canonical_code, published_date",
            (published_through,),
        ).fetchall()
    for row in rows:
        out.setdefault(row["canonical_code"], []).append(dict(row))
    return out


def _margin_map(repository: CoreRepository) -> dict[str, dict[str, Any]]:
    """直近 2 週分の信用残から、水準と変化を取る（週次データ）。"""

    with repository.read() as connection:
        latest = connection.execute("SELECT MAX(application_date) FROM margin_interest").fetchone()[0]
        if not latest:
            return {}
        prior = connection.execute(
            "SELECT MAX(application_date) FROM margin_interest WHERE application_date < ?",
            (latest,),
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT canonical_code, application_date, long_total, short_total "
            "FROM margin_interest WHERE application_date IN (?, ?)",
            (latest, prior or latest),
        ).fetchall()

    current: dict[str, dict[str, Any]] = {}
    previous: dict[str, float] = {}
    for row in rows:
        code = row["canonical_code"]
        if row["application_date"] == latest:
            current[code] = {
                "long_total": row["long_total"], "short_total": row["short_total"],
                "application_date": latest,
            }
        elif row["long_total"] is not None:
            previous[code] = float(row["long_total"])
    for code, state in current.items():
        before = previous.get(code)
        now = state.get("long_total")
        state["long_change"] = (
            float(now) - before if (now is not None and before is not None) else None
        )
    return current


def _regulation_map(
    repository: CoreRepository, universe: Iterable[str], *, as_of: str, calendar: Sequence[str]
) -> dict[str, dict[str, Any]]:
    alerts = repository.latest_margin_alert_map()
    alert_date = repository.latest_margin_alert_date()
    since = None
    if alert_date and alert_date in calendar:
        since = len(calendar) - 1 - calendar.index(alert_date)
    states = build_regulation_map(
        alerts.values(), as_of=as_of, trading_days_since=since, universe=universe,
    )
    return {
        code: {"severity": getattr(state, "severity", 0), "level": getattr(state, "level", None)}
        for code, state in states.items()
    }


def _earnings_distance(
    repository: CoreRepository, *, calendar: Sequence[str], as_of: str
) -> dict[str, int]:
    """次の決算発表まで何営業日か。過ぎた予定は数えない。

    呼び出し側の ``calendar`` はスナップショット日で切れている（履歴窓）。
    距離を測るには **as_of より後** の営業日が要るので、ここでは独立に取る。
    発表日が休日なら、その直後の営業日までの距離にする。
    """

    import bisect

    horizon_end = _add_calendar_days(as_of, 90)
    days = list(calendar)
    seen = set(days)
    for day in repository.trading_days_between(as_of, horizon_end):
        if day not in seen:
            days.append(day)
            seen.add(day)
    if as_of not in seen:
        days.append(as_of)
        days.sort()

    rows = repository.earnings_between(as_of, horizon_end)
    today = bisect.bisect_left(days, as_of)
    if today >= len(days) or days[today] != as_of:
        return {}
    out: dict[str, int] = {}
    for row in rows:
        code = row.get("canonical_code")
        day = str(row.get("announcement_date") or row.get("date") or "")
        if not code or not day:
            continue
        position = bisect.bisect_left(days, day)
        if position >= len(days):
            continue
        distance = position - today
        if distance < 0:
            continue
        out[code] = min(out.get(code, distance), distance)
    return out


def _add_calendar_days(day: str, count: int) -> str:
    from datetime import date, timedelta

    try:
        parsed = date.fromisoformat(day[:10])
    except ValueError:
        return day
    return (parsed + timedelta(days=count)).isoformat()


__all__ = [
    "BAR_LOOKBACK_TRADING_DAYS",
    "RebuildResult",
    "RefreshResult",
    "rebuild_events",
    "refresh_snapshots",
]
