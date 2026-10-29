from datetime import date

import pandas as pd
import pytest

from stock_crawler.sources.fred import parse_series
from stock_crawler.sources.sec import _valid_agent, extract_excerpts, fetch_filing
from stock_crawler.sources import market


def test_fred_changes_use_dates_not_fixed_number_of_rows():
    csv = "DATE,DGS10\n2024-10-04,4.00\n2024-10-07,.\n2025-01-04,4.45\n"
    point = parse_series("DGS10", "Treasury", "%", "pp", "M1", csv)
    assert point.value == pytest.approx(4.45)
    assert point.change_3m == pytest.approx(0.45)
    assert point.comparison_date == date(2024, 10, 4)


def test_fred_cpi_is_yoy_and_change_is_in_percentage_points():
    csv = "observation_date,CPIAUCSL\n2023-10-01,100\n2024-01-01,101\n2024-10-01,104\n2025-01-01,106\n"
    point = parse_series("CPIAUCSL", "CPI", "%", "pp", "M3", csv)
    assert point.value == pytest.approx((106 / 101 - 1) * 100)
    assert point.change_3m == pytest.approx((106 / 101 - 1) * 100 - 4)
    assert point.change_kind == "pp"


def test_fred_wti_change_is_a_fraction_not_percentage_points():
    csv = "DATE,DCOILWTICO\n2024-10-01,80\n2025-01-01,100\n"
    point = parse_series("DCOILWTICO", "WTI", "USD/barrel", "percent", "M5", csv)
    assert point.change_3m == pytest.approx(0.25)


def test_sec_requires_identifying_user_agent_and_extracts_disclosures():
    assert _valid_agent("Research Team contact@example.com")
    assert not _valid_agent("contact@example.com")
    assert not _valid_agent("Anonymous Research")
    filing, warnings = fetch_filing("AAPL", "")
    assert filing is None and "SEC_USER_AGENT" in warnings[0]
    html = b"""<html><body><p>Our products are sold to many different businesses.
    Our customer Acme Corporation accounted for 22 percent of total revenue during the fiscal year.
    Supply chain disruption could adversely affect our ability to serve customers and deliver products.
    Changes in tariffs and trade regulations could increase our costs and disrupt overseas operations.
    </p><script>fake customer revenue 99 percent</script></body></html>"""
    customers, risks, policy = extract_excerpts(html)
    assert any("Acme Corporation" in item and "22 percent" in item for item in customers)
    assert any("Supply chain" in item for item in risks)
    assert any("tariffs" in item for item in policy)
    assert not any("fake customer" in item for item in customers + risks + policy)


def test_financial_history_parses_periods_and_keeps_missing_fields(monkeypatch):
    frame = pd.DataFrame({pd.Timestamp("2024-12-31"): [100.0, 20.0, float('nan')],
                          pd.Timestamp("2023-12-31"): [80.0, 10.0, 4.0]},
                         index=["Total Revenue", "Operating Income", "Net Income"])
    class FakeTicker:
        def __init__(self, symbol): pass
        def get_income_stmt(self, freq, pretty):
            assert freq == "yearly" and pretty is True
            return frame
        def get_cashflow(self, freq, pretty):
            assert freq == "yearly" and pretty is True
            return pd.DataFrame({pd.Timestamp("2024-12-31"): [30.0, -10.0, 20.0]},
                                index=["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow"])
    monkeypatch.setattr(market.yf, "Ticker", FakeTicker)
    annuals, warnings = market.fetch_annual_financials("FAKE")
    assert not warnings
    assert annuals[0].period_end == date(2024, 12, 31)
    assert annuals[0].revenue == 100
    assert annuals[0].net_income is None
    assert annuals[0].operating_cash_flow == 30
    assert annuals[0].capital_expenditure == -10
    assert annuals[0].free_cash_flow == 20
    assert annuals[1].net_income == 4
    assert annuals[1].free_cash_flow is None


def test_news_parser_rejects_unsafe_urls(monkeypatch):
    class FakeTicker:
        def __init__(self, symbol): pass
        def get_news(self, count):
            return [
                {"content": {"title": "Safe headline", "provider": {"displayName": "News Co"}, "pubDate": "2025-01-01", "canonicalUrl": {"url": "https://example.com/story"}}},
                {"content": {"title": "Bad headline", "canonicalUrl": {"url": "javascript:alert(1)"}}},
            ]
    monkeypatch.setattr(market.yf, "Ticker", FakeTicker)
    news, warnings = market.fetch_news("FAKE")
    assert not warnings
    assert len(news) == 1
    assert news[0].title == "Safe headline"


def test_market_history_uses_daily_closes_and_handles_empty_profile(monkeypatch):
    frame = pd.DataFrame({"Close": [100.0, float('nan'), 102.0]},
                         index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]))
    class FakeTicker:
        def __init__(self, symbol): pass
        def history(self, **kwargs):
            assert kwargs["auto_adjust"] is False
            return frame
        def get_info(self): return {}
    monkeypatch.setattr(market.yf, "Ticker", FakeTicker)
    info, prices, holdings, warnings, provider = market.fetch_market("FAKE")
    assert provider == "Yahoo Finance"
    assert info == {} and holdings == []
    assert [p.close for p in prices] == [100.0, 102.0]
    assert any("profile" in warning for warning in warnings)


