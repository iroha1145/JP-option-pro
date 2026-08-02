"""Tokyo-time helpers. Every schedule and data date in this project is JST."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def now_jst() -> datetime:
    return datetime.now(JST)


def today_jst() -> date:
    return now_jst().date()


def iso_date(value: date) -> str:
    return value.isoformat()


def parse_iso_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def add_days(value: str, days: int) -> str:
    return iso_date(parse_iso_date(value) + timedelta(days=days))


def jst_minutes_now() -> int:
    moment = now_jst()
    return moment.hour * 60 + moment.minute


def parse_hhmm(value: str) -> int:
    hours, minutes = value.strip().split(":", 1)
    return int(hours) * 60 + int(minutes)


def seconds_until_next_jst_time(times_hhmm: tuple[str, ...], *, now: datetime | None = None) -> float:
    """Seconds until the next JST wall-clock slot, computed in UTC.

    The subtraction happens on aware datetimes so a JST-less host clock or
    DST-affected machine timezone cannot skew the schedule (JST itself has
    no DST, but the host may).
    """

    moment = now.astimezone(JST) if now else now_jst()
    candidates: list[datetime] = []
    for raw in times_hhmm:
        minutes = parse_hhmm(raw)
        slot = moment.replace(hour=minutes // 60, minute=minutes % 60, second=0, microsecond=0)
        if slot <= moment:
            slot = slot + timedelta(days=1)
        candidates.append(slot)
    if not candidates:
        return 3600.0
    target = min(candidates)
    return max(1.0, (target - moment).total_seconds())


__all__ = [
    "JST",
    "add_days",
    "iso_date",
    "jst_minutes_now",
    "now_jst",
    "parse_hhmm",
    "parse_iso_date",
    "seconds_until_next_jst_time",
    "today_jst",
]
