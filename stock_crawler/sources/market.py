"""Yahoo Finance market/profile data through yfinance (unofficial, best effort)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import yfinance as yf

from stock_crawler.models import AnalystPeriod, AnnualFinancial, NewsItem, OptionsSnapshot, PricePoint
from stock_crawler.utils import number, text


class MarketDataError(RuntimeError):
    """A symbol could not be researched with the available price source."""


def _prices_from_frame(history) -> list[PricePoint]:
    prices: list[PricePoint] = []
    for index, row in history.iterrows():
        close = number(row.get("Close"))
        adjusted = number(row.get("Adj Close"))
        volume = number(row.get("Volume"))
        day = index.date() if hasattr(index, "date") else date.fromisoformat(str(index)[:10])
        if close is not None and close > 0:
            prices.append(PricePoint(day, close, adjusted if adjusted is not None and adjusted > 0 else None,
                                     volume if volume is not None and volume >= 0 else None))
    prices.sort(key=lambda point: point.date)
    return list({point.date: point for point in prices}.values())


def _history(instrument, period: str):
    return instrument.history(period=period, interval="1d", auto_adjust=False, timeout=12, raise_errors=True)


def fetch_market(ticker: str) -> tuple[dict[str, Any], list[PricePoint], list[tuple[str, str, float | None]], list[str]]:
    warnings: list[str] = []
    instrument = yf.Ticker(ticker)
    prices: list[PricePoint] = []
    last_error = None
    # Ten years allows several election windows when the instrument has traded
    # long enough. If the provider can't supply it, retain a one-year fallback.
    for period in ("10y", "1y"):
        try:
            prices = _prices_from_frame(_history(instrument, period))
            if prices:
                if period == "1y":
                    warnings.append("Only a one-year history was available; election-event analysis will be limited.")
                break
        except Exception as exc:
            last_error = exc
    if not prices:
        raise MarketDataError(
            f"Could not retrieve usable price history for {ticker}. Check the Yahoo Finance symbol and network access, or try again if the provider is rate-limiting requests."
        ) from last_error
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
                if weight is not None and not 0 <= weight <= 1:
                    weight = None
                holdings.append((text(symbol, 25), holding_name, weight))
        except Exception:
            warnings.append("Fund holdings were not available from the market-data provider.")
    if len(prices) < 100:
        warnings.append("Less than roughly five months of daily price history was available; momentum and historical context may be limited.")
    return info, prices, holdings, warnings


def fetch_benchmark() -> tuple[list[PricePoint], list[str]]:
    """SPY's adjusted-close series, used for aligned US election comparisons."""
    try:
        prices = _prices_from_frame(_history(yf.Ticker("SPY"), "10y"))
        if not any(point.adjusted_close is not None for point in prices):
            raise ValueError("Adjusted closes unavailable")
        return prices, []
    except Exception:
        return [], ["SPY adjusted price history was unavailable; election-event benchmark comparisons are omitted."]


def fetch_annual_financials(ticker: str):
    """Best-effort annual income and cash-flow statements; missing is never zero."""
    instrument = yf.Ticker(ticker)
    warnings: list[str] = []
    try:
        income = instrument.get_income_stmt(freq="yearly", pretty=True)
    except Exception:
        income = None
    try:
        cashflow = instrument.get_cashflow(freq="yearly", pretty=True)
    except Exception:
        cashflow = None
    if income is None or income.empty:
        warnings.append("Annual income statements were unavailable from the market-data provider.")
    if cashflow is None or cashflow.empty:
        warnings.append("Annual cash-flow statements were unavailable from the market-data provider.")

    def columns_by_date(frame):
        if frame is None or frame.empty:
            return {}
        result = {}
        for column in list(frame.columns)[:5]:
            try:
                period = column.date() if hasattr(column, "date") else date.fromisoformat(str(column)[:10])
                result[period] = column
            except (TypeError, ValueError):
                continue
        return result

    def cell(frame, column, *labels: str):
        if frame is None or column is None:
            return None
        for label in labels:
            if label in frame.index:
                return number(frame.at[label, column])
        return None

    income_columns = columns_by_date(income)
    cash_columns = columns_by_date(cashflow)
    rows = []
    for period in sorted(set(income_columns) | set(cash_columns), reverse=True)[:4]:
        ic, cc = income_columns.get(period), cash_columns.get(period)
        item = AnnualFinancial(
            period, cell(income, ic, "Total Revenue", "TotalRevenue"),
            cell(income, ic, "Operating Income", "OperatingIncome"),
            cell(income, ic, "Net Income", "NetIncome"),
            cell(cashflow, cc, "Operating Cash Flow", "OperatingCashFlow"),
            cell(cashflow, cc, "Capital Expenditure", "CapitalExpenditure"),
            cell(cashflow, cc, "Free Cash Flow", "FreeCashFlow"),
        )
        if any(v is not None for v in (item.revenue, item.operating_income, item.net_income,
                                        item.operating_cash_flow, item.capital_expenditure, item.free_cash_flow)):
            rows.append(item)
    return rows, warnings


