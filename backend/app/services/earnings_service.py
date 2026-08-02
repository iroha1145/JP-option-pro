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


# ---------------------------------------------------------------------------
# 米国版財報カレンダー対応の高密度ビュー
# ---------------------------------------------------------------------------
#
# J-Quants の発表予定 API は「翌営業日分のみ」しか返さない（実測: 全件が
# 次営業日）。週歴・月歴を成立させるため、経済カレンダーと同じ規律で
# 二層にする:
#   confirmed … 公式 API の翌営業日分（確定）
#   estimated … 前年同期の実開示日 + 364日 → 翌営業日（目安。根拠を行で宣言）
# 過去数日は financial_summaries の実開示（released、実績値つき）で埋める。
# 推定はあくまで目安であり、確定分と視覚的に区別して返す。

_PERIOD_SEQUENCE = {"1Q": "2Q", "2Q": "3Q", "3Q": "FY", "4Q": "1Q", "FY": "1Q"}
_PERIOD_LABEL = {"1Q": "第１四半期", "2Q": "第２四半期", "3Q": "第３四半期", "FY": "本決算", "4Q": "本決算"}
_QUARTER_TO_PERIOD = {
    "第１四半期": "1Q", "第２四半期": "2Q", "第３四半期": "3Q",
    "本決算": "FY", "期末": "FY",
}
_ESTIMATE_BASIS = "前年同期の開示日+364日を翌営業日に丸めた目安"
_FEATURED_TURNOVER_JPY = 5_000_000_000.0  # 20日平均売買代金 50億円

UPCOMING_COVERAGE_NOTE = (
    "確定日はJ-Quants発表予定（翌営業日分のみ・3月期/9月期）。それ以外の日付は"
    "前年同期の開示日から導出した目安で、会社都合で前後する。"
)


def _next_trading_day_on_or_after(date: str, trading_days: list[str]) -> str | None:
    from bisect import bisect_left

    index = bisect_left(trading_days, date)
    return trading_days[index] if index < len(trading_days) else None


def _shift_days(date: str, days: int) -> str:
    from datetime import date as date_cls, timedelta

    return (date_cls.fromisoformat(date) + timedelta(days=days)).isoformat()


