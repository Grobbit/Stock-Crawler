"""Explicitly fictional, network-free data for a reproducible product demo."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

from dateutil.relativedelta import relativedelta

from stock_crawler.models import AnnualFinancial, Filing, MacroPoint, NewsItem, PricePoint, Snapshot


def demo_snapshot() -> Snapshot:
    today = datetime.now(timezone.utc).date()
    days: list[date] = []
    day = today
    while len(days) < 270:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    days.reverse()
    prices = [PricePoint(day, round(82 + i * 0.16 + 3.1 * math.sin(i / 13) + 1.1 * math.cos(i / 7), 2)) for i, day in enumerate(days)]
    comparison = today - relativedelta(months=3)
    specs = [
        ("DGS10", "US 10-year Treasury yield", 4.25, 0.18, "%", "pp", "M1"),
        ("DFF", "Effective federal funds rate", 4.33, -0.25, "%", "pp", "M2"),
        ("CPIAUCSL", "US CPI inflation, year over year", 2.8, -0.3, "%", "pp", "M3"),
        ("UNRATE", "US unemployment rate", 4.1, 0.1, "%", "pp", "M4"),
        ("DCOILWTICO", "WTI crude oil", 73.4, -0.08, "USD/barrel", "percent", "M5"),
        ("DTWEXBGS", "Broad US dollar index", 120.0, 0.015, "index", "percent", "M6"),
    ]
    macro = {
        code: MacroPoint(code, label, value, today, change, comparison, unit, kind, "", citation)
        for code, label, value, change, unit, kind, citation in specs
    }
    info = {
        "symbol": "DEMO",
        "longName": "Northstar Analytics, Inc.",
        "shortName": "Northstar Analytics",
        "quoteType": "EQUITY",
        "sector": "Technology",
        "industry": "Software - Infrastructure",
        "country": "United States",
        "city": "Portland",
        "state": "Oregon",
        "currency": "USD",
        "financialCurrency": "USD",
        "fullTimeEmployees": 7400,
        "website": "",
        "longBusinessSummary": (
            "Northstar Analytics is a fictional software company created solely to demonstrate this report. "
            "In this example it sells cloud-based planning and data-analysis subscriptions to businesses and public institutions. "
            "Subscriptions make up the majority of the illustrative revenue mix, while implementation and support contribute the remainder. "
            "Demand in this invented example depends on customer technology budgets, contract renewals and the ability to expand existing accounts."
        ),
        "companyOfficers": [
            {"name": "Alex Morgan", "title": "Chief Executive Officer"},
            {"name": "Jordan Chen", "title": "Chief Financial Officer"},
            {"name": "Taylor Reed", "title": "Chief Technology Officer"},
        ],
        "marketCap": 13_500_000_000,
        "enterpriseValue": 12_800_000_000,
        "totalRevenue": 2_200_000_000,
        "revenueGrowth": 0.22,
        "earningsGrowth": 0.16,
        "grossMargins": 0.72,
        "operatingMargins": 0.23,
        "profitMargins": 0.18,
        "freeCashflow": 420_000_000,
        "totalCash": 1_600_000_000,
        "totalDebt": 900_000_000,
        "currentRatio": 1.8,
        "trailingPE": 31.0,
        "forwardPE": 24.0,
        "returnOnEquity": 0.18,
        "beta": 1.20,
        "dividendYield": None,
        "sharesOutstanding": 108_000_000,
        "recommendationMean": 2.1,
        "recommendationKey": "buy",
        "numberOfAnalystOpinions": 16,
        "targetMeanPrice": 148.0,
        "fiftyTwoWeekLow": min(p.close for p in prices),
        "fiftyTwoWeekHigh": max(p.close for p in prices),
    }
    filing = Filing(
        form="SIMULATED ANNUAL FILING",
        filing_date=today - timedelta(days=50),
        report_date=today - timedelta(days=90),
        url="",
        customer_excerpts=(
            "In this fictional example, no individual customer represented more than 10% of total revenue during the year.",
            "The fictional company sells subscriptions to enterprise and public-sector customers through direct sales and partners.",
        ),
        risk_excerpts=(
            "In this fictional example, longer customer purchasing cycles and intense competition could adversely affect subscription growth.",
            "In this fictional example, a service interruption or cybersecurity incident could damage customer relationships and increase costs.",
        ),
    )
    annuals = [
        AnnualFinancial(date(today.year - 1, 12, 31), 2_040_000_000, 440_000_000, 345_000_000),
        AnnualFinancial(date(today.year - 2, 12, 31), 1_720_000_000, 325_000_000, 240_000_000),
        AnnualFinancial(date(today.year - 3, 12, 31), 1_390_000_000, 205_000_000, 150_000_000),
    ]
    news = [
        NewsItem("Fictional Northstar expands its cloud planning platform", "Synthetic demo", str(today - timedelta(days=10)), ""),
        NewsItem("Fictional customers face longer technology purchasing cycles", "Synthetic demo", str(today - timedelta(days=30)), ""),
    ]
    return Snapshot(
        requested_ticker="DEMO", ticker="DEMO", name="Northstar Analytics, Inc.", info=info,
        prices=prices, macro=macro, fetched_at=datetime.now(timezone.utc), filing=filing, annuals=annuals, news=news,
        warnings=["DEMO ONLY: every company, person, price, financial figure, macro observation and filing excerpt in this report is synthetic."],
        demo=True,
    )
