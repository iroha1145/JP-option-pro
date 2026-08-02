"""Security code normalization for the Japanese market.

J-Quants uses 5-character codes: the familiar 4-character local code plus a
check digit position ("7203" → "72030"). Codes are NOT numbers — new-style
codes contain letters ("130A0", "285A0") — so nothing here ever converts a
code to int, and only this module is allowed to reason about the 4↔5
character relationship. Business code must call these helpers.
"""

from __future__ import annotations

import re

_CODE_RE = re.compile(r"^[0-9][0-9A-Z]{3,4}$")


def normalize_input_code(raw: str | None) -> str | None:
    """Accept user/API input ("7203", "72030", "285A") → canonical 5-char code.

    Returns None when the input cannot be a Japanese security code.
    """

    if raw is None:
        return None
    text = raw.strip().upper()
    # Tolerate vendor suffixes like "7203.T"/"7203.JP" on input only.
    if "." in text:
        text = text.split(".", 1)[0]
    if not _CODE_RE.fullmatch(text):
        return None
    if len(text) == 4:
        # Local 4-char code: the J-Quants canonical form appends "0".
        return text + "0"
    return text


def display_code(canonical: str) -> str:
    """Canonical 5-char code → the 4-char code humans use.

    Only a trailing "0" is dropped; codes whose fifth character is
    meaningful (non-zero check position) display in full.
    """

    text = (canonical or "").strip().upper()
    if len(text) == 5 and text.endswith("0"):
        return text[:4]
    return text


def is_canonical_code(value: str | None) -> bool:
    if value is None:
        return False
    text = value.strip().upper()
    return len(text) == 5 and bool(_CODE_RE.fullmatch(text))


def is_common_stock_code(canonical: str) -> bool:
    """Heuristic for 普通株 vs ETF/REIT ranges is NOT reliable by code alone —
    the master data's product category is authoritative. Kept only as a
    guard for obviously non-equity input."""

    return is_canonical_code(canonical)


__all__ = [
    "display_code",
    "is_canonical_code",
    "is_common_stock_code",
    "normalize_input_code",
]
