from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from typing import Any

TICKER_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=^]{0,24}$")
# Quoted minor units can differ from how providers express market capitalization.
MINOR_UNIT_CURRENCIES = {"GBp", "GBX", "ZAc", "ILa"}


def normalize_ticker(value: str) -> str:
    ticker = value.strip().upper()
    if not TICKER_RE.fullmatch(ticker):
        raise ValueError(
            "Enter a valid Yahoo Finance symbol (for example AAPL, BRK-B, VOD.L, or BTC-USD)."
        )
    return ticker


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def text(value: Any, limit: int = 300) -> str:
    if value is None:
        return ""
    result = re.sub(r"\s+", " ", str(value)).strip()
    if len(result) > limit:
        return result[: limit - 3].rsplit(" ", 1)[0] + "..."
    return result


def date_from_timestamp(value: Any) -> date | None:
    num = number(value)
    if num is None:
        return None
    try:
        return datetime.fromtimestamp(num, timezone.utc).date()
    except (ValueError, OverflowError, OSError):
        return None


def pct(value: float | None, *, signed: bool = False, digits: int = 1) -> str:
    if value is None:
        return "Not available"
    return f"{value:+.{digits}%}" if signed else f"{value:.{digits}%}"


def price(value: float | None, currency: str) -> str:
    if value is None:
        return "Not available"
    return f"{currency} {value:,.2f}"


def compact(value: float | None, currency: str = "") -> str:
    if value is None:
        return "Not available"
    absolute = abs(value)
    if absolute >= 1e12:
        result = f"{value / 1e12:,.2f}T"
    elif absolute >= 1e9:
        result = f"{value / 1e9:,.2f}B"
    elif absolute >= 1e6:
        result = f"{value / 1e6:,.2f}M"
    elif absolute >= 1000:
        result = f"{value:,.0f}"
    else:
        result = f"{value:,.2f}"
    return f"{currency} {result}".strip()


def days_old(day: date, today: date | None = None) -> int:
    return max(0, ((today or datetime.now(timezone.utc).date()) - day).days)
