"""J-Quants → jp-core.db sync engine.

Two lanes, never blocking each other:
- **Incremental** — per-dataset "sync up to the latest completed trading
  day", checkpointed on the last fully ingested date; re-running any date is
  idempotent.
- **Backfill** — historical import through the bulk CSV endpoints, one file
  per step, resumable via a pending-keys checkpoint. A crashed backfill
  continues from the next file, never from zero.

Failures record an error code in sync_state and leave every previously
ingested row untouched. Empty responses never overwrite existing data.
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from app.domain.constants import INDEX_CODES, TOPIX_INDEX_CODE
from app.domain.timeutil import add_days, iso_date, today_jst
from app.providers.jquants import mapping
from app.providers.jquants.client import JQuantsClient
from app.providers.jquants.errors import JQuantsError, JQuantsPlanError
from app.repositories.core import CoreRepository

DATASET_TRADING_CALENDAR = "trading_calendar"
DATASET_SECURITY_MASTER = "security_master"
DATASET_DAILY_PRICES = "daily_prices"
DATASET_INDEX_PRICES = "index_prices"
DATASET_TOPIX_PRICES = "topix_prices"
DATASET_FINANCIAL_SUMMARY = "financial_summary"
DATASET_EARNINGS_CALENDAR = "earnings_calendar"
DATASET_MARGIN_INTEREST = "margin_interest"
DATASET_MARGIN_ALERTS = "margin_alerts"
DATASET_SHORT_RATIO = "short_sale_ratio"
DATASET_SHORT_POSITIONS = "reported_short_positions"

ALL_DATASETS = (
    DATASET_TRADING_CALENDAR,
    DATASET_SECURITY_MASTER,
    DATASET_DAILY_PRICES,
    DATASET_INDEX_PRICES,
    DATASET_FINANCIAL_SUMMARY,
    DATASET_EARNINGS_CALENDAR,
    DATASET_MARGIN_INTEREST,
    DATASET_MARGIN_ALERTS,
    DATASET_SHORT_RATIO,
    DATASET_SHORT_POSITIONS,
)

# Incremental catch-up guard: a fresh deployment must run the backfill lane,
# not iterate thousands of per-date requests.
MAX_INCREMENTAL_DAYS = 45
_BULK_BACKFILL_ENDPOINTS = {
    DATASET_DAILY_PRICES: "/equities/bars/daily",
    DATASET_INDEX_PRICES: "/indices/bars/daily",
    DATASET_FINANCIAL_SUMMARY: "/fins/summary",
    DATASET_MARGIN_INTEREST: "/markets/margin-interest",
    DATASET_MARGIN_ALERTS: "/markets/margin-alert",
    DATASET_SHORT_RATIO: "/markets/short-ratio",
    DATASET_SHORT_POSITIONS: "/markets/short-sale-report",
}


def _bulk_file_date(key: str) -> str | None:
    """`.../markets_short-sale-report_20260803.csv.gz` → `2026-08-03`。

    月次ファイル（`..._202607.csv.gz`）は日次の対象外なので None を返す。
    """

    stem = key.rsplit("/", 1)[-1].split(".", 1)[0]
    digits = stem.rsplit("_", 1)[-1]
    if len(digits) != 8 or not digits.isdigit():
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"


class SyncResult(dict):
    """Plain dict subclass so task status JSON stays trivially serializable."""

    @property
    def rows(self) -> int:
        return int(self.get("rows") or 0)


class JQuantsSyncEngine:
    def __init__(
        self,
        client: JQuantsClient,
        repository: CoreRepository,
        *,
        backfill_years: int = 10,
    ) -> None:
        self._client = client
        self._repository = repository
        self._backfill_years = max(1, min(10, int(backfill_years)))

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _run_dataset(
        self, dataset: str, work: Callable[[], SyncResult]
    ) -> SyncResult:
        self._repository.record_sync_attempt(dataset)
        try:
            result = work()
        except JQuantsError as exc:
            self._repository.record_sync_error(dataset, exc.code)
            return SyncResult(dataset=dataset, status="error", error_code=exc.code)
        except Exception as exc:  # noqa: BLE001 — sync loop must not die silently
            code = f"unexpected:{type(exc).__name__}"
            self._repository.record_sync_error(dataset, code)
            return SyncResult(dataset=dataset, status="error", error_code=code)
        return result

    def _checkpoint(self, dataset: str) -> dict[str, Any]:
        state = self._repository.sync_state(dataset)
        return dict(state.get("checkpoint") or {}) if state else {}

    def _history_start_date(self) -> str:
        today = today_jst()
        target_year = today.year - self._backfill_years
        try:
            return iso_date(today.replace(year=target_year))
        except ValueError:
            # today is Feb 29 and target_year is not a leap year: clamp to Feb 28
            # rather than raising and failing the whole calendar/backfill/TOPIX sync.
            return iso_date(today.replace(year=target_year, day=28))

    # ------------------------------------------------------------------
    # trading calendar & master
    # ------------------------------------------------------------------

    def sync_trading_calendar(self) -> SyncResult:
        def work() -> SyncResult:
            start = self._history_start_date()
            end = add_days(iso_date(today_jst()), 370)
            rows = [
                mapped
                for row in self._client.fetch_rows("/markets/calendar", {"from": start, "to": end})
                if (mapped := mapping.map_trading_day(row))
            ]
            count = self._repository.upsert_trading_days(rows)
            data_through = max((row["calendar_date"] for row in rows), default=None)
            self._repository.record_sync_success(
                DATASET_TRADING_CALENDAR,
                checkpoint={"from": start, "to": end},
                rows_total=count,
                data_through=data_through,
            )
            return SyncResult(dataset=DATASET_TRADING_CALENDAR, status="ok", rows=count)

        return self._run_dataset(DATASET_TRADING_CALENDAR, work)

    def sync_security_master(self) -> SyncResult:
        def work() -> SyncResult:
            today = iso_date(today_jst())
            rows = [
                mapped
                for row in self._client.fetch_rows("/equities/master")
                if (mapped := mapping.map_security_master(row))
            ]
            if not rows:
                # An empty master would deactivate the entire universe;
                # treat it as a failure instead of destroying state.
                raise JQuantsError("empty security master response", code="jquants_empty_master")
            outcome = self._repository.replace_security_master(rows, as_of_date=today)
            self._repository.record_sync_success(
                DATASET_SECURITY_MASTER,
                checkpoint={"as_of_date": today},
                rows_total=outcome["upserted"],
                data_through=today,
            )
            return SyncResult(
                dataset=DATASET_SECURITY_MASTER, status="ok",
                rows=outcome["upserted"], deactivated=outcome["deactivated"],
            )

        return self._run_dataset(DATASET_SECURITY_MASTER, work)

    # ------------------------------------------------------------------
    # date-driven incremental datasets
    # ------------------------------------------------------------------

    def _pending_trading_days(self, dataset: str, target_date: str) -> list[str]:
        checkpoint = self._checkpoint(dataset)
        last = checkpoint.get("last_synced_date")
        if not last:
            return []
        start = add_days(last, 1)
        if start > target_date:
            return []
        days = self._repository.trading_days_between(start, target_date)
        return days[:MAX_INCREMENTAL_DAYS]

    def sync_daily_bars(self, target_date: str) -> SyncResult:
        def work() -> SyncResult:
            checkpoint = self._checkpoint(DATASET_DAILY_PRICES)
            if not checkpoint.get("last_synced_date"):
                return SyncResult(
                    dataset=DATASET_DAILY_PRICES, status="backfill_required", rows=0
                )
            total = 0
            synced_through = checkpoint.get("last_synced_date")
            for day in self._pending_trading_days(DATASET_DAILY_PRICES, target_date):
                rows = [
                    mapped
                    for row in self._client.fetch_rows("/equities/bars/daily", {"date": day})
                    if (mapped := mapping.map_daily_bar(row))
                ]
                if not rows:
                    # 営業日なのに 0 行 = J-Quants がまだ publish していない。
                    # ここでチェックポイントを進めると次回は last+1 から探すため、
                    # その日は二度と取得されず恒久的な穴になる。進めずに抜けて
                    # 「未着」を宣言し、呼び出し側に短い間隔で再試行させる。
                    return SyncResult(
                        dataset=DATASET_DAILY_PRICES,
                        status="not_published",
                        rows=total,
                        data_through=synced_through,
                    )
                total += self._repository.upsert_daily_bars(rows)
                synced_through = day
                self._repository.record_sync_success(
                    DATASET_DAILY_PRICES,
                    checkpoint={"last_synced_date": day},
                    rows_total=total,
                    data_through=day,
                )
            return SyncResult(
                dataset=DATASET_DAILY_PRICES, status="ok", rows=total, data_through=synced_through
            )

        return self._run_dataset(DATASET_DAILY_PRICES, work)

    def sync_index_bars(self, target_date: str) -> SyncResult:
        def work() -> SyncResult:
            checkpoint = self._checkpoint(DATASET_INDEX_PRICES)
            if not checkpoint.get("last_synced_date"):
                return SyncResult(dataset=DATASET_INDEX_PRICES, status="backfill_required", rows=0)
            total = 0
            synced_through = checkpoint.get("last_synced_date")
            for day in self._pending_trading_days(DATASET_INDEX_PRICES, target_date):
                rows = [
                    mapped
                    for row in self._client.fetch_rows("/indices/bars/daily", {"date": day})
                    if (mapped := mapping.map_index_bar(row))
                ]
                if not rows:
                    # 日足と同じ規律: 未 publish の日でチェックポイントを進めない
                    # （進めるとその営業日は恒久的に欠測になる）。
                    return SyncResult(
                        dataset=DATASET_INDEX_PRICES,
                        status="not_published",
                        rows=total,
                        data_through=synced_through,
                    )
                total += self._repository.upsert_index_bars(rows)
                synced_through = day
                self._repository.record_sync_success(
                    DATASET_INDEX_PRICES,
                    checkpoint={"last_synced_date": day},
                    rows_total=total,
                    data_through=day,
                )
            return SyncResult(
                dataset=DATASET_INDEX_PRICES, status="ok", rows=total, data_through=synced_through
            )

        return self._run_dataset(DATASET_INDEX_PRICES, work)

    def sync_financial_summaries(self, target_date: str) -> SyncResult:
        """Disclosures are fetched per calendar date (not trading date):
        TDnet occasionally publishes on non-trading days."""

        def work() -> SyncResult:
            checkpoint = self._checkpoint(DATASET_FINANCIAL_SUMMARY)
            last = checkpoint.get("last_synced_date")
            if not last:
                return SyncResult(
                    dataset=DATASET_FINANCIAL_SUMMARY, status="backfill_required", rows=0
                )
            total = 0
            day = add_days(last, 1)
            steps = 0
            synced_through = last
            while day <= target_date and steps < MAX_INCREMENTAL_DAYS:
                rows = [
                    mapped
                    for row in self._client.fetch_rows("/fins/summary", {"date": day})
                    if (mapped := mapping.map_financial_summary(row))
                ]
                total += self._repository.upsert_financial_summaries(rows)
                synced_through = day
                self._repository.record_sync_success(
                    DATASET_FINANCIAL_SUMMARY,
                    checkpoint={"last_synced_date": day},
                    rows_total=total,
                    data_through=day,
                )
                day = add_days(day, 1)
                steps += 1
            return SyncResult(
                dataset=DATASET_FINANCIAL_SUMMARY, status="ok", rows=total,
                data_through=synced_through,
            )

        return self._run_dataset(DATASET_FINANCIAL_SUMMARY, work)

    def resync_financial_summaries_for(self, date: str) -> SyncResult:
        """Late-confirmation pass: re-pull one disclosure date (確報 ~24:30 JST)."""

        def work() -> SyncResult:
            rows = [
                mapped
                for row in self._client.fetch_rows("/fins/summary", {"date": date})
                if (mapped := mapping.map_financial_summary(row))
            ]
            count = self._repository.upsert_financial_summaries(rows)
            self._repository.record_sync_success(DATASET_FINANCIAL_SUMMARY, rows_total=count)
            return SyncResult(dataset=DATASET_FINANCIAL_SUMMARY, status="ok", rows=count)

        return self._run_dataset(DATASET_FINANCIAL_SUMMARY, work)

    def sync_earnings_calendar(self) -> SyncResult:
        def work() -> SyncResult:
            rows = [
                mapped
                for row in self._client.fetch_rows("/equities/earnings-calendar")
                if (mapped := mapping.map_earnings_announcement(row))
            ]
            if not rows:
                # 空の 200 で replace_* すると全件 DELETE になる。
                # モジュール不変条件「empty never overwrites」に従い失敗扱い。
                raise JQuantsError(
                    "empty earnings calendar response", code="jquants_empty_earnings"
                )
            count = self._repository.replace_earnings_announcements(rows)
            self._repository.record_sync_success(
                DATASET_EARNINGS_CALENDAR, rows_total=count, data_through=iso_date(today_jst())
            )
            return SyncResult(dataset=DATASET_EARNINGS_CALENDAR, status="ok", rows=count)

        return self._run_dataset(DATASET_EARNINGS_CALENDAR, work)

    def _sync_calendar_dated(
        self,
        dataset: str,
        path: str,
        mapper: Callable[[Mapping[str, Any]], dict[str, Any] | None],
        writer: Callable[[Iterable[Mapping[str, Any]]], int],
        target_date: str,
    ) -> SyncResult:
        """Shared loop for margin-alert / margin-interest / short-ratio style
        endpoints where ``date`` walks calendar dates and empty days are
        cheap no-ops."""

        checkpoint = self._checkpoint(dataset)
        last = checkpoint.get("last_synced_date")
        if not last:
            return SyncResult(dataset=dataset, status="backfill_required", rows=0)
        total = 0
        day = add_days(last, 1)
        steps = 0
        synced_through = last
        while day <= target_date and steps < MAX_INCREMENTAL_DAYS:
            rows = [
                mapped
                for row in self._client.fetch_rows(path, {"date": day})
                if (mapped := mapper(row))
            ]
            total += writer(rows)
            synced_through = day
            self._repository.record_sync_success(
                dataset,
                checkpoint={"last_synced_date": day},
                rows_total=total,
                data_through=day,
            )
            day = add_days(day, 1)
            steps += 1
        return SyncResult(dataset=dataset, status="ok", rows=total, data_through=synced_through)

    def sync_margin_interest(self, target_date: str) -> SyncResult:
        return self._run_dataset(
            DATASET_MARGIN_INTEREST,
            lambda: self._sync_calendar_dated(
                DATASET_MARGIN_INTEREST,
                "/markets/margin-interest",
                mapping.map_margin_interest,
                self._repository.upsert_margin_interest,
                target_date,
            ),
        )

    def sync_margin_alerts(self, target_date: str) -> SyncResult:
        return self._run_dataset(
            DATASET_MARGIN_ALERTS,
            lambda: self._sync_calendar_dated(
                DATASET_MARGIN_ALERTS,
                "/markets/margin-alert",
                mapping.map_margin_alert,
                self._repository.upsert_margin_alerts,
                target_date,
            ),
        )

    def sync_short_ratios(self, target_date: str) -> SyncResult:
        return self._run_dataset(
            DATASET_SHORT_RATIO,
            lambda: self._sync_calendar_dated(
                DATASET_SHORT_RATIO,
                "/markets/short-ratio",
                mapping.map_short_ratio,
                self._repository.upsert_short_ratios,
                target_date,
            ),
        )

    def sync_short_positions(self, target_date: str) -> SyncResult:
        """空売り残高の日次取り込み。

        **REST の `/markets/short-sale-report` は `code` 必須**で、日付範囲だけの
        問い合わせは 400 を返す（`disc_date_from`/`disc_date_to`、`from`/`to`、
        `disclosed_date` いずれも実測で 400。`code` を付けた瞬間に 200）。
        全銘柄を code ごとに回すのは現実的でないので、バックフィルと同じ
        **一括配信の日次ファイル**を使う。

        以前はここで日付範囲の REST を叩いており、増分取り込みは一度も
        成立していなかった（データは全て bulk 回填由来）。しかも
        `start > target_date` の分岐が「取りに行かずに ok」を返すため、
        取り込めていない日が続いても同期状態は成功のまま見えていた。
        """

        def work() -> SyncResult:
            checkpoint = self._checkpoint(DATASET_SHORT_POSITIONS)
            last = checkpoint.get("last_synced_date")
            if not last:
                return SyncResult(dataset=DATASET_SHORT_POSITIONS, status="backfill_required", rows=0)
            start = add_days(last, 1)
            if start > target_date:
                # 取りに行っていないことを "ok" と呼ばない。何もしていない日は
                # そう名乗る（取り込みが壊れていても成功に見える、を防ぐ）。
                return SyncResult(
                    dataset=DATASET_SHORT_POSITIONS, status="up_to_date", rows=0,
                    data_through=last,
                )

            endpoint = _BULK_BACKFILL_ENDPOINTS[DATASET_SHORT_POSITIONS]
            files = self._client.bulk_list(endpoint=endpoint, date_from=start)
            keys = sorted(str(item.get("Key")) for item in files if item.get("Key"))
            # 一括ファイル名の末尾は YYYYMMDD。開始日より前のものは捨てる。
            wanted = [key for key in keys if _bulk_file_date(key) and start <= _bulk_file_date(key) <= target_date]
            if not wanted:
                return SyncResult(
                    dataset=DATASET_SHORT_POSITIONS, status="not_published", rows=0,
                    data_through=last,
                )

            total = 0
            latest_date = last
            for key in wanted:
                handle = self._client.bulk_download_csv(key)
                batch: list[dict[str, Any]] = []
                for raw in csv.DictReader(handle):
                    mapped = mapping.map_short_position(raw)
                    if mapped is not None:
                        batch.append(mapped)
                    if len(batch) >= 20000:
                        total += self._repository.upsert_short_positions(batch)
                        batch = []
                if batch:
                    total += self._repository.upsert_short_positions(batch)
                latest_date = max(latest_date, _bulk_file_date(key) or last)

            self._repository.record_sync_success(
                DATASET_SHORT_POSITIONS,
                checkpoint={"last_synced_date": latest_date},
                rows_total=total,
                data_through=latest_date,
            )
            return SyncResult(
                dataset=DATASET_SHORT_POSITIONS, status="ok", rows=total,
                data_through=latest_date, files=len(wanted),
            )

        return self._run_dataset(DATASET_SHORT_POSITIONS, work)

    # ------------------------------------------------------------------
    # bulk backfill lane
    # ------------------------------------------------------------------

    _BULK_MAPPERS: dict[str, tuple[Callable[[Mapping[str, Any]], dict[str, Any] | None], str]] = {}

    def _bulk_writer(self, dataset: str) -> tuple[Callable[[Mapping[str, Any]], dict[str, Any] | None], Callable[[Iterable[Mapping[str, Any]]], int]]:
        writers = {
            DATASET_DAILY_PRICES: (mapping.map_daily_bar, self._repository.upsert_daily_bars),
            DATASET_INDEX_PRICES: (mapping.map_index_bar, self._repository.upsert_index_bars),
            DATASET_FINANCIAL_SUMMARY: (
                mapping.map_financial_summary, self._repository.upsert_financial_summaries,
            ),
            DATASET_MARGIN_INTEREST: (
                mapping.map_margin_interest, self._repository.upsert_margin_interest,
            ),
            DATASET_MARGIN_ALERTS: (mapping.map_margin_alert, self._repository.upsert_margin_alerts),
            DATASET_SHORT_RATIO: (mapping.map_short_ratio, self._repository.upsert_short_ratios),
            DATASET_SHORT_POSITIONS: (
                mapping.map_short_position, self._repository.upsert_short_positions,
            ),
        }
        return writers[dataset]

    def backfill_window_start(self) -> str:
        """回填計画の窓の先頭。**月初に丸める**。

        アーカイブの履歴ファイルは月次（`..._202001.csv.gz`）なので、計画を
        識別する自然な粒度は月。日付のままだと窓の文字列が毎日変わり、
        「窓が変わったら立て直す」が毎日の立て直しになってしまう。
        """

        return self._history_start_date()[:7] + "-01"

    def backfill_plan(self, dataset: str) -> SyncResult:
        """List bulk files and persist them as the pending work queue.

        計画には **どの窓に対して立てたか**（`bulk_history_from`）を必ず残す。
        `pending == 0` は「その窓の中では全部取り込んだ」でしかなく、
        「履歴が揃った」ではない —— 窓が広がれば計画ごと立て直す必要がある。
        実際、`backfill_years` を 1 から 10 に広げた後も空売り残高・空売り
        比率・信用余額は 2025-06 起点の古い計画のまま `pending=0` を返し続け、
        10 年分あるアーカイブのうち 35 本しか取り込めていなかった。
        """

        endpoint = _BULK_BACKFILL_ENDPOINTS.get(dataset)
        if endpoint is None:
            return SyncResult(dataset=dataset, status="not_bulk", rows=0)

        def work() -> SyncResult:
            start = self.backfill_window_start()
            files = self._client.bulk_list(endpoint=endpoint, date_from=start)
            keys = sorted(str(item.get("Key")) for item in files if item.get("Key"))
            checkpoint = self._checkpoint(dataset)
            done = set(checkpoint.get("bulk_done") or [])
            pending = [key for key in keys if key not in done]
            self._repository.record_sync_success(
                dataset,
                checkpoint={
                    "bulk_pending": pending,
                    "bulk_done": sorted(done),
                    "bulk_history_from": start,
                },
            )
            return SyncResult(
                dataset=dataset, status="planned", pending=len(pending),
                history_from=start, archive_files=len(keys),
            )

        return self._run_dataset(dataset, work)

    def backfill_step(self, dataset: str, *, max_files: int = 1) -> SyncResult:
        """Download and ingest up to ``max_files`` pending bulk files."""

        def work() -> SyncResult:
            checkpoint = self._checkpoint(dataset)
            pending: list[str] = list(checkpoint.get("bulk_pending") or [])
            done: list[str] = list(checkpoint.get("bulk_done") or [])
            if not pending:
                return SyncResult(dataset=dataset, status="backfill_complete", rows=0, pending=0)
            mapper, writer = self._bulk_writer(dataset)
            total = 0
            data_through = None
            for key in pending[: max(1, int(max_files))]:
                handle = self._client.bulk_download_csv(key)
                reader = csv.DictReader(handle)
                batch: list[dict[str, Any]] = []
                for raw in reader:
                    mapped = mapper(raw)
                    if mapped is None:
                        continue
                    batch.append(mapped)
                    if len(batch) >= 20000:
                        total += writer(batch)
                        batch = []
                if batch:
                    total += writer(batch)
                done.append(key)
                pending.remove(key)
                for field in ("trade_date", "application_date", "disclosed_date", "calendar_date"):
                    if batch and batch[-1].get(field):
                        data_through = batch[-1][field]
                        break
                self._repository.record_sync_success(
                    dataset,
                    checkpoint={"bulk_pending": pending, "bulk_done": sorted(set(done))},
                    rows_total=total,
                )
            if not pending:
                # Hand over to the incremental lane from the newest ingested date.
                latest = self._latest_dataset_date(dataset)
                if latest:
                    self._repository.record_sync_success(
                        dataset,
                        checkpoint={"last_synced_date": latest},
                        data_through=latest,
                    )
            return SyncResult(dataset=dataset, status="ok", rows=total, pending=len(pending))

        return self._run_dataset(dataset, work)

    def _latest_dataset_date(self, dataset: str) -> str | None:
        if dataset == DATASET_DAILY_PRICES:
            return self._repository.latest_bar_date()
        if dataset == DATASET_INDEX_PRICES:
            return self._repository.latest_index_date()
        if dataset == DATASET_SHORT_RATIO:
            return self._repository.latest_short_ratio_date()
        state = self._repository.sync_state(dataset)
        return state.get("data_through") if state else None

    def seed_incremental_from(self, dataset: str, last_synced_date: str) -> None:
        """Manual escape hatch: start the incremental lane at a known date
        (used by tests and by fresh deployments that skip deep history)."""

        self._repository.record_sync_success(
            dataset,
            checkpoint={"last_synced_date": last_synced_date},
            data_through=last_synced_date,
        )

    # ------------------------------------------------------------------
    # topix convenience (dedicated endpoint keeps working even if the
    # generic indices endpoint trims TOPIX from the plan)
    # ------------------------------------------------------------------

    def sync_topix_history(self) -> SyncResult:
        def work() -> SyncResult:
            start = self._history_start_date()
            try:
                rows = [
                    mapped
                    for row in self._client.fetch_rows(
                        "/indices/bars/daily/topix", {"from": start, "to": iso_date(today_jst())}
                    )
                    if (mapped := mapping.map_topix_bar(row))
                ]
            except JQuantsPlanError:
                rows = [
                    mapped
                    for row in self._client.fetch_rows(
                        "/indices/bars/daily",
                        {"code": TOPIX_INDEX_CODE, "from": start, "to": iso_date(today_jst())},
                    )
                    if (mapped := mapping.map_index_bar(row))
                ]
            count = self._repository.upsert_index_bars(rows)
            data_through = max((row["trade_date"] for row in rows), default=None)
            # Use a dedicated sync-state key: sharing DATASET_INDEX_PRICES with the
            # generic index sync would reset its data_through/last_error and hide a
            # stalled incremental index lane behind a healthy TOPIX pass.
            self._repository.record_sync_success(
                DATASET_TOPIX_PRICES, rows_total=count, data_through=data_through
            )
            return SyncResult(dataset=DATASET_TOPIX_PRICES, status="ok", rows=count)

        return self._run_dataset(DATASET_TOPIX_PRICES, work)


INDEX_UNIVERSE = tuple(INDEX_CODES)

__all__ = [
    "ALL_DATASETS",
    "DATASET_DAILY_PRICES",
    "DATASET_EARNINGS_CALENDAR",
    "DATASET_FINANCIAL_SUMMARY",
    "DATASET_INDEX_PRICES",
    "DATASET_TOPIX_PRICES",
    "DATASET_MARGIN_ALERTS",
    "DATASET_MARGIN_INTEREST",
    "DATASET_SECURITY_MASTER",
    "DATASET_SHORT_POSITIONS",
    "DATASET_SHORT_RATIO",
    "DATASET_TRADING_CALENDAR",
    "INDEX_UNIVERSE",
    "JQuantsSyncEngine",
    "MAX_INCREMENTAL_DAYS",
    "SyncResult",
]
