"""Coordinate independent sources and keep a record of partial failures."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable

from stock_crawler.archive import load_signals
from stock_crawler.demo import demo_snapshot
from stock_crawler.models import Snapshot
from stock_crawler.sources.fred import fetch_macro
from stock_crawler.sources.market import (
    fetch_analyst_trend, fetch_annual_financials, fetch_benchmark, fetch_market, fetch_news, fetch_options,
)
from stock_crawler.sources.politics import fetch_political_context
from stock_crawler.sources.peers import fetch_peers
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
    update(10, "Retrieving company profile and historical prices")
    info, prices, holdings, market_warnings, price_source = fetch_market(ticker)
    update(35, "Gathering macro, policy, sentiment and available filings")
    quote_type = str(info.get("quoteType") or "").upper()
    use_benchmark = str(info.get("currency") or "") == "USD" and quote_type in {"EQUITY", "ETF"}
    with ThreadPoolExecutor(max_workers=9, thread_name_prefix="sources") as executor:
        macro_future = executor.submit(fetch_macro)
        filing_future = executor.submit(fetch_filing, ticker, os.getenv("SEC_USER_AGENT", "").strip())
        financial_future = executor.submit(fetch_annual_financials, ticker)
        news_future = executor.submit(fetch_news, ticker)
        politics_future = executor.submit(fetch_political_context, info)
        benchmark_future = executor.submit(fetch_benchmark) if use_benchmark and ticker != "SPY" else None
        options_future = executor.submit(fetch_options, ticker) if quote_type in {"EQUITY", "ETF"} else None
        analyst_future = executor.submit(fetch_analyst_trend, ticker) if quote_type == "EQUITY" else None
        peer_future = executor.submit(fetch_peers, ticker, info) if quote_type == "EQUITY" else None
        # Optional sources must not destroy an otherwise usable report. The
        # market history above is the only mandatory input.
        def resolve(future, default, message):
            try:
                return future.result()
            except Exception:
                return default, [message]

        try:
            macro, macro_history, macro_warnings = macro_future.result()
        except Exception:
            macro, macro_history = {}, {}
            macro_warnings = ["The macro data provider failed unexpectedly; macro observations are unavailable."]
        filing, filing_warnings = resolve(filing_future, None, "The SEC lookup failed unexpectedly; filing excerpts are unavailable.")
        annuals, financial_warnings = resolve(financial_future, [], "Annual income statements could not be retrieved.")
        news, news_warnings = resolve(news_future, [], "Recent headlines could not be retrieved.")
        politics, politics_warnings = resolve(politics_future, None, "Election and officeholder data could not be retrieved.")
        benchmark, benchmark_warnings = (resolve(benchmark_future, [], "The SPY benchmark could not be retrieved.")
                                         if benchmark_future else (prices if use_benchmark and ticker == "SPY" else [], []))
        options, options_warnings = (resolve(options_future, None, "Options positioning could not be retrieved.")
                                     if options_future else (None, []))
        analyst_trend, analyst_warnings = (resolve(analyst_future, [], "Analyst recommendation history could not be retrieved.")
                                            if analyst_future else ([], []))
        peers, peer_warnings = (resolve(peer_future, None, "Comparable industry peers could not be retrieved; valuation is unscored.")
                                if peer_future else (None, []))
    update(65, "Evaluating data coverage, sentiment and historical reactions")
    recorded_signals, archive_warnings = load_signals(ticker)
    name = text(info.get("longName") or info.get("shortName") or ticker, 120)
    return Snapshot(
        requested_ticker=ticker,
        ticker=ticker,
        name=name,
        info=info,
        prices=prices,
        macro=macro,
        fetched_at=datetime.now(timezone.utc),
        price_source=price_source,
        macro_history=macro_history,
        peers=peers,
        recorded_signals=recorded_signals,
        filing=filing,
        holdings=holdings,
        annuals=annuals,
        news=news,
        politics=politics,
        benchmark_prices=benchmark,
        options=options,
        analyst_trend=analyst_trend,
        warnings=(market_warnings + macro_warnings + filing_warnings + financial_warnings + news_warnings +
                  politics_warnings + benchmark_warnings + options_warnings + analyst_warnings + peer_warnings + archive_warnings),
    )
