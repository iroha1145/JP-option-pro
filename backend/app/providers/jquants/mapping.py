"""Map J-Quants V2 wire rows (abbreviated field names) to domain dicts.

The abbreviated names (O/H/L/C/Vo/Va/AdjC, S17, Mkt, FSales, …) must never
leak past this module. Every mapper returns plain dicts whose keys match the
repository column names one-to-one; unknown wire fields are ignored, missing
fields become None. Numbers may arrive as numbers or numeric strings — both
are accepted; empty strings become None; codes stay strings always.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _text(row: Mapping[str, Any], key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _code(row: Mapping[str, Any], key: str = "Code") -> str | None:
    # Security codes are identifiers, never numbers. "72030" stays "72030".
    value = row.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _num(row: Mapping[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _int(row: Mapping[str, Any], key: str) -> int | None:
    number = _num(row, key)
    if number is None:
        return None
    return int(number)


def _flag(row: Mapping[str, Any], key: str) -> int | None:
    """UL/LL style flags arrive as "0"/"1" strings."""

    value = row.get(key)
    if value in (None, ""):
        return None
    return 1 if str(value).strip() in ("1", "1.0", "true", "True") else 0


def map_security_master(row: Mapping[str, Any]) -> dict[str, Any] | None:
    code = _code(row)
    if not code:
        return None
    return {
        "canonical_code": code,
        "as_of_date": _text(row, "Date"),
        "name_ja": _text(row, "CoName"),
        "name_en": _text(row, "CoNameEn"),
        "sector17_code": _text(row, "S17"),
        "sector17_name": _text(row, "S17Nm"),
        "sector33_code": _text(row, "S33"),
        "sector33_name": _text(row, "S33Nm"),
        "scale_category": _text(row, "ScaleCat"),
        "market_code": _text(row, "Mkt"),
        "market_name": _text(row, "MktNm"),
        "margin_code": _text(row, "Mrgn"),
        "margin_name": _text(row, "MrgnNm"),
        "product_category": _text(row, "ProdCat"),
    }


def map_daily_bar(row: Mapping[str, Any]) -> dict[str, Any] | None:
    code = _code(row)
    trade_date = _text(row, "Date")
    if not code or not trade_date:
        return None
    return {
        "canonical_code": code,
        "trade_date": trade_date,
        "open": _num(row, "O"),
        "high": _num(row, "H"),
        "low": _num(row, "L"),
        "close": _num(row, "C"),
        "upper_limit": _flag(row, "UL"),
        "lower_limit": _flag(row, "LL"),
        "volume": _num(row, "Vo"),
        "turnover_value": _num(row, "Va"),
        "adjustment_factor": _num(row, "AdjFactor"),
        "adj_open": _num(row, "AdjO"),
        "adj_high": _num(row, "AdjH"),
        "adj_low": _num(row, "AdjL"),
        "adj_close": _num(row, "AdjC"),
        "adj_volume": _num(row, "AdjVo"),
    }


def map_index_bar(row: Mapping[str, Any]) -> dict[str, Any] | None:
    code = _code(row)
    trade_date = _text(row, "Date")
    if not code or not trade_date:
        return None
    return {
        "index_code": code,
        "trade_date": trade_date,
        "open": _num(row, "O"),
        "high": _num(row, "H"),
        "low": _num(row, "L"),
        "close": _num(row, "C"),
    }


def map_topix_bar(row: Mapping[str, Any]) -> dict[str, Any] | None:
    trade_date = _text(row, "Date")
    if not trade_date:
        return None
    return {
        "index_code": "0000",
        "trade_date": trade_date,
        "open": _num(row, "O"),
        "high": _num(row, "H"),
        "low": _num(row, "L"),
        "close": _num(row, "C"),
    }


def map_trading_day(row: Mapping[str, Any]) -> dict[str, Any] | None:
    date = _text(row, "Date")
    division = _text(row, "HolDiv")
    if not date or division is None:
        return None
    return {"calendar_date": date, "holiday_division": division}


def map_financial_summary(row: Mapping[str, Any]) -> dict[str, Any] | None:
    code = _code(row)
    disclosed_date = _text(row, "DiscDate")
    disclosure_number = _text(row, "DiscNo")
    if not code or not disclosed_date:
        return None
    return {
        "canonical_code": code,
        "disclosed_date": disclosed_date,
        "disclosed_time": _text(row, "DiscTime"),
        "disclosure_number": disclosure_number,
        "type_of_document": _text(row, "TypeOfDocument"),
        "period_type": _text(row, "CurPerType"),
        "period_start": _text(row, "CurPerSt"),
        "period_end": _text(row, "CurPerEn"),
        "fiscal_year_start": _text(row, "CurFYSt"),
        "fiscal_year_end": _text(row, "CurFYEn"),
        "next_fiscal_year_start": _text(row, "NxtFYSt"),
        "next_fiscal_year_end": _text(row, "NxtFYEn"),
        # Consolidated actuals (cumulative for the period).
        "sales": _num(row, "Sales"),
        "operating_profit": _num(row, "OP"),
        "ordinary_profit": _num(row, "OdP"),
        "net_profit": _num(row, "NP"),
        "eps": _num(row, "EPS"),
        "total_assets": _num(row, "TA"),
        "equity": _num(row, "Eq"),
        "equity_ratio": _num(row, "EqAR"),
        "bps": _num(row, "BPS"),
        # Company forecasts — these are company guidance, never analyst
        # consensus, and the UI must label them 会社予想.
        "forecast_sales_2q": _num(row, "FSales2Q"),
        "forecast_operating_profit_2q": _num(row, "FOP2Q"),
        "forecast_ordinary_profit_2q": _num(row, "FOdP2Q"),
        "forecast_net_profit_2q": _num(row, "FNP2Q"),
        "forecast_eps_2q": _num(row, "FEPS2Q"),
        "forecast_sales": _num(row, "FSales"),
        "forecast_operating_profit": _num(row, "FOP"),
        "forecast_ordinary_profit": _num(row, "FOdP"),
        "forecast_net_profit": _num(row, "FNP"),
        "forecast_eps": _num(row, "FEPS"),
        "next_forecast_sales": _num(row, "NxFSales"),
        "next_forecast_operating_profit": _num(row, "NxFOP"),
        "next_forecast_ordinary_profit": _num(row, "NxFOdP"),
        "next_forecast_net_profit": _num(row, "NxFNP"),
        "next_forecast_eps": _num(row, "NxFEPS"),
        # Dividends.
        "dividend_annual": _num(row, "DivAnn"),
        "forecast_dividend_annual": _num(row, "FDivAnn"),
        "next_forecast_dividend_annual": _num(row, "NxFDivAnn"),
        "payout_ratio_annual": _num(row, "PayoutRatioAnn"),
        # Change flags.
        "material_change_subsidiaries": _text(row, "MatChgSub"),
        "change_by_accounting_standard": _text(row, "ChgByASRev"),
        "change_other_than_accounting_standard": _text(row, "ChgNoASRev"),
        "change_accounting_estimate": _text(row, "ChgAcEst"),
        "retrospective_restatement": _text(row, "RetroRst"),
        # Shares.
        "shares_outstanding_fy": _num(row, "ShOutFY"),
        "treasury_shares_fy": _num(row, "TrShFY"),
        "average_shares": _num(row, "AvgSh"),
        # Non-consolidated (単体) actuals.
        "nc_sales": _num(row, "NCSales"),
        "nc_operating_profit": _num(row, "NCOP"),
        "nc_ordinary_profit": _num(row, "NCOdP"),
        "nc_net_profit": _num(row, "NCNP"),
        "nc_eps": _num(row, "NCEPS"),
    }


def map_earnings_announcement(row: Mapping[str, Any]) -> dict[str, Any] | None:
    code = _code(row)
    if not code:
        return None
    return {
        "canonical_code": code,
        "announcement_date": _text(row, "Date"),  # empty means 未定
        "company_name": _text(row, "CoName"),
        "fiscal_year_end": _text(row, "FY"),
        "fiscal_quarter": _text(row, "FQ"),
        "sector_name": _text(row, "SectorNm"),
        "section": _text(row, "Section"),
    }


def map_margin_interest(row: Mapping[str, Any]) -> dict[str, Any] | None:
    code = _code(row)
    date = _text(row, "Date")
    if not code or not date:
        return None
    return {
        "canonical_code": code,
        "application_date": date,
        "short_total": _num(row, "ShrtVol"),
        "long_total": _num(row, "LongVol"),
        "short_negotiable": _num(row, "ShrtNegVol"),
        "long_negotiable": _num(row, "LongNegVol"),
        "short_standardized": _num(row, "ShrtStdVol"),
        "long_standardized": _num(row, "LongStdVol"),
        "issue_type": _text(row, "IssType"),
    }


def map_margin_alert(row: Mapping[str, Any]) -> dict[str, Any] | None:
    code = _code(row)
    published = _text(row, "PubDate")
    applied = _text(row, "AppDate")
    if not code or not (published or applied):
        return None
    return {
        "canonical_code": code,
        "published_date": published,
        "application_date": applied,
        "short_outstanding": _num(row, "ShrtOut"),
        "long_outstanding": _num(row, "LongOut"),
        "short_long_ratio": _num(row, "SLRatio"),
        "short_outstanding_change": _num(row, "ShrtOutChg"),
        "long_outstanding_change": _num(row, "LongOutChg"),
        "short_outstanding_listed_ratio": _num(row, "ShrtOutRatio"),
        "long_outstanding_listed_ratio": _num(row, "LongOutRatio"),
        "short_negotiable": _num(row, "ShrtNegOut"),
        "short_standardized": _num(row, "ShrtStdOut"),
        "long_negotiable": _num(row, "LongNegOut"),
        "long_standardized": _num(row, "LongStdOut"),
        "tse_regulation_class": _text(row, "TSEMrgnRegCls"),
        "publish_reason": _publish_reason(row),
    }


def _publish_reason(row: Mapping[str, Any]) -> str | None:
    value = row.get("PubReason")
    if value is None:
        return None
    if isinstance(value, Mapping):
        active = sorted(str(k) for k, v in value.items() if str(v).strip() in ("1", "true", "True"))
        return ",".join(active) or None
    text = str(value).strip()
    return text or None


def map_short_ratio(row: Mapping[str, Any]) -> dict[str, Any] | None:
    sector = _text(row, "S33")
    date = _text(row, "Date")
    if not sector or not date:
        return None
    return {
        "sector33_code": sector.zfill(4),
        "trade_date": date,
        "selling_ex_short_value": _num(row, "SellExShortVa"),
        "short_with_restriction_value": _num(row, "ShrtWithResVa"),
        "short_without_restriction_value": _num(row, "ShrtNoResVa"),
    }


def map_short_position(row: Mapping[str, Any]) -> dict[str, Any] | None:
    code = _code(row)
    disclosed = _text(row, "DiscDate")
    calculated = _text(row, "CalcDate")
    if not code or not disclosed or not calculated:
        return None
    return {
        "canonical_code": code,
        "disclosed_date": disclosed,
        "calculated_date": calculated,
        "holder_name": _text(row, "SSName"),
        "investment_fund_name": _text(row, "FundName"),
        "short_position_ratio": _num(row, "ShrtPosToSO"),
        "short_position_shares": _num(row, "ShrtPosShares"),
        "short_position_units": _num(row, "ShrtPosUnits"),
        "previous_report_date": _text(row, "PrevRptDate"),
        "previous_ratio": _num(row, "PrevRptRatio"),
        "notes": _text(row, "Notes"),
    }


__all__ = [
    "map_daily_bar",
    "map_earnings_announcement",
    "map_financial_summary",
    "map_index_bar",
    "map_margin_alert",
    "map_margin_interest",
    "map_security_master",
    "map_short_position",
    "map_short_ratio",
    "map_topix_bar",
    "map_trading_day",
]
