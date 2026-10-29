"""Limited, best-effort daily price fallback for plain US symbols.

Stooq's CSV endpoint is unofficial. It does not establish issuer identity,
quote type, fundamentals, or a separately documented adjusted-close series.
Those fields must not be fabricated from an assumed symbol mapping.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timezone

import requests
from dateutil.relativedelta import relativedelta

from stock_crawler.models import PricePoint
from stock_crawler.utils import number


def stooq_symbol(ticker: str) -> str | None:
    # Avoid silently mapping international listings, funds with punctuation,
    # crypto, currency pairs or ambiguous class-share notation to a US ticker.
    return ticker.lower() + ".us" if re.fullmatch(r"[A-Z]{1,5}", ticker) else None


def fetch_stooq_prices(ticker: str) -> list[PricePoint]:
    symbol = stooq_symbol(ticker)
    if not symbol:
        return []
    response = requests.get("https://stooq.com/q/d/l/", params={"s": symbol, "i": "d"},
                            headers={"User-Agent": "StockCrawler/1.1 (research application)"}, timeout=(5, 20))
    response.raise_for_status()
    # Protect the local service against an accidental enormous/non-CSV response.
    if len(response.content) > 5_000_000:
        raise ValueError("Stooq response too large")
    today = datetime.now(timezone.utc).date()
    cutoff = today - relativedelta(years=10)
    prices: dict[date, PricePoint] = {}
    reader = csv.DictReader(io.StringIO(response.text))
    if not reader.fieldnames or not {"Date", "Close"}.issubset(reader.fieldnames):
        return []
    for row in reader:
        try:
            day = date.fromisoformat(row.get("Date", ""))
        except (ValueError, TypeError):
            continue
        close, volume = number(row.get("Close")), number(row.get("Volume"))
        if cutoff <= day <= today and close is not None and close > 0:
            # Adjustment methodology is not available in this feed. Do not
            # treat Close as a separate adjusted series for volatility/tests.
            prices[day] = PricePoint(day, close, None, volume if volume is not None and volume >= 0 else None)
    return [prices[day] for day in sorted(prices)]
