"""Coordinate independent sources and keep a record of partial failures."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable

from stock_crawler.demo import demo_snapshot
from stock_crawler.models import Snapshot
from stock_crawler.sources.fred import fetch_macro
from stock_crawler.sources.market import fetch_annual_financials, fetch_market, fetch_news
from stock_crawler.sources.sec import fetch_filing
from stock_crawler.utils import text

Progress = Callable[[int, str], None]


def collect(ticker: str, *, demo: bool = False, progress: Progress | None = None) -> Snapshot:
    update = progress or (lambda _percent, _message: None)
    if demo:
        update(30, "Loading the fictional sample dataset")
        snapshot = demo_snapshot()
        update(65, "Checking sample financial and macro coverage")
        return snapshot
    update(10, "Retrieving company profile and daily prices")
    info, prices, holdings, market_warnings = fetch_market(ticker)
    update(35, "Gathering macro observations and available filings")
    # FRED and SEC are independent; either may fail without destroying the rest.
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="sources") as executor:
        macro_future = executor.submit(fetch_macro)
        filing_future = executor.submit(fetch_filing, ticker, os.getenv("SEC_USER_AGENT", "").strip())
        financial_future = executor.submit(fetch_annual_financials, ticker)
        news_future = executor.submit(fetch_news, ticker)
        # Optional sources must not destroy an otherwise usable report. The
        # market history above is the only mandatory input.
        def resolve(future, default, message):
            try:
                return future.result()
            except Exception:
                return default, [message]

        macro, macro_warnings = resolve(macro_future, {}, "The macro data provider failed unexpectedly; macro observations are unavailable.")
        filing, filing_warnings = resolve(filing_future, None, "The SEC lookup failed unexpectedly; filing excerpts are unavailable.")
        annuals, financial_warnings = resolve(financial_future, [], "Annual income statements could not be retrieved.")
        news, news_warnings = resolve(news_future, [], "Recent headlines could not be retrieved.")
    update(65, "Evaluating data coverage and research signals")
    name = text(info.get("longName") or info.get("shortName") or ticker, 120)
    return Snapshot(
        requested_ticker=ticker,
        ticker=ticker,
        name=name,
        info=info,
        prices=prices,
        macro=macro,
        fetched_at=datetime.now(timezone.utc),
        filing=filing,
        holdings=holdings,
        annuals=annuals,
        news=news,
        warnings=market_warnings + macro_warnings + filing_warnings + financial_warnings + news_warnings,
    )
