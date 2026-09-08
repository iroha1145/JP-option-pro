"""Publication contract for nightly strength / screener snapshots.

See ``docs/DESIGN.md``. This module is the single place that defines
outcome names, coverage arithmetic, expected trade dates, and freshness
evaluation. Callers must not treat HTTP 200 or task completion as proof
that a new publication was submitted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from app.domain.timeutil import JST, add_days, iso_date, parse_hhmm

OUTCOME_PUBLISHED = "published"
OUTCOME_ALREADY_CURRENT = "already_current"
OUTCOME_RETAINED = "retained"
OUTCOME_WAITING_INPUT = "waiting_input"
OUTCOME_SKIPPED = "skipped"
OUTCOME_FAILED = "failed"

REASON_EMPTY_INPUT = "empty_input"
REASON_INCOMPLETE_COVERAGE = "incomplete_coverage"
REASON_INPUT_REGRESSION = "input_date_regression"
REASON_BARS_NOT_CURRENT = "bars_not_current"
REASON_NOT_PUBLISHED = "not_published"
REASON_PREVIOUS_UNUSABLE = "previous_unusable"

MAX_POST_CLOSE_RETRY_ATTEMPTS = 12


@dataclass
class CoverageSummary:
    expected: int = 0
    arrived: int = 0
    valid: int = 0
    invalid: int = 0
    unknown_missing: int = 0
    excluded: int = 0
    filtered: int = 0
    index_input_date: str | None = None
    index_stale: bool = False
    universe_version: str = ""
    reasons: dict[str, int] = field(default_factory=dict)

    @property
    def allows_complete_publish(self) -> bool:
        return self.expected > 0 and self.unknown_missing == 0 and self.invalid == 0

    def add_reason(self, reason: str) -> None:
        self.reasons[reason] = self.reasons.get(reason, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allows_complete_publish"] = self.allows_complete_publish
        return payload


@dataclass
class PublicationResult:
    outcome: str
    rows_written: int
    publication_id: str | None = None
    built_at: str | None = None
    trade_date: str | None = None
    score_version: str | None = None
    reason: str | None = None
    previous_publication_id: str | None = None
    input_data_through: str | None = None
    coverage: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def clip_rows_through(
    rows: Sequence[Mapping[str, Any]] | None, target_date: str
) -> list[Mapping[str, Any]]:
    """Historical replay must not consume bars after the target session."""

    if not rows:
        return []
    return [row for row in rows if str(row.get("trade_date") or "") <= target_date]


def classify_equity_input(
    bars: Sequence[Mapping[str, Any]] | None,
    target_date: str,
    *,
    min_feature_bars: int,
) -> tuple[str, Any, str]:
    """Return ``(bucket, cleaned_series_or_none, reason)``.

    Buckets: ``valid`` / ``invalid`` / ``unknown_missing`` / ``excluded``.
    Halt is never inferred from a missing print.
    """

    from app.services.radar.features import clean_series

    clipped = clip_rows_through(bars, target_date)
    if not clipped:
        return "unknown_missing", None, "no_bars"
    has_target = any(str(row.get("trade_date")) == target_date for row in clipped)
    series = clean_series(clipped)
    if series is None:
        if has_target and len(clipped) < min_feature_bars:
            return "excluded", None, "insufficient_history"
        if has_target:
            return "invalid", None, "uncleanable_target_bar"
        return "unknown_missing", None, "no_target_bar"
    last = str(series["dates"][-1])
    if last != target_date:
        if has_target:
            return "invalid", series, "target_bar_dropped"
        return "unknown_missing", series, "no_target_bar"
    return "valid", series, "ok"


def universe_version(
    codes: Sequence[str],
    *,
    market_codes: Sequence[str],
    min_listed_days: int,
    min_avg_turnover_jpy: float,
) -> str:
    blob = json.dumps(
        {
            "codes": sorted(codes),
            "markets": list(market_codes),
            "min_listed_days": min_listed_days,
            "min_avg_turnover_jpy": min_avg_turnover_jpy,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def input_fingerprint(
    valid_inputs: Sequence[tuple[str, str, float | None]],
    *,
    score_version: str,
    universe_version_value: str,
) -> str:
    blob = json.dumps(
        {
            "inputs": [list(item) for item in sorted(valid_inputs)],
            "score_version": score_version,
            "universe_version": universe_version_value,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def expected_trade_date(
    *,
    today: str,
    now: datetime,
    batch_hhmm: str,
    latest_trading_day: Callable[[str], str | None],
) -> str | None:
    """Target session whose official daily batch should exist *now*.

    Boundary comes from configuration, not a hardcoded 15:30 close.
    """

    moment = now.astimezone(JST) if now.tzinfo else now.replace(tzinfo=JST)
    latest = latest_trading_day(today)
    if latest is None:
        return None
    if latest == today:
        boundary = parse_hhmm(batch_hhmm)
        if moment.hour * 60 + moment.minute < boundary:
            latest = latest_trading_day(add_days(today, -1))
    return latest


def previous_publication_usable(meta: Mapping[str, Any] | None, *, today: str | None) -> bool:
    """A previous snapshot can block a worse replacement only if it is coherent."""

    if not meta:
        return False
    publication_id = meta.get("publication_id")
    trade_date = str(meta.get("trade_date") or "")
    if not publication_id or not trade_date:
        return False
    if today and trade_date > today:
        return False
    built_at = str(meta.get("built_at") or "")
    if built_at.endswith("Z") or "+" in built_at[10:]:
        pass
    elif not built_at:
        return False
    return True


def evaluate_freshness(
    *,
    stored_trade_date: str | None,
    expected: str | None,
    stored_score_version: str | None,
    current_score_version: str,
    coverage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if stored_score_version is None or stored_score_version == "":
        version_state = "unknown"
        compatible = False
    elif stored_score_version != current_score_version:
        version_state = "incompatible"
        compatible = False
    else:
        version_state = "current"
        compatible = True

    if expected is None:
        calendar_state = "unknown"
    elif not stored_trade_date:
        calendar_state = "missing"
    elif stored_trade_date == expected:
        calendar_state = "current"
    elif stored_trade_date < expected:
        calendar_state = "stale"
    else:
        calendar_state = "ahead"

    complete = bool((coverage or {}).get("allows_complete_publish", True))
    if calendar_state == "unknown":
        freshness = "unknown"
    elif calendar_state == "current" and compatible and complete:
        freshness = "current"
    elif calendar_state == "stale":
        freshness = "stale"
    elif not compatible:
        freshness = "incompatible"
    else:
        freshness = calendar_state

    return {
        "calendar_state": calendar_state,
        "version_state": version_state,
        "score_compatible": compatible,
        "freshness": freshness,
    }


def strength_etag(
    *,
    publication_id: str | None,
    stored_score_version: str | None,
    expected_trade_date_value: str | None,
    freshness: Mapping[str, Any],
    universe_count: int,
) -> str:
    raw = "|".join(
        (
            publication_id or "",
            stored_score_version or "unknown",
            expected_trade_date_value or "",
            str(freshness.get("freshness") or ""),
            str(freshness.get("calendar_state") or ""),
            str(universe_count),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def parse_aware_datetime(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=JST)
    return moment


def seconds_until_deadline(deadline_iso: str, *, now: datetime | None = None) -> float:
    target = parse_aware_datetime(deadline_iso)
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    remaining = (target.astimezone(timezone.utc) - moment.astimezone(timezone.utc)).total_seconds()
    return max(0.5, remaining)


def absolute_retry_iso(*, now: datetime | None = None, delay_seconds: float) -> str:
    moment = now.astimezone(JST) if now else datetime.now(JST)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=JST)
    target = moment + timedelta(seconds=delay_seconds)
    return target.isoformat()


__all__ = [
    "CoverageSummary",
    "MAX_POST_CLOSE_RETRY_ATTEMPTS",
    "OUTCOME_ALREADY_CURRENT",
    "OUTCOME_FAILED",
    "OUTCOME_PUBLISHED",
    "OUTCOME_RETAINED",
    "OUTCOME_SKIPPED",
    "OUTCOME_WAITING_INPUT",
    "PublicationResult",
    "REASON_BARS_NOT_CURRENT",
    "REASON_EMPTY_INPUT",
    "REASON_INCOMPLETE_COVERAGE",
    "REASON_INPUT_REGRESSION",
    "REASON_NOT_PUBLISHED",
    "REASON_PREVIOUS_UNUSABLE",
    "absolute_retry_iso",
    "classify_equity_input",
    "clip_rows_through",
    "evaluate_freshness",
    "expected_trade_date",
    "input_fingerprint",
    "parse_aware_datetime",
    "previous_publication_usable",
    "seconds_until_deadline",
    "strength_etag",
    "universe_version",
]
