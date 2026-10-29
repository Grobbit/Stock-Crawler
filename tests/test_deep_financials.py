from dataclasses import replace
from datetime import date, timedelta

import pandas as pd

from stock_crawler.analysis import analyze
from stock_crawler.demo import demo_snapshot
from stock_crawler.financial_research import (
    research_insights,
    selected_annuals,
    selected_quarters,
)
from stock_crawler.models import AnnualFinancial, QuarterFinancial
from stock_crawler.sources.market import (
    fetch_annual_financials,
    fetch_quarterly_financials,
)
from stock_crawler.sources.sec_facts import parse_companyfacts


def test_quarterly_history_has_dates_and_preserves_missing_or_nonfinite_data(monkeypatch):
    class FakeTicker:
        def __init__(self, symbol):
            assert symbol == "TEST"
        def get_income_stmt(self, freq, pretty):
            assert freq == "quarterly" and pretty
            return pd.DataFrame({pd.Timestamp("2025-03-31"): [100, 40, 20, float("nan"), 1.5, 10],
                                 pd.Timestamp("2024-03-31"): [80, 35, 15, 7, 1.0, 9]},
                                index=["Total Revenue", "Gross Profit", "Operating Income", "Net Income", "Diluted EPS", "Diluted Average Shares"])
    monkeypatch.setattr("stock_crawler.sources.market.yf.Ticker", FakeTicker)
    rows, warnings = fetch_quarterly_financials("TEST")
    assert not warnings
    assert rows[0].period_end == date(2025, 3, 31)
    assert rows[0].revenue == 100 and rows[0].gross_profit == 40
    assert rows[0].net_income is None and rows[1].diluted_eps == 1
    assert rows[0].revenue_concept == "Yahoo Total Revenue"


def test_annual_statements_include_cash_quality_and_balance_sheet(monkeypatch):
    class FakeTicker:
        def __init__(self, symbol): pass
        def get_income_stmt(self, freq, pretty):
            return pd.DataFrame({pd.Timestamp("2024-12-31"): [100, 40, 20, 12, 10]},
                                index=["Total Revenue", "Gross Profit", "Operating Income", "Net Income", "Diluted Average Shares"])
        def get_cashflow(self, freq, pretty):
            return pd.DataFrame({pd.Timestamp("2024-12-31"): [20, -5, 15, 3]},
                                index=["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow", "Stock Based Compensation"])
        def get_balance_sheet(self, freq, pretty):
            return pd.DataFrame({pd.Timestamp("2024-12-31"): [7, 12, 25, 10]},
                                index=["Cash And Cash Equivalents", "Total Debt", "Current Assets", "Current Liabilities"])
    monkeypatch.setattr("stock_crawler.sources.market.yf.Ticker", FakeTicker)
    annuals, warnings = fetch_annual_financials("TEST")
    assert not warnings
    result = annuals[0]
    assert (result.gross_profit, result.stock_compensation, result.diluted_shares) == (40, 3, 10)
    assert (result.cash, result.total_debt, result.current_assets, result.current_liabilities) == (7, 12, 25, 10)


def sec_fact_fixture():
    def row(start, end, value, filed, form):
        return {"start": start, "end": end, "val": value, "filed": filed, "form": form}
    annual = ("2024-01-01", "2024-12-31", "2025-02-15", "10-K")
    prior = ("2023-01-01", "2023-12-31", "2024-02-15", "10-K")
    q1 = ("2025-01-01", "2025-03-31", "2025-05-01", "10-Q")
    q0 = ("2024-01-01", "2024-03-31", "2024-05-01", "10-Q")
    def values(a, p, q, old):
        return [row(annual[0], annual[1], a, annual[2], annual[3]),
                row(prior[0], prior[1], p, prior[2], prior[3]),
                row(q1[0], q1[1], q, q1[2], q1[3]),
                row(q0[0], q0[1], old, q0[2], q0[3])]
    tags = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": values(1000, 900, 300, 200) + [
            row("2025-01-01", "2025-06-30", 9000, "2025-07-30", "10-Q"),  # six-month YTD, never a quarter
            row("2025-01-01", "2025-03-31", 9999, "2026-01-01", "10-Q"),  # future filing
        ]}},
        "GrossProfit": {"units": {"USD": values(500, 450, 150, 100)}},
        "OperatingIncomeLoss": {"units": {"USD": values(200, 180, 45, 40)}},
        "NetIncomeLoss": {"units": {"USD": values(150, 125, 30, 25)}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": values(220, 180, 60, 40)}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": values(50, 40, 15, 10)}},
        "ShareBasedCompensation": {"units": {"USD": values(12, 10, 3, 2)}},
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": values(11, 10, 11, 10)}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": values(13.6, 12.5, 2.7, 2.5)}},
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
            {"end": "2024-12-31", "val": 500, "filed": "2025-02-15", "form": "10-K"}]}},
    }
    return {"cik": 123, "facts": {"us-gaap": tags}}