def _forecast_pack(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    """会社予想と前期実績の対（営業利益優先、無ければ純利益）。

    FY 開示は F* が「終わった期の予想」なので、翌期予想は NxF（純利益のみ）
    に切り替わる —— メトリック名を明示して返し、UI は騙らず表記する。
    """

    if not history:
        return None
    latest = history[0]
    prior_fy = next((row for row in history if row.get("period_type") == "FY"), None)
    metric = "operating_profit"
    forecast = latest.get("forecast_operating_profit")
    if latest.get("period_type") == "FY" or forecast is None:
        next_op = latest.get("next_forecast_operating_profit")
        next_np = latest.get("next_forecast_net_profit")
        if next_op is not None:
            forecast = next_op
        elif next_np is not None:
            metric = "net_profit"
            forecast = next_np
        elif forecast is None:
            metric = "net_profit"
            forecast = latest.get("forecast_net_profit")
    prior_value = prior_fy.get(metric) if prior_fy else None
    previous = history[1] if len(history) >= 2 else None
    direction = _forecast_direction(latest, previous)
    if forecast is None and prior_value is None:
        return None
    return {
        "metric": metric,
        "forecast_value": forecast,
        "prior_fy_value": prior_value,
        "direction": direction,
        "as_of": latest.get("disclosed_date"),
    }


def upcoming_view(
    repository: CoreRepository,
    *,
    today: str,
    days_back: int = 3,
    days_ahead: int = 35,
    watchlist_codes: set[str] | None = None,
    radar_state_by_code: dict[str, str] | None = None,
) -> dict[str, Any]:
    watchlist = watchlist_codes or set()
    radar_states = radar_state_by_code or {}
    window_start = _shift_days(today, -days_back)
    window_end = _shift_days(today, days_ahead)
    trading_days = repository.trading_days_between(today, _shift_days(window_end, 21))

    securities = {
        row["canonical_code"]: row for row in repository.list_securities(active_only=True)
    }
    strength_map = {row["canonical_code"]: row for row in repository.strength_rows_all()}
    quote_map = repository.latest_quote_map()

    # 過去 ~14 か月の開示を一括ロードして code ごとに整理（新しい順）。
    history_rows = repository.summaries_disclosed_between(_shift_days(today, -430), today)
    history_by_code: dict[str, list[dict[str, Any]]] = {}
    for row in history_rows:
        history_by_code.setdefault(row["canonical_code"], []).append(row)

    def base_item(code: str) -> dict[str, Any] | None:
        security = securities.get(code)
        if security is None:
            return None
        strength = strength_map.get(code) or {}
        quote = quote_map.get(code) or {}
        avg_turnover = strength.get("avg_turnover_20d")
        radar_state = radar_states.get(code)
        featured = (
            code in watchlist
            or radar_state is not None
            or (avg_turnover is not None and avg_turnover >= _FEATURED_TURNOVER_JPY)
        )
        return {
            "canonical_code": code,
            "display_code": display_code(code),
            "name_ja": security.get("name_ja"),
            "sector33_name": security.get("sector33_name"),
            "close": quote.get("close"),
            "change_pct": quote.get("change_pct"),
            "avg_turnover_20d": round(avg_turnover) if avg_turnover is not None else None,
            "in_watchlist": code in watchlist,
            "radar_state": radar_state,
            "featured": featured,
            "forecast": _forecast_pack(history_by_code.get(code) or []),
        }

    items: list[dict[str, Any]] = []
    tbd: list[dict[str, Any]] = []
    official_codes: set[str] = set()
    released_codes_today: set[str] = set()

    # --- released: ウィンドウ内の実開示（実績値つき） -------------------------
    released_rows = [
        row for row in history_rows
        if window_start <= (row.get("disclosed_date") or "") <= today
    ]
    for row in released_rows:
        code = row["canonical_code"]
        item = base_item(code)
        if item is None:
            continue
        document = row.get("type_of_document") or ""
        item.update(
            date=row.get("disclosed_date"),
            status="released",
            confirmed=True,
            period_type=row.get("period_type"),
            quarter_label=_PERIOD_LABEL.get(row.get("period_type") or "", row.get("period_type")),
            fiscal_year_end=row.get("fiscal_year_end"),
            actual={
                "sales": row.get("sales"),
                "operating_profit": row.get("operating_profit"),
                "net_profit": row.get("net_profit"),
                "disclosed_time": row.get("disclosed_time"),
                "is_revision": ("修正" in document) if document else False,
            },
        )
        items.append(item)
        if row.get("disclosed_date") == today:
            released_codes_today.add(code)

    # --- confirmed: 公式発表予定（翌営業日分） -------------------------------
    for row in repository.earnings_between(today, window_end):
        code = row["canonical_code"]
        announcement = row.get("announcement_date") or None
        item = base_item(code)
        if item is None:
            continue
        quarter = row.get("fiscal_quarter") or ""
        item.update(
            status="confirmed",
            confirmed=True,
            period_type=_QUARTER_TO_PERIOD.get(quarter, quarter or None),
            quarter_label=quarter or None,
            fiscal_year_end=row.get("fiscal_year_end"),
        )
        if announcement is None:
            item["date"] = None
            item["status"] = "tbd"
            tbd.append(item)
            continue
        if code in released_codes_today and announcement == today:
            continue  # 当日既に開示済み → released 行が真実
        item["date"] = announcement
        items.append(item)
        official_codes.add(code)

    # --- estimated: 前年同期の開示日から導出（公式行がある code は除外） -----
    # 公式リストの対象日（翌営業日）については、3月期/9月期の会社は公式が
    # 網羅的 —— リストに無いのにその日へ推定が落ちたら、それは公式と矛盾
    # する目安なので出さない（12月期などリスト対象外の決算期は残す）。
    official_list_date = min(
        (item["date"] for item in items if item.get("status") == "confirmed"),
        default=None,
    )
    estimated_count = 0
    for code, history in history_by_code.items():
        if code in official_codes or code in released_codes_today:
            continue
        latest = history[0]
        latest_period = latest.get("period_type")
        next_period = _PERIOD_SEQUENCE.get(latest_period or "")
        if not next_period:
            continue
        anchor = next(
            (row for row in history[1:] if row.get("period_type") == next_period),
            None,
        )
        if anchor is None or not anchor.get("disclosed_date"):
            continue
        candidate = _shift_days(anchor["disclosed_date"], 364)
        estimated = _next_trading_day_on_or_after(candidate, trading_days)
        if estimated is None or estimated < today or estimated > window_end:
            continue
        if estimated == official_list_date:
            fiscal_month = str(latest.get("fiscal_year_end") or "")[5:7]
            if fiscal_month in ("03", "09"):
                continue
        item = base_item(code)
        if item is None:
            continue
        item.update(
            date=estimated,
            status="estimated",
            confirmed=False,
            estimate_basis=_ESTIMATE_BASIS,
            period_type=next_period,
            quarter_label=_PERIOD_LABEL.get(next_period, next_period),
            fiscal_year_end=None,
        )
        items.append(item)
        estimated_count += 1

    items.sort(key=lambda row: (row["date"] or "9999", row["canonical_code"]))
    return {
        "version": EARNINGS_VERSION,
        "coverage_note": UPCOMING_COVERAGE_NOTE,
        "today": today,
        "window_start": window_start,
        "window_end": window_end,
        "counts": {
            "released": len(released_rows),
            "confirmed": len(official_codes),
            "estimated": estimated_count,
            "tbd": len(tbd),
        },
        "items": items,
        "tbd_items": tbd,
    }


__all__ = [
    "CALENDAR_COVERAGE_NOTE",
    "EARNINGS_VERSION",
    "UPCOMING_COVERAGE_NOTE",
    "recent_disclosures",
    "upcoming_calendar",
    "upcoming_view",
]
