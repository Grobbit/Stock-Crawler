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
    </p><script>fake customer revenue 99 percent</script></body></html>"""
    customers, risks = extract_excerpts(html)
    assert any("Acme Corporation" in item and "22 percent" in item for item in customers)
    assert any("Supply chain" in item for item in risks)
    assert not any("fake customer" in item for item in customers)


def test_financial_history_parses_periods_and_keeps_missing_fields(monkeypatch):
    frame = pd.DataFrame({pd.Timestamp("2024-12-31"): [100.0, 20.0, float('nan')],
                          pd.Timestamp("2023-12-31"): [80.0, 10.0, 4.0]},
                         index=["Total Revenue", "Operating Income", "Net Income"])
    class FakeTicker:
        def __init__(self, symbol): pass
        def get_income_stmt(self, freq, pretty):
            assert freq == "yearly" and pretty is True
            return frame
    monkeypatch.setattr(market.yf, "Ticker", FakeTicker)
    annuals, warnings = market.fetch_annual_financials("FAKE")
    assert not warnings
    assert annuals[0].period_end == date(2024, 12, 31)
    assert annuals[0].revenue == 100
    assert annuals[0].net_income is None
    assert annuals[1].net_income == 4


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
    info, prices, holdings, warnings = market.fetch_market("FAKE")
    assert info == {} and holdings == []
    assert [p.close for p in prices] == [100.0, 102.0]
    assert any("profile" in warning for warning in warnings)


def test_optional_source_failure_does_not_crash_collection(monkeypatch):
    from stock_crawler import collector
    from stock_crawler.demo import demo_snapshot
    sample = demo_snapshot()
    monkeypatch.setattr(collector, "fetch_market", lambda ticker: (sample.info, sample.prices, [], []))
    def fail(*args, **kwargs):
        raise RuntimeError("provider internal error")
    monkeypatch.setattr(collector, "fetch_macro", fail)
    monkeypatch.setattr(collector, "fetch_filing", fail)
    monkeypatch.setattr(collector, "fetch_annual_financials", fail)
    monkeypatch.setattr(collector, "fetch_news", fail)
    snapshot = collector.collect("FAKE")
    assert snapshot.ticker == "FAKE"
    assert snapshot.prices
    assert snapshot.macro == {}
    assert snapshot.filing is None
    assert len(snapshot.warnings) == 4


def test_cpi_does_not_substitute_a_different_month_for_year_over_year():
    csv = "DATE,CPIAUCSL\n2023-12-01,100\n2025-01-01,106\n"
    with pytest.raises(ValueError, match="Not enough CPI history"):
        parse_series("CPIAUCSL", "CPI", "%", "pp", "M3", csv)