def test_optional_source_failure_does_not_crash_collection(monkeypatch):
    from stock_crawler import collector
    from stock_crawler.demo import demo_snapshot
    sample = demo_snapshot()
    monkeypatch.setattr(collector, "fetch_market", lambda ticker: (sample.info, sample.prices, [], [], "Yahoo Finance"))
    def fail(*args, **kwargs):
        raise RuntimeError("provider internal error")
    monkeypatch.setattr(collector, "fetch_macro", fail)
    monkeypatch.setattr(collector, "fetch_filing", fail)
    monkeypatch.setattr(collector, "fetch_annual_financials", fail)
    monkeypatch.setattr(collector, "fetch_news", fail)
    monkeypatch.setattr(collector, "fetch_political_context", fail)
    monkeypatch.setattr(collector, "fetch_benchmark", fail)
    monkeypatch.setattr(collector, "fetch_options", fail)
    monkeypatch.setattr(collector, "fetch_analyst_trend", fail)
    monkeypatch.setattr(collector, "fetch_peers", fail)
    snapshot = collector.collect("FAKE")
    assert snapshot.ticker == "FAKE"
    assert snapshot.prices
    assert snapshot.macro == {}
    assert snapshot.filing is None
    assert len(snapshot.warnings) == 9


def test_cpi_does_not_substitute_a_different_month_for_year_over_year():
    csv = "DATE,CPIAUCSL\n2023-12-01,100\n2025-01-01,106\n"
    with pytest.raises(ValueError, match="Not enough CPI history"):
        parse_series("CPIAUCSL", "CPI", "%", "pp", "M3", csv)


def test_real_gdp_yoy_uses_matching_quarter_and_reports_pp_change():
    csv = "DATE,GDPC1\n2023-10-01,100\n2024-01-01,102\n2024-10-01,105\n2025-01-01,108\n"
    point = parse_series("GDPC1", "Real GDP", "%", "pp", "M7", csv)
    assert point.value == pytest.approx((108 / 102 - 1) * 100)
    assert point.change_3m == pytest.approx((108 / 102 - 1) * 100 - 5)
    with pytest.raises(ValueError, match="GDP history"):
        parse_series("GDPC1", "Real GDP", "%", "pp", "M7", "DATE,GDPC1\n2023-10-01,100\n2025-01-01,108\n")


def test_history_retains_adjusted_close_volume_and_sorts_unique_dates():
    frame = pd.DataFrame({"Close": [110, 100, 0], "Adj Close": [55, None, 50], "Volume": [10, -1, 20]},
                         index=pd.to_datetime(["2025-01-03", "2025-01-02", "2025-01-06"]))
    prices = market._prices_from_frame(frame)
    assert [p.date for p in prices] == [date(2025, 1, 2), date(2025, 1, 3)]
    assert prices[0].adjusted_close is None and prices[0].volume is None
    assert prices[1].adjusted_close == 55 and prices[1].volume == 10


def test_options_chain_reports_incomplete_data_without_fabricating_a_ratio(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from stock_crawler.demo import demo_snapshot
    from stock_crawler.research_context import positioning
    expiry = (datetime.now(timezone.utc).date() + timedelta(days=45)).isoformat()
    class FakeTicker:
        def __init__(self, symbol): pass
        @property
        def options(self): return (expiry,)
        def option_chain(self, selected):
            assert selected == expiry
            return SimpleNamespace(calls=pd.DataFrame({"openInterest": [100, None]}),
                                   puts=pd.DataFrame({"openInterest": [75, 25]}))
    monkeypatch.setattr(market.yf, "Ticker", FakeTicker)
    options, warnings = market.fetch_options("FAKE")
    assert options.call_open_interest == 100 and options.call_known == 1 and options.call_total == 2
    assert options.put_open_interest == 100 and options.put_known == 2
    assert "incomplete" in warnings[0]
    sample = demo_snapshot()
    sample.options = options
    assert positioning(sample)["put_call_oi"] is None


def test_analyst_trend_discards_missing_negative_and_unexpected_periods(monkeypatch):
    class FakeTicker:
        def __init__(self, symbol): pass
        def get_recommendations(self):
            return pd.DataFrame([
                {"period": "0m", "strongBuy": 2, "buy": 3, "hold": 1, "sell": 0, "strongSell": 0},
                {"period": "-1m", "strongBuy": 1, "buy": None, "hold": 1, "sell": 0, "strongSell": 0},
                {"period": "-2m", "strongBuy": -1, "buy": 2, "hold": 1, "sell": 0, "strongSell": 0},
                {"period": "-4m", "strongBuy": 1, "buy": 2, "hold": 1, "sell": 0, "strongSell": 0},
            ])
    monkeypatch.setattr(market.yf, "Ticker", FakeTicker)
    rows, warnings = market.fetch_analyst_trend("FAKE")
    assert not warnings and len(rows) == 1
    assert rows[0].period == "0m" and rows[0].count == 6


def test_news_parser_retains_provider_language_and_related_tickers(monkeypatch):
    class FakeTicker:
        def __init__(self, symbol): pass
        def get_news(self, count):
            assert count == 20
            return [{"content": {"title": "Earnings beat", "lang": "en-US", "pubDate": "2025-01-01",
                                 "canonicalUrl": {"url": "https://example.com/news"},
                                 "finance": {"stockTickers": [{"symbol": "demo"}, {"symbol": "SPY"}]}}}]
    monkeypatch.setattr(market.yf, "Ticker", FakeTicker)
    items, warnings = market.fetch_news("DEMO")
    assert not warnings and len(items) == 1
    assert items[0].language == "en-us"
    assert items[0].related_symbols == ("DEMO", "SPY")