def fetch_news(ticker: str):
    """Provider-linked headlines; neither relevance nor article claims are verified."""
    try:
        raw = yf.Ticker(ticker).get_news(count=20)
        result = []
        seen: set[str] = set()
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            content = item.get("content") if isinstance(item.get("content"), dict) else item
            title = text(content.get("title"), 160)
            provider = content.get("provider")
            publisher = text(provider.get("displayName") if isinstance(provider, dict) else content.get("publisher"), 70) or "Publisher not supplied"
            published = text(content.get("pubDate") or content.get("displayTime"), 30)
            if not published and number(content.get("providerPublishTime")) is not None:
                published = datetime.fromtimestamp(float(content["providerPublishTime"]), timezone.utc).isoformat()
            url = ""
            for candidate in (content.get("canonicalUrl"), content.get("clickThroughUrl"), content.get("link")):
                candidate = candidate.get("url", "") if isinstance(candidate, dict) else candidate or ""
                candidate = str(candidate)
                if urlsplit(candidate).scheme in {"http", "https"} and urlsplit(candidate).netloc:
                    url = candidate
                    break
            if not title or not url or title.casefold() in seen:
                continue
            seen.add(title.casefold())
            language = text(content.get("lang") or content.get("language"), 12).lower()
            finance = content.get("finance") if isinstance(content.get("finance"), dict) else {}
            related = finance.get("stockTickers") if isinstance(finance.get("stockTickers"), list) else []
            symbols = tuple(text(entry.get("symbol"), 25).upper() for entry in related
                            if isinstance(entry, dict) and entry.get("symbol"))
            result.append(NewsItem(title, publisher, published or "Date not supplied", url, language, symbols))
            if len(result) == 20:
                break
        return result, [] if result else ["Recent provider-linked headlines were unavailable; current events should be checked separately."]
    except Exception:
        return [], ["Recent provider-linked headlines were unavailable; current events should be checked separately."]


def fetch_analyst_trend(ticker: str) -> tuple[list[AnalystPeriod], list[str]]:
    try:
        frame = yf.Ticker(ticker).get_recommendations()
        rows: list[AnalystPeriod] = []
        for _, row in frame.iterrows():
            period = str(row.get("period", ""))
            if period not in {"0m", "-1m", "-2m", "-3m"}:
                continue
            counts = [number(row.get(key)) for key in ("strongBuy", "buy", "hold", "sell", "strongSell")]
            if any(value is None or value < 0 or value != int(value) for value in counts):
                continue
            item = AnalystPeriod(period, *(int(value) for value in counts))
            if item.count:
                rows.append(item)
        rows.sort(key=lambda row: {"0m": 0, "-1m": 1, "-2m": 2, "-3m": 3}[row.period])
        return rows, [] if rows else ["Historical analyst recommendation counts were unavailable."]
    except Exception:
        return [], ["Historical analyst recommendation counts were unavailable."]


def fetch_options(ticker: str) -> tuple[OptionsSnapshot | None, list[str]]:
    """One expiration's open interest, not a directional trade-flow measure."""
    try:
        instrument = yf.Ticker(ticker)
        today = datetime.now(timezone.utc).date()
        dates = []
        for raw in instrument.options:
            try:
                expiry = date.fromisoformat(raw)
                if 7 <= (expiry - today).days <= 90:
                    dates.append(expiry)
            except (ValueError, TypeError):
                continue
        if not dates:
            return None, ["No option expiration 7–90 days away was available from the provider."]
        expiry = min(dates, key=lambda day: abs((day - today).days - 45))
        chain = instrument.option_chain(expiry.isoformat())

        def coverage(frame):
            if frame is None or "openInterest" not in frame.columns:
                return 0, 0, 0
            values = [number(item) for item in frame["openInterest"]]
            valid = [item for item in values if item is not None and item >= 0 and item == int(item)]
            return sum(int(item) for item in valid), len(valid), len(values)

        calls, calls_known, calls_total = coverage(chain.calls)
        puts, puts_known, puts_total = coverage(chain.puts)
        if not calls_total or not puts_total:
            return None, ["The selected options chain did not contain both calls and puts."]
        result = OptionsSnapshot(expiry, calls, puts, calls_known, calls_total, puts_known, puts_total, datetime.now(timezone.utc))
        warning = []
        if calls_known != calls_total or puts_known != puts_total:
            warning = ["Options-chain open interest is incomplete; the put/call ratio is withheld."]
        return result, warning
    except Exception:
        return None, ["Options-chain positioning was unavailable from the market-data provider."]
