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

from typing import Any

from app.config import get_settings
from app.data_paths import get_data_paths
from app.domain.timeutil import add_days, iso_date, now_jst, seconds_until_next_jst_time, today_jst
from app.personal_config import get_personal_config
from app.providers.jquants.client import JQuantsClient
from app.repositories.core import CoreRepository
from app.services import jquants_sync as sync
from app.services.radar.engine import RadarEngine
from app.services.radar.lifecycle import TERMINAL_STATES
from app.services.screener import build_screener_rows
from app.worker.runtime import TaskResult, TaskSpec

TASK_CALENDAR_MASTER = "calendar_master_sync"
TASK_POST_CLOSE = "post_close_batch"
TASK_FINS_EVENING = "fins_evening_sync"
TASK_FINS_LATE = "fins_late_sync"
TASK_BACKFILL = "history_backfill"
TASK_MAINTENANCE = "maintenance"

DEFAULT_TASK_NAMES: tuple[str, ...] = (
    TASK_CALENDAR_MASTER,
    TASK_POST_CLOSE,
    TASK_FINS_EVENING,
    TASK_FINS_LATE,
    TASK_BACKFILL,
    TASK_MAINTENANCE,
)

MANUAL_ACTION_TYPES: tuple[str, ...] = (
    "post_close_batch",
    "master_sync",
    "fins_sync",
    "backfill_step",
    "radar_refresh",
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
        """The trading day whose post-close data should exist right now."""

        today = iso_date(today_jst())
        latest = self.repository.latest_trading_day(today)
        if latest == today and now_jst().hour < 17:
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
        failed = [
            name for name, value in results.items()
            if isinstance(value, dict) and value.get("status") == "error"
        ]
        return TaskResult(
            status="failed" if failed else "completed",
            error_code=(f"step_failed:{failed[0]}" if failed else None),
            next_delay_seconds=next_delay,
            details=results,
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
        for dataset in _BACKFILL_DATASET_ORDER:
            state = context.repository.sync_state(dataset)
            checkpoint = (state or {}).get("checkpoint") or {}
            pending = checkpoint.get("bulk_pending")
            if pending is None and not checkpoint.get("last_synced_date"):
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
    ]


def _run_radar_and_screener(context: TaskContext, target_date: str) -> dict[str, Any]:
    if not context.config.features.radar_enabled:
        return {"status": "disabled"}
    if context.repository.latest_bar_date() != target_date:
        return {"status": "skipped", "reason": "bars_not_current", "target_date": target_date}
    lookback_start = add_days(target_date, -context.config.radar.lookback_days * 2)
    engine = RadarEngine(context.repository, context.config.radar)
    summary = engine.scan(target_date, lookback_start=lookback_start)
    features_by_code = summary.pop("features_by_code")
    sector_median_returns = summary.pop("sector_median_returns")
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
        topix_return_63d=rs_context.get("topix_return_63d"),
        margin_map=context.repository.latest_margin_map(),
        radar_state_by_code=radar_state_by_code,
    )
    written = context.repository.replace_screener_rows(rows)
    context.repository.record_sync_success(
        "radar_scan", rows_total=summary.get("events_written"), data_through=target_date
    )
    context.repository.record_sync_success(
        "screener_snapshot", rows_total=written, data_through=target_date
    )
    summary["screener_rows"] = written
    summary["status"] = "ok"
    return summary


__all__ = [
    "DEFAULT_TASK_NAMES",
    "MANUAL_ACTION_TYPES",
    "TaskContext",
    "build_default_tasks",
]
