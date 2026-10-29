from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from stock_crawler.analysis import analyze
from stock_crawler.demo import demo_snapshot
from stock_crawler.models import PricePoint
from stock_crawler.sources import market, stooq


@pytest.mark.parametrize("symbol,expected", [("AAPL", "aapl.us"), ("SPY", "spy.us"), ("BRK-B", None),
                                              ("VOD.L", None), ("BTC-USD", None), ("^GSPC", None),
                                              ("EURUSD=X", None), ("lower", None)])
def test_stooq_mapping_is_deliberately_narrow(symbol, expected):
    assert stooq.stooq_symbol(symbol) == expected


def test_stooq_parser_sorts_deduplicates_and_never_fabricates_adjusted_close(monkeypatch):
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    csv = ("Date,Open,High,Low,Close,Volume\n"
           f"{today},1,1,1,101,1000\n{yesterday},1,1,1,100,500\n"
           f"{today},1,1,1,102,1100\nnot-a-date,1,1,1,500,1\n")
    def get(url, params, headers, timeout):
        assert url == "https://stooq.com/q/d/l/" and params["s"] == "aapl.us"
        return SimpleNamespace(content=csv.encode(), text=csv, raise_for_status=lambda: None)
    monkeypatch.setattr(stooq.requests, "get", get)
    prices = stooq.fetch_stooq_prices("AAPL")
    assert [p.date for p in prices] == [yesterday, today]
    assert [p.close for p in prices] == [100, 102]
    assert all(p.adjusted_close is None for p in prices)
    snapshot = demo_snapshot()
    snapshot.prices = [replace(p, adjusted_close=None) for p in snapshot.prices]
    snapshot.price_source = "Stooq"
    result = analyze(snapshot)
    assert not result.ranges and result.backtest is None


def test_yahoo_failure_uses_stooq_and_rejects_non_usd_profile(monkeypatch):
    point = PricePoint(date(2025, 1, 2), 100, None, 1000)
    class FakeTicker:
        def __init__(self, symbol): pass
        def history(self, **kwargs): raise RuntimeError("Yahoo unavailable")
        def get_info(self): return {"quoteType": "EQUITY", "currency": "USD"}
    monkeypatch.setattr(market.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(market, "fetch_stooq_prices", lambda ticker: [point])
    _, prices, _, warnings, provider = market.fetch_market("AAPL")
    assert provider == "Stooq" and prices == [point]
    assert any("adjusted" in warning and "withheld" in warning for warning in warnings)
    monkeypatch.setattr(FakeTicker, "get_info", lambda self: {"quoteType": "EQUITY", "currency": "EUR"})
    with pytest.raises(market.MarketDataError, match="non-USD"):
        market.fetch_market("AAPL")
    monkeypatch.setattr(market, "fetch_stooq_prices", lambda ticker: [])
    with pytest.raises(market.MarketDataError, match="Could not retrieve"):
        market.fetch_market("AAPL")


def test_current_utc_day_is_not_mistaken_for_a_final_close(monkeypatch):
    import pandas as pd
    today = datetime.now(timezone.utc).date()
    previous = today - timedelta(days=1)
    frame = pd.DataFrame({"Close": [100, 120], "Adj Close": [100, 120]},
                         index=pd.to_datetime([previous, today]))
    class FakeTicker:
        def __init__(self, symbol): pass
        def history(self, **kwargs): return frame
        def get_info(self): return {"currency": "USD", "quoteType": "EQUITY"}
    monkeypatch.setattr(market.yf, "Ticker", FakeTicker)
    _, prices, _, warnings, source = market.fetch_market("AAPL")
    assert source == "Yahoo Finance" and [p.date for p in prices] == [previous]
    assert any("may not be final" in warning for warning in warnings)


def test_stooq_rejects_incompatible_yahoo_instrument_type(monkeypatch):
    point = PricePoint(date(2025, 1, 2), 100)
    class FakeTicker:
        def __init__(self, symbol): pass
        def history(self, **kwargs): raise ValueError("unavailable")
        def get_info(self): return {"currency": "USD", "quoteType": "CRYPTOCURRENCY"}
    monkeypatch.setattr(market.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(market, "fetch_stooq_prices", lambda ticker: [point])
    with pytest.raises(market.MarketDataError, match="instrument type"):
        market.fetch_market("BTC")