def test_sec_companyfacts_use_matched_durations_currency_and_no_future_filings():
    annuals, quarters = parse_companyfacts(sec_fact_fixture(), 123, as_of=date(2025, 8, 1))
    assert [x.period_end for x in annuals] == [date(2024, 12, 31), date(2023, 12, 31)]
    assert annuals[0].revenue == 1000 and annuals[0].cash == 500
    assert annuals[0].operating_cash_flow == 220 and annuals[0].capital_expenditure == -50
    assert annuals[0].free_cash_flow == 170 and annuals[0].stock_compensation == 12
    assert [x.period_end for x in quarters] == [date(2025, 3, 31), date(2024, 3, 31)]
    assert quarters[0].revenue == 300 and quarters[0].diluted_eps == 2.7
    assert quarters[0].period_start == date(2025, 1, 1)
    assert parse_companyfacts(sec_fact_fixture(), 999, as_of=date(2025, 8, 1)) == ([], [])


def test_sec_companyfacts_use_latest_filed_amendment_but_not_future_restatements():
    payload = sec_fact_fixture()
    revenue = payload["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
    revenue.append({"start": "2024-01-01", "end": "2024-12-31", "val": 1020,
                    "filed": "2025-06-01", "form": "10-K/A"})
    revenue.append({"start": "2024-01-01", "end": "2024-12-31", "val": 3000,
                    "filed": "2026-06-01", "form": "10-K/A"})
    annuals, _ = parse_companyfacts(payload, 123, as_of=date(2025, 8, 1))
    assert annuals[0].revenue == 1020


def test_sec_companyfacts_withholds_conflicting_or_ambiguous_currency():
    payload = sec_fact_fixture()
    revenue = payload["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]
    revenue["EUR"] = list(revenue["USD"])
    assert parse_companyfacts(payload, 123, as_of=date(2025, 8, 1)) == ([], [])
    del revenue["EUR"]
    conflict = dict(revenue["USD"][0]); conflict["val"] = 999
    revenue["USD"].append(conflict)
    annuals, _ = parse_companyfacts(payload, 123, as_of=date(2025, 8, 1))
    assert all(item.period_end != date(2024, 12, 31) for item in annuals)


def test_descriptive_research_connects_revenue_margin_cash_and_dilution():
    snapshot = demo_snapshot()
    insights = {item.label: item for item in research_insights(snapshot)}
    growth = insights["Growth versus profitability"]
    assert "+20.0%" in growth.evidence and "-1.0 percentage points" in growth.evidence
    assert growth.direction == "mixed" and "data alone do not establish the cause" in growth.implication
    assert "1.48x" in insights["Earnings versus cash"].evidence
    assert "+3.8%" in insights["Per-share ownership"].evidence
    assert "73.5%" in insights["Where revenue is concentrated"].evidence
    assert "Cloud subscriptions" in insights["Revenue mix shifts"].evidence
    assert "+22.0%" in insights["Revenue mix shifts"].evidence
    assert "peer median" in insights["Business quality versus peers"].evidence
    assert analyze(snapshot).research_insights == list(insights.values())


def test_incompatible_periods_concepts_and_currencies_are_not_compared():
    snapshot = demo_snapshot()
    snapshot.annuals = []
    current = QuarterFinancial(date(2025, 3, 31), 100, operating_income=20,
                               currency="USD", revenue_concept="RevenueA", operating_concept="Op")
    previous = QuarterFinancial(date(2024, 3, 31), 80, operating_income=10,
                                currency="EUR", revenue_concept="RevenueB", operating_concept="Op")
    snapshot.quarters = [current, previous]
    assert all(item.label != "Growth versus profitability" for item in research_insights(snapshot))
    snapshot.quarters[1] = replace(previous, currency="USD")
    assert all(item.label != "Growth versus profitability" for item in research_insights(snapshot))
    snapshot.quarters[1] = replace(previous, currency="USD", revenue_concept="RevenueA", period_end=date(2024, 9, 30))
    assert all(item.label != "Growth versus profitability" for item in research_insights(snapshot))
    snapshot.quarters[1] = replace(previous, currency="USD", revenue_concept="RevenueA", revenue=0)
    assert all(item.label != "Growth versus profitability" for item in research_insights(snapshot))


def test_primary_source_selected_only_when_as_recent_and_no_future_periods():
    snapshot = demo_snapshot()
    current = snapshot.quarters[0]
    old_sec = replace(current, source="SEC XBRL", currency="USD", period_end=current.period_end - timedelta(days=90))
    future_sec = replace(old_sec, period_end=snapshot.fetched_at.date() + timedelta(days=1))
    snapshot.filing = replace(snapshot.filing, sec_quarters=(old_sec, future_sec))
    assert selected_quarters(snapshot)[0].source == "Yahoo Finance"
    equal_sec = replace(old_sec, period_end=current.period_end)
    snapshot.filing = replace(snapshot.filing, sec_quarters=(equal_sec,))
    assert selected_quarters(snapshot)[0].source == "SEC XBRL"
    annual = replace(snapshot.annuals[0], source="SEC XBRL", currency="USD")
    snapshot.filing = replace(snapshot.filing, sec_annuals=(annual,))
    assert selected_annuals(snapshot)[0].source == "SEC XBRL"


def test_cash_conversion_not_calculated_for_zero_or_negative_profit():
    snapshot = demo_snapshot()
    snapshot.annuals = [AnnualFinancial(date(snapshot.fetched_at.year - 1, 12, 31), 100, 10, 0, 20, -5, 15)]
    assert all(item.label != "Earnings versus cash" for item in research_insights(snapshot))
