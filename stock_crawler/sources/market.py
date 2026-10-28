"""Yahoo Finance market/profile data through yfinance (unofficial, best effort)."""
from __future__ import annotations

from datetime import date
from typing import Any

import yfinance as yf

from stock_crawler.models import PricePoint
from stock_crawler.utils import number, text


class MarketDataError(RuntimeError):
    """A symbol could not be researched with the available price source."""


def fetch_market(ticker: str) -> tuple[dict[str, Any], list[PricePoint], list[tuple[str, str, float | None]], list[str]]:
    warnings: list[str] = []
    instrument = yf.Ticker(ticker)
    try:
        # Close is used consistently for the anchor and price-return calculations;
        # it is not adjusted for dividends. We do not treat it as a live quote.
        history = instrument.history(period="1y", interval="1d", auto_adjust=False, timeout=12, raise_errors=True)
    except Exception as exc:
        raise MarketDataError(
            f"Could not retrieve price history for {ticker}. Check the Yahoo Finance symbol and network access, or try again if the provider is rate-limiting requests."
        ) from exc
    prices: list[PricePoint] = []
    try:
        for index, row in history.iterrows():
            close = number(row.get("Close"))
            day = index.date() if hasattr(index, "date") else date.fromisoformat(str(index)[:10])
            if close is not None and close > 0:
                prices.append(PricePoint(day, close))
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise MarketDataError(f"The price history returned for {ticker} could not be read.") from exc
    prices.sort(key=lambda point: point.date)
    prices = list({point.date: point for point in prices}.values())
    if not prices:
        raise MarketDataError(
            f"No usable price history was found for {ticker}. Check the symbol (international listings often need a suffix such as .L or .T), or try again later."
        )
    try:
        info = instrument.get_info() or {}
        if not isinstance(info, dict):
            info = {}
    except Exception:
        info = {}
    if not info:
        warnings.append("The Yahoo Finance company profile and statistics were unavailable; price history alone cannot support a full conclusion.")

    holdings: list[tuple[str, str, float | None]] = []
    if str(info.get("quoteType", "")).upper() in {"ETF", "MUTUALFUND"}:
        try:
            frame = instrument.funds_data.top_holdings
            for symbol, row in frame.head(8).iterrows():
                holding_name = text(row.get("Name") or symbol, 100)
                weight = number(row.get("Holding Percent"))
                # Do not guess whether out-of-range values represent percentages.
                if weight is not None and not 0 <= weight <= 1:
                    weight = None
                holdings.append((text(symbol, 25), holding_name, weight))
        except Exception:
            warnings.append("Fund holdings were not available from the market-data provider.")
    if len(prices) < 100:
        warnings.append("Less than roughly five months of daily price history was available; momentum and historical context may be limited.")
    return info, prices, holdings, warnings


def fetch_annual_financials(ticker: str):
    """Best-effort annual statements; do not assume missing values are zero."""
    from stock_crawler.models import AnnualFinancial

    try:
        # yfinance's default row names are camelCase; request readable labels
        # and still accept raw labels for provider/version compatibility.
        frame = yf.Ticker(ticker).get_income_stmt(freq="yearly", pretty=True)
        if frame is None or frame.empty:
            return [], ["Annual income statements were unavailable from the market-data provider."]
        def cell(column, *labels: str):
            for label in labels:
                if label in frame.index:
                    return number(frame.at[label, column])
            return None

        rows = []
        for column in list(frame.columns)[:4]:
            period = column.date() if hasattr(column, "date") else date.fromisoformat(str(column)[:10])
            item = AnnualFinancial(period, cell(column, "Total Revenue", "TotalRevenue"),
                                   cell(column, "Operating Income", "OperatingIncome"), cell(column, "Net Income", "NetIncome"))
            if any(v is not None for v in (item.revenue, item.operating_income, item.net_income)):
                rows.append(item)
        rows.sort(key=lambda item: item.period_end, reverse=True)
        return rows, [] if rows else ["Annual income statements contained no usable values."]
    except Exception:
        return [], ["Annual income statements were unavailable from the market-data provider."]


def fetch_news(ticker: str):
    """Provider-linked headlines, presented as headlines rather than verified facts."""
    from urllib.parse import urlsplit
    from stock_crawler.models import NewsItem

    try:
        raw = yf.Ticker(ticker).get_news(count=6)
        result = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            content = item.get("content") if isinstance(item.get("content"), dict) else item
            title = text(content.get("title"), 160)
            provider = content.get("provider")
            publisher = text(provider.get("displayName") if isinstance(provider, dict) else content.get("publisher"), 70) or "Publisher not supplied"
            published = text(content.get("pubDate") or content.get("displayTime"), 30)
            if not published and number(content.get("providerPublishTime")) is not None:
                from datetime import datetime, timezone
                published = datetime.fromtimestamp(float(content["providerPublishTime"]), timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            url = ""
            for candidate in (content.get("canonicalUrl"), content.get("clickThroughUrl"), content.get("link")):
                candidate = candidate.get("url", "") if isinstance(candidate, dict) else candidate or ""
                candidate = str(candidate)
                if urlsplit(candidate).scheme in {"http", "https"} and urlsplit(candidate).netloc:
                    url = candidate
                    break
            if not title or not url:
                continue
            result.append(NewsItem(title, publisher, published or "Date not supplied", url))
            if len(result) == 4:
                break
        return result, [] if result else ["Recent provider-linked headlines were unavailable; current events should be checked separately."]
    except Exception:
        return [], ["Recent provider-linked headlines were unavailable; current events should be checked separately."]
