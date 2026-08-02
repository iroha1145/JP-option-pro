"""決算カレンダーと直近開示ビュー。

J-Quants の決算発表予定 API は「3月期・9月期決算のみ、直近分のみ」という
公式制限があるため、その事実をレスポンスで宣言する。過去の開示実績は
financial_summaries（開示日ベース）から構成する。
"""

from __future__ import annotations

from typing import Any

from app.domain.symbols import display_code
from app.repositories.core import CoreRepository

EARNINGS_VERSION = "jp-earnings-v1"

CALENDAR_COVERAGE_NOTE = (
    "決算発表予定はJ-Quants仕様により3月期・9月期決算会社の直近分のみ。REITは含まれない。"
)


def upcoming_calendar(
    repository: CoreRepository,
    *,
    start_date: str,
    end_date: str,
    watchlist_codes: set[str] | None = None,
) -> dict[str, Any]:
    rows = repository.earnings_between(start_date, end_date)
    watchlist = watchlist_codes or set()
    items = []
    for row in rows:
        code = row["canonical_code"]
        items.append(
            {
                "canonical_code": code,
                "display_code": display_code(code),
                "company_name": row.get("company_name"),
                "announcement_date": row.get("announcement_date") or None,
                "fiscal_year_end": row.get("fiscal_year_end"),
                "fiscal_quarter": row.get("fiscal_quarter"),
                "sector_name": row.get("sector_name"),
                "section": row.get("section"),
                "in_watchlist": code in watchlist,
            }
        )
    return {
        "version": EARNINGS_VERSION,
        "coverage_note": CALENDAR_COVERAGE_NOTE,
        "start_date": start_date,
        "end_date": end_date,
        "items": items,
    }


def _forecast_direction(latest: dict[str, Any], previous: dict[str, Any] | None) -> str | None:
    """会社予想の方向変化: 直前開示の期末予想と比較する。"""

    if previous is None:
        return None
    current = latest.get("forecast_operating_profit")
    prior = previous.get("forecast_operating_profit")
    if current is None or prior is None or prior == 0:
        current = latest.get("forecast_net_profit")
        prior = previous.get("forecast_net_profit")
    if current is None or prior is None or prior == 0:
        return None
    delta = (current - prior) / abs(prior)
    if delta > 0.005:
        return "upward"
    if delta < -0.005:
        return "downward"
    return "unchanged"


def recent_disclosures(
    repository: CoreRepository,
    *,
    start_date: str,
    end_date: str,
    watchlist_codes: set[str] | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    rows = repository.summaries_disclosed_between(start_date, end_date)
    watchlist = watchlist_codes or set()
    security_names: dict[str, dict[str, Any]] = {}
    items: list[dict[str, Any]] = []
    for row in rows[: max(1, int(limit))]:
        code = row["canonical_code"]
        if code not in security_names:
            security_names[code] = repository.get_security(code) or {}
        security = security_names[code]
        history = repository.summaries_for_code(code, limit=2)
        previous = history[1] if len(history) >= 2 and history[0].get("disclosure_number") == row.get("disclosure_number") else None
        document = (row.get("type_of_document") or "")
        items.append(
            {
                "canonical_code": code,
                "display_code": display_code(code),
                "name_ja": security.get("name_ja"),
                "sector33_name": security.get("sector33_name"),
                "disclosed_date": row.get("disclosed_date"),
                "disclosed_time": row.get("disclosed_time"),
                "period_type": row.get("period_type"),
                "fiscal_year_end": row.get("fiscal_year_end"),
                "type_of_document": document or None,
                "is_forecast_revision": "修正" in document if document else None,
                "sales": row.get("sales"),
                "operating_profit": row.get("operating_profit"),
                "ordinary_profit": row.get("ordinary_profit"),
                "net_profit": row.get("net_profit"),
                "eps": row.get("eps"),
                "forecast_operating_profit": row.get("forecast_operating_profit"),
                "forecast_direction": _forecast_direction(row, previous),
                "forecast_label": "会社予想",
                "in_watchlist": code in watchlist,
            }
        )
    return {
        "version": EARNINGS_VERSION,
        "start_date": start_date,
        "end_date": end_date,
        "items": items,
    }


__all__ = [
    "CALENDAR_COVERAGE_NOTE",
    "EARNINGS_VERSION",
    "recent_disclosures",
    "upcoming_calendar",
]
