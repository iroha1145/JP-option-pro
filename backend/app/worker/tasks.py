"""Optix Japan worker tasks — JST-scheduled J-Quants sync + radar batch.

Schedule baseline (config/personal.toml [sync], gated on the J-Quants
trading calendar):
- 07:10 calendar+master refresh
- 17:00 post-close batch: bars/indices/margin/shorts/earnings → radar →
  screener cross-section (official daily data lands ~16:30)
- 18:40 financial summary evening pass (disclosures land 18:00)
- 01:10 financial summary late pass (confirmed data ~24:30)
- backfill loop drains bulk CSV history whenever pending
- maintenance every 6h: verified online backups
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.config import get_settings
from app.data_paths import get_data_paths
from app.domain.constants import TOPIX_INDEX_CODE
from app.domain.timeutil import (
    add_days,
    iso_date,
    now_jst,
    parse_hhmm,
    seconds_until_next_jst_time,
    today_jst,
)
from app.personal_config import get_personal_config
from app.providers.jquants.client import JQuantsClient
from app.repositories.core import CoreRepository
from app.services import jquants_sync as sync
from app.services.radar.engine import RadarEngine
from app.services.radar.lifecycle import TERMINAL_STATES
from app.services.screener import build_screener_rows
from app.services.strength_scan import build_strength_rows, compute_market_regime_jp
from app.worker.runtime import TaskResult, TaskSpec

TASK_CALENDAR_MASTER = "calendar_master_sync"
TASK_POST_CLOSE = "post_close_batch"
TASK_FINS_EVENING = "fins_evening_sync"
TASK_FINS_LATE = "fins_late_sync"
TASK_BACKFILL = "history_backfill"
TASK_MAINTENANCE = "maintenance"
TASK_NEWS_SYNC = "news_sync"
TASK_AI_JOBS = "ai_jobs"
TASK_INTRADAY = "intraday_fetch"
TASK_SHORT_MONITOR = "short_monitor_refresh"

# 引け後バッチ時刻に J-Quants がまだ publish していない時の再試行間隔。
POST_CLOSE_RETRY_SECONDS = 20 * 60.0

DEFAULT_TASK_NAMES: tuple[str, ...] = (
    TASK_CALENDAR_MASTER,
    TASK_POST_CLOSE,
    TASK_FINS_EVENING,
    TASK_FINS_LATE,
    TASK_BACKFILL,
    TASK_MAINTENANCE,
    TASK_NEWS_SYNC,
    TASK_AI_JOBS,
    TASK_INTRADAY,
    TASK_SHORT_MONITOR,
)

MANUAL_ACTION_TYPES: tuple[str, ...] = (
    "post_close_batch",
    "master_sync",
    "fins_sync",
    "backfill_step",
    "radar_refresh",
    "news_sync",
    "intraday_fetch",
    "tick_fetch",
    "short_monitor_refresh",
)

_BACKFILL_DATASET_ORDER = (
    sync.DATASET_DAILY_PRICES,
    sync.DATASET_INDEX_PRICES,
    sync.DATASET_FINANCIAL_SUMMARY,
    sync.DATASET_MARGIN_INTEREST,
    sync.DATASET_MARGIN_ALERTS,
    sync.DATASET_SHORT_RATIO,
    sync.DATASET_SHORT_POSITIONS,
)


class TaskContext:
    """Shared lazily-built clients for all task bodies."""

    def __init__(self) -> None:
        self._client: JQuantsClient | None = None
        self.settings = get_settings()
        self.config = get_personal_config()
        self.paths = get_data_paths()
        self.repository = CoreRepository(self.paths.core_db)
        self.repository.initialize()
        # intraday は起動時に必ず初期化（v1→v2 移行含む）: API 側は read_only で
        # 開くだけなので、移行前の旧ファイルを読ませない。
        from app.repositories.intraday_store import IntradayStore

        IntradayStore(self.paths.intraday_db).initialize()

    @property
    def client(self) -> JQuantsClient:
        if self._client is None:
            self._client = JQuantsClient(
                self.settings.JQUANTS_API_KEY.get_secret_value(),
                base_url=self.settings.JQUANTS_BASE_URL,
                max_attempts=self.settings.JQUANTS_MAX_ATTEMPTS,
            )
        return self._client

    @property
    def engine(self) -> sync.JQuantsSyncEngine:
        return sync.JQuantsSyncEngine(
            self.client, self.repository, backfill_years=self.config.sync.backfill_years
        )

    def jquants_ready(self) -> bool:
        return self.settings.jquants_configured()

    def latest_completed_trading_day(self) -> str | None:
        """The trading day whose post-close data should exist right now.

        「引け後」の境界は設定の daily_batch_time_jst に従う。ここを 17 で
        ハードコードすると、バッチ時刻を変えた瞬間に「当日をまだ完了扱いしない
        時刻」とズレて、当日分を一度も取りに行かない or 早すぎて空振りする。
        """

        today = iso_date(today_jst())
        latest = self.repository.latest_trading_day(today)
        if latest == today:
            boundary = parse_hhmm(self.config.sync.daily_batch_time_jst)
            moment = now_jst()
            if moment.hour * 60 + moment.minute < boundary:
                latest = self.repository.latest_trading_day(add_days(today, -1))
        return latest


def _not_configured() -> TaskResult:
    return TaskResult(
        status="skipped", next_delay_seconds=1800.0,
        details={"reason": "jquants_api_key_not_configured"},
    )


def build_default_tasks(context: TaskContext) -> list[TaskSpec]:
    config = context.config

    def calendar_master(_payload: dict[str, Any] | None) -> TaskResult:
        if not context.jquants_ready():
            return _not_configured()
        calendar = context.engine.sync_trading_calendar()
        master = context.engine.sync_security_master()
        failed = [r for r in (calendar, master) if r.get("status") == "error"]
        return TaskResult(
            status="failed" if failed else "completed",
            error_code=(failed[0].get("error_code") if failed else None),
            next_delay_seconds=seconds_until_next_jst_time(("07:10",)),
            details={"calendar": dict(calendar), "master": dict(master)},
        )

    def post_close(payload: dict[str, Any] | None) -> TaskResult:
        if not context.jquants_ready():
            return _not_configured()
        next_delay = seconds_until_next_jst_time((config.sync.daily_batch_time_jst,))
        target = context.latest_completed_trading_day()
        if target is None:
            return TaskResult(
                status="skipped", next_delay_seconds=next_delay,
                details={"reason": "trading_calendar_empty_or_non_trading_day"},
            )
        radar_only = bool(payload and payload.get("__radar_only"))
        results: dict[str, Any] = {"target_date": target}
        if not radar_only:
            steps = (
                ("daily_bars", lambda: context.engine.sync_daily_bars(target)),
                ("index_bars", lambda: context.engine.sync_index_bars(target)),
                ("margin_interest", lambda: context.engine.sync_margin_interest(target)),
                ("margin_alerts", lambda: context.engine.sync_margin_alerts(target)),
                ("short_ratios", lambda: context.engine.sync_short_ratios(target)),
                ("short_positions", lambda: context.engine.sync_short_positions(target)),
                ("earnings_calendar", lambda: context.engine.sync_earnings_calendar()),
            )
            for name, step in steps:
                results[name] = dict(step())
        scan_summary = _run_radar_and_screener(context, target)
        results["radar"] = scan_summary
        # 雷達の後に回す。突破確認と出来高確認を「挤空確認」の条件に使うので、
        # その日の雷達が終わっていないと判定材料が揃わない。
        results["short_monitor"] = _run_short_monitor(context, target)
        failed = [
            name for name, value in results.items()
            if isinstance(value, dict) and value.get("status") == "error"
        ]
        # J-Quants の publish が引け後バッチ時刻に間に合わないことはある。その日を
        # 翌日まで放置すると丸一日古いまま（かつチェックポイントは進めないので
        # 穴にはならない）なので、短い間隔で取りに戻る。
        pending = [
            name for name, value in results.items()
            if isinstance(value, dict) and value.get("status") == "not_published"
        ]
        if pending and not failed:
            next_delay = min(next_delay, POST_CLOSE_RETRY_SECONDS)
        return TaskResult(
            status="failed" if failed else "completed",
            error_code=(f"step_failed:{failed[0]}" if failed else None),
            next_delay_seconds=next_delay,
            details={**results, "pending_publish": pending},
        )

    def fins_evening(_payload: dict[str, Any] | None) -> TaskResult:
        if not context.jquants_ready():
            return _not_configured()
        today = iso_date(today_jst())
        result = context.engine.sync_financial_summaries(today)
        return TaskResult(
            status="failed" if result.get("status") == "error" else "completed",
            error_code=result.get("error_code"),
            next_delay_seconds=seconds_until_next_jst_time((config.sync.fins_evening_time_jst,)),
            details=dict(result),
        )

    def fins_late(_payload: dict[str, Any] | None) -> TaskResult:
        if not context.jquants_ready():
            return _not_configured()
        # 確報補完: 直前の営業日ぶんを再取得して上書きする（冪等）。
        yesterday = context.repository.latest_trading_day(add_days(iso_date(today_jst()), -1))
        details: dict[str, Any] = {}
        status = "completed"
        if yesterday:
            result = context.engine.resync_financial_summaries_for(yesterday)
            details = dict(result)
            if result.get("status") == "error":
                status = "failed"
        return TaskResult(
            status=status,
            error_code=details.get("error_code"),
            next_delay_seconds=seconds_until_next_jst_time((config.sync.fins_late_time_jst,)),
            details=details,
        )

    def backfill(payload: dict[str, Any] | None) -> TaskResult:
        if not context.jquants_ready():
            return _not_configured()
        # 進行中データセットを 1 ステップ（1ファイル）ずつ進める。
        history_from = context.engine.backfill_window_start()
        for dataset in _BACKFILL_DATASET_ORDER:
            state = context.repository.sync_state(dataset)
            checkpoint = (state or {}).get("checkpoint") or {}
            pending = checkpoint.get("bulk_pending")
            # 計画は **それを立てた窓に対してのみ** 完了しうる。`backfill_years`
            # を広げても古い計画が残っていると、`pending=0` が「履歴が揃った」
            # に見えたまま永久に固まる（実際、空売り残高は 10 年分あるうち
            # 2025-06 以降の 35 本で止まっていた）。窓が変わったら立て直す。
            stale_window = checkpoint.get("bulk_history_from") != history_from
            unplanned = pending is None and not checkpoint.get("last_synced_date")
            if unplanned or stale_window:
                plan = context.engine.backfill_plan(dataset)
                if plan.get("status") == "error":
                    return TaskResult(
                        status="failed", error_code=plan.get("error_code"),
                        next_delay_seconds=600.0, details=dict(plan),
                    )
                pending = (context.repository.sync_state(dataset) or {}).get("checkpoint", {}).get("bulk_pending")
            if pending:
                result = context.engine.backfill_step(dataset, max_files=1)
                return TaskResult(
                    status="failed" if result.get("status") == "error" else "completed",
                    error_code=result.get("error_code"),
                    next_delay_seconds=5.0,  # 残りがある限り続ける（限流はクライアント側が守る）
                    details=dict(result),
                )
        return TaskResult(
            status="completed", next_delay_seconds=6 * 3600.0,
            details={"reason": "no_pending_backfill"},
        )

    def maintenance(_payload: dict[str, Any] | None) -> TaskResult:
        from app.tools.sqlite_backup import backup_database

        outcomes: dict[str, Any] = {}
        status = "completed"
        for label, path in (
            ("jp-core", context.paths.core_db),
            ("jp-app", context.paths.app_db),
            ("jp-worker", context.paths.worker_db),
            ("jp-news", context.paths.news_db),
            ("jp-ai-jobs", context.paths.ai_jobs_db),
        ):
            if not path.is_file():
                outcomes[label] = "absent"
                continue
            try:
                result = backup_database(
                    path,
                    context.paths.backups_dir,
                    label=label,
                    keep=context.config.storage.backup_keep,
                )
                outcomes[label] = {"backup": result.backup, "sha256": result.sha256[:16]}
            except Exception as exc:  # noqa: BLE001
                outcomes[label] = f"failed:{type(exc).__name__}"
                status = "failed"
        # Prune the append-only action-request log so it can't grow unbounded.
        try:
            from datetime import datetime, timedelta, timezone

            from app.worker.state import WorkerStateRepository

            if context.paths.worker_db.is_file():
                cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                pruned = WorkerStateRepository(context.paths.worker_db).prune_action_requests(cutoff)
                outcomes["action_requests_pruned"] = pruned
        except Exception as exc:  # noqa: BLE001 — pruning is best-effort
            outcomes["action_requests_pruned"] = f"failed:{type(exc).__name__}"
        return TaskResult(
            status=status,
            error_code=None if status == "completed" else "backup_failed",
            next_delay_seconds=6 * 3600.0,
            details=outcomes,
        )

    def post_close_dispatch(payload: dict[str, Any] | None) -> TaskResult:
        if payload and payload.get("__action_type") == "radar_refresh":
            payload = {**payload, "__radar_only": True}
        return post_close(payload)

    def news_sync_task(_payload: dict[str, Any] | None) -> TaskResult:
        from app.repositories.news_store import NewsStore
        from app.repositories.app_store import AppStore
        from app.services.ai_jobs.store import AIJobStore
        from app.services.news.service import enqueue_ai_jobs, rebuild_entity_catalog, sync_feeds_once
        from app.services.radar.lifecycle import TERMINAL_STATES as RADAR_TERMINAL

        if config.features.news_mode == "off":
            return TaskResult(status="skipped", next_delay_seconds=1800.0, details={"reason": "news_mode_off"})
        store = NewsStore(context.paths.news_db)
        store.initialize()
        rebuild_entity_catalog(context.repository, store)
        watchlist: set[str] = set()
        app_db = AppStore(context.paths.app_db, read_only=True)
        if app_db.exists():
            try:
                watchlist = set(app_db.watchlist_codes())
            except Exception:  # noqa: BLE001 — 自選が読めなくても同期は続行
                watchlist = set()
        radar_codes = {
            event["canonical_code"]
            for event in context.repository.open_radar_events(terminal_states=sorted(RADAR_TERMINAL))
        }
        summary = sync_feeds_once(
            core=context.repository, store=store,
            watchlist_codes=watchlist, radar_codes=radar_codes,
        )
        if config.features.news_mode == "scheduled" and context.settings.openai_configured():
            jobs = AIJobStore(context.paths.ai_jobs_db)
            jobs.initialize()
            summary["ai_enqueue"] = enqueue_ai_jobs(
                store=store, jobs=jobs,
                daily_token_limit=config.ai.daily_token_limit,
                max_items=config.news.max_ai_items_per_run,
            )
        cutoff_days = context.config.storage.news_retention_days
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=cutoff_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        summary["pruned"] = store.prune_older_than(cutoff)
        status, error_code = news_sync_outcome(summary)
        return TaskResult(
            status=status,
            error_code=error_code,
            next_delay_seconds=float(config.news.sync_seconds),
            details=summary,
        )

    def intraday_fetch_task(payload: dict[str, Any] | None) -> TaskResult:
        """手動専用: 指定銘柄の直近分足/ティックをキャッシュ（未契約は正直に記録）。

        payload["dataset"]: "minute"（既定）| "tick" — アクション種別はランタイムが
        payload から剥がすので、データセットは payload 自身で運ぶ。
        """

        from app.repositories.intraday_store import IntradayStore
        from app.services.intraday import (
            FETCH_TRADING_DAYS,
            RETENTION_TRADING_DAYS,
            TICK_RETENTION_TRADING_DAYS,
            fetch_latest_ticks,
            fetch_recent_minutes,
        )
        from app.domain.timeutil import add_days, iso_date, today_jst

        idle = TaskResult(status="completed", next_delay_seconds=6 * 3600.0, details={"reason": "manual_only"})
        code = (payload or {}).get("code")
        if not code:
            return idle
        if not context.jquants_ready():
            return _not_configured()
        dataset = (payload or {}).get("dataset") or "minute"
        store = IntradayStore(context.paths.intraday_db)
        store.initialize()
        if dataset == "tick":
            # ティックの日次 CSV は全市場 50〜70MB。1 銘柄のために毎回落とすのは
            # 高すぎるので、同じ 1 パスで自選＋レーダー中の銘柄も抽出しておく。
            from app.repositories.app_store import AppStore

            extra: set[str] = set()
            app_db = AppStore(context.paths.app_db, read_only=True)
            if app_db.exists():
                try:
                    extra |= set(app_db.watchlist_codes())
                except Exception:  # noqa: BLE001 — 自選が読めなくても本体は続行
                    pass
            extra |= {
                event["canonical_code"]
                for event in context.repository.open_radar_events(
                    terminal_states=sorted(TERMINAL_STATES)
                )
            }
            result = fetch_latest_ticks(
                client=context.client, store=store, core=context.repository,
                canonical_code=str(code), extra_codes=extra,
            )
            store.prune_ticks_older_than(
                add_days(iso_date(today_jst()), -TICK_RETENTION_TRADING_DAYS * 2)
            )
        else:
            result = fetch_recent_minutes(
                client=context.client, store=store, core=context.repository,
                canonical_code=str(code), days=FETCH_TRADING_DAYS,
            )
            store.prune_older_than(add_days(iso_date(today_jst()), -RETENTION_TRADING_DAYS * 2))
        status = (
            "completed"
            if result.get("status") in ("ok", "plan_not_included", "not_published")
            else "failed"
        )
        return TaskResult(
            status=status,
            error_code=result.get("error_code"),
            next_delay_seconds=6 * 3600.0,
            details={"code": code, "dataset": dataset, **result},
        )

    def ai_jobs_task(_payload: dict[str, Any] | None) -> TaskResult:
        from app.repositories.news_store import NewsStore
        from app.services.ai_jobs.runtime import OpenAIRuntime
        from app.services.ai_jobs.store import AIJobStore
        from app.services.news.service import process_ai_jobs_once

        if config.features.news_mode != "scheduled":
            return TaskResult(status="skipped", next_delay_seconds=1800.0, details={"reason": "news_mode_not_scheduled"})
        if not context.settings.openai_configured():
            return TaskResult(status="skipped", next_delay_seconds=1800.0, details={"reason": "openai_api_key_not_configured"})
        jobs = AIJobStore(context.paths.ai_jobs_db)
        jobs.initialize()
        store = NewsStore(context.paths.news_db)
        store.initialize()
        runtime = OpenAIRuntime(context.settings.OPENAI_API_KEY.get_secret_value())
        outcome = process_ai_jobs_once(store=store, jobs=jobs, runtime=runtime)
        busy = outcome.get("submitted") or outcome.get("pending")
        return TaskResult(
            status="completed",
            next_delay_seconds=5.0 if busy else 30.0,
            details={**outcome, "queue": jobs.status_counts()},
        )

    def short_monitor_task(payload: dict[str, Any] | None) -> TaskResult:
        """手動更新の受け口。**定時では走らない。**

        再構築は引け後バッチの中で雷達の後に走る。ここでも定時に走らせると、
        単一ライターの SQLite を 9 分ぶん取り合って両方が `database is locked`
        で落ちる（実際そうなった）。定時のティックは何もせず、手動の
        `short_monitor_refresh` が来たときだけ同じ関数を呼ぶ。
        """

        if not payload:
            return TaskResult(
                status="completed", next_delay_seconds=6 * 3600.0,
                details={"reason": "runs_inside_post_close_batch"},
            )
        target = context.latest_completed_trading_day()
        if target is None:
            return TaskResult(
                status="skipped", next_delay_seconds=6 * 3600.0,
                details={"reason": "trading_calendar_empty_or_non_trading_day"},
            )
        result = _run_short_monitor(context, target)
        if result.get("status") == "busy":
            # 書き込みロックの取り合いは「壊れている」ではない。少し待って戻る。
            return TaskResult(
                status="skipped", next_delay_seconds=300.0, details=result,
            )
        return TaskResult(
            status="failed" if result.get("status") == "error" else "completed",
            error_code=result.get("error_code"),
            next_delay_seconds=6 * 3600.0,
            details=result,
        )

    return [
        TaskSpec(
            name=TASK_CALENDAR_MASTER,
            run=calendar_master,
            initial_delay_seconds=5.0,
            action_types=("master_sync",),
        ),
        TaskSpec(
            name=TASK_POST_CLOSE,
            run=post_close_dispatch,
            initial_delay_seconds=20.0,
            action_types=("post_close_batch", "radar_refresh"),
        ),
        TaskSpec(
            name=TASK_FINS_EVENING,
            run=fins_evening,
            initial_delay_seconds=40.0,
            action_types=("fins_sync",),
        ),
        TaskSpec(name=TASK_FINS_LATE, run=fins_late, initial_delay_seconds=90.0),
        TaskSpec(
            name=TASK_BACKFILL,
            run=backfill,
            initial_delay_seconds=15.0,
            failure_backoff_seconds=120.0,
            action_types=("backfill_step",),
        ),
        TaskSpec(name=TASK_MAINTENANCE, run=maintenance, initial_delay_seconds=300.0),
        TaskSpec(
            name=TASK_NEWS_SYNC,
            run=news_sync_task,
            initial_delay_seconds=45.0,
            action_types=("news_sync",),
        ),
        TaskSpec(name=TASK_AI_JOBS, run=ai_jobs_task, initial_delay_seconds=60.0),
        TaskSpec(
            name=TASK_INTRADAY,
            run=intraday_fetch_task,
            initial_delay_seconds=120.0,
            action_types=("intraday_fetch", "tick_fetch"),
        ),
        # 手動更新は引け後バッチと **同じ関数** を呼ぶ。別経路を作ると
        # 「手で押したときだけ結果が違う」が起きる。
        TaskSpec(
            name=TASK_SHORT_MONITOR,
            run=short_monitor_task,
            initial_delay_seconds=180.0,
            action_types=("short_monitor_refresh",),
        ),
    ]


def news_sync_outcome(summary: dict[str, Any]) -> tuple[str, str | None]:
    """全フィードが失敗した同期は completed にしない（健全性をごまかさない）。"""

    errors = summary.get("feed_errors") or {}
    feeds = int(summary.get("feeds") or 0)
    if feeds > 0 and len(errors) >= feeds:
        return "failed", "all_feeds_failed"
    return "completed", None


#: 突破が確認済みと呼べる雷達状態。挤空確認の「価格突破」条件に使う。
_RADAR_BREAKOUT_STATES = frozenset({
    "confirmed", "holding", "retest_held", "reaccelerating", "extended",
})


def _radar_confirmations(context: TaskContext) -> dict[str, dict[str, bool]]:
    """雷達の突破確認と出来高確認を、銘柄ごとの真偽に落とす。

    空売り側で価格を再判定しない —— 突破の定義は 1 か所（雷達）に置く。
    """

    out: dict[str, dict[str, bool]] = {}
    for event in context.repository.open_radar_events(terminal_states=sorted(TERMINAL_STATES)):
        code = event.get("canonical_code")
        if not code:
            continue
        breakout = str(event.get("state") or "") in _RADAR_BREAKOUT_STATES
        scores = event.get("scores") or {}
        confirmation = scores.get("breakout_confirmation") or {}
        turnover = confirmation.get("score") if isinstance(confirmation, dict) else None
        current = out.setdefault(code, {"breakout": False, "turnover": False})
        current["breakout"] = current["breakout"] or breakout
        current["turnover"] = current["turnover"] or bool(turnover is not None and turnover >= 60.0)
    return out


def _count_news_by_code(items: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """ニュース記事列 → {銘柄: 件数}。1 記事が複数銘柄に紐づけば各銘柄に 1 ずつ。"""

    counts: dict[str, int] = {}
    for item in items:
        codes = item.get("securities") or []
        if not isinstance(codes, (list, tuple, set)):
            continue
        for code in set(str(c) for c in codes if c):
            counts[code] = counts.get(code, 0) + 1
    return counts


def _news_counts_5d(context: TaskContext, target_date: str) -> tuple[dict[str, int], bool]:
    """直近 5 営業日のニュース件数（銘柄別）と「ニュース源があるか」。

    以前はスナップショットに渡していなかったので、`news_catalyst` は本番で
    一度も立たず、催化剂は決算距離だけになっていた。ニュースが無い・読めない
    ときは `has_news_feed=False` を返す —— 「無い」を「0 件」と偽らない。
    """

    if context.config.features.news_mode == "off" or not context.paths.news_db.exists():
        return {}, False
    try:
        from app.repositories.news_store import NewsStore

        window = context.repository.trading_days_between(add_days(target_date, -14), target_date)
        since_day = window[-5] if len(window) >= 5 else (window[0] if window else target_date)
        store = NewsStore(context.paths.news_db, read_only=True)
        items = store.recent_items(since_iso=f"{since_day}T00:00:00Z", limit=5000)
    except Exception:  # noqa: BLE001 - ニュースが読めなくても空売りは止めない
        return {}, False
    return _count_news_by_code(items), True


def _run_short_monitor(context: TaskContext, target_date: str) -> dict[str, Any]:
    """機関空売り行動モニターの再構築 + 当日スナップショット。

    1 銘柄の異常で全市場を止めない。失敗したら前回の有効なスナップショットを
    そのまま残す（消さない）。
    """

    from app.services.short_monitor import pipeline as short_monitor

    if not context.repository.latest_short_position_date():
        return {"status": "skipped", "reason": "no_short_position_data"}
    try:
        news_counts, has_news_feed = _news_counts_5d(context, target_date)
        rebuilt = short_monitor.rebuild_events(context.repository)
        refreshed = short_monitor.refresh_snapshots(
            context.repository,
            as_of_date=target_date,
            radar_confirmations=_radar_confirmations(context),
            news_counts=news_counts,
            has_news_feed=has_news_feed,
        )
    except Exception as exc:  # noqa: BLE001 - 全市場バッチを 1 件で落とさない
        message = str(exc)
        # 単一ライターの SQLite でロックがぶつかるのは想定内。障害ではない。
        if "locked" in message or "busy" in message:
            return {"status": "busy", "message": message[:200]}
        return {"status": "error", "error_code": type(exc).__name__, "message": message[:200]}

    context.repository.record_sync_success(
        "short_behavior",
        rows_total=refreshed.snapshots,
        data_through=refreshed.as_of_date,
    )
    return {"status": "ok", "rebuild": rebuilt.as_dict(), "refresh": refreshed.as_dict()}


def _run_radar_and_screener(context: TaskContext, target_date: str) -> dict[str, Any]:
    if not context.config.features.radar_enabled:
        return {"status": "disabled"}
    if context.repository.latest_bar_date() != target_date:
        return {"status": "skipped", "reason": "bars_not_current", "target_date": target_date}
    lookback_start = add_days(target_date, -context.config.radar.lookback_days * 2)
    engine = RadarEngine(context.repository, context.config.radar)
    summary = engine.scan(target_date, lookback_start=lookback_start)
    features_by_code = summary.pop("features_by_code")
    structure_by_code = summary.pop("structure_by_code")
    sector_median_returns = summary.pop("sector_median_returns")
    sector_median_returns_63d = summary.pop("sector_median_returns_63d", {})
    regulation_map = summary.pop("regulation_map", {})
    rs_context = summary.pop("rs_context")

    securities = {
        row["canonical_code"]: row
        for row in context.repository.list_securities(active_only=True)
    }
    open_events = context.repository.open_radar_events(
        terminal_states=sorted(TERMINAL_STATES)
    )
    radar_state_by_code = {event["canonical_code"]: event["state"] for event in open_events}
    rows = build_screener_rows(
        trade_date=target_date,
        features_by_code=features_by_code,
        securities=securities,
        sector_median_returns=sector_median_returns,
        sector_median_returns_63d=sector_median_returns_63d,
        topix_return_63d=rs_context.get("topix_return_63d"),
        margin_map=context.repository.latest_margin_map(),
        radar_state_by_code=radar_state_by_code,
        regulation_map=regulation_map,
    )
    written = context.repository.replace_screener_rows(rows)
    context.repository.record_sync_success(
        "radar_scan", rows_total=summary.get("events_written"), data_through=target_date
    )
    context.repository.record_sync_success(
        "screener_snapshot", rows_total=written, data_through=target_date
    )
    summary["screener_rows"] = written

    # 強度スキャン断面: 同じ features / 構造分析から intrinsic を全量確定。
    topix_series = context.repository.index_series(
        TOPIX_INDEX_CODE, start_date=lookback_start
    )
    market_codes = {
        code: (securities.get(code) or {}).get("market_code") or ""
        for code in features_by_code
    }
    regime = compute_market_regime_jp(topix_series, features_by_code, market_codes)
    strength_rows = build_strength_rows(
        trade_date=target_date,
        features_by_code=features_by_code,
        structure_by_code=structure_by_code,
        securities=securities,
        topix_return_63d=rs_context.get("topix_return_63d"),
        regulation_map=regulation_map,
    )
    strength_written = context.repository.replace_strength_rows(
        strength_rows, trade_date=target_date, regime=regime
    )
    context.repository.record_sync_success(
        "strength_snapshot", rows_total=strength_written, data_through=target_date
    )
    summary["strength_rows"] = strength_written
    summary["status"] = "ok"
    return summary


__all__ = [
    "DEFAULT_TASK_NAMES",
    "MANUAL_ACTION_TYPES",
    "TaskContext",
    "build_default_tasks",
    "news_sync_outcome",
]
