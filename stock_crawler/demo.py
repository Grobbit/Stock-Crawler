"""Explicitly fictional, network-free data for a reproducible product demo."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

from dateutil.relativedelta import relativedelta

from stock_crawler.models import (AnalystPeriod, AnnualFinancial, Filing, MacroPoint, NewsItem, Official,
                                  OptionsSnapshot, PoliticalContext, PricePoint, Snapshot)


def demo_snapshot() -> Snapshot:
    today = datetime.now(timezone.utc).date()
    days: list[date] = []
    day = today
    while len(days) < 2700:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    days.reverse()
    prices = []
    benchmark = []
    for i, day in enumerate(days):
        recent_index = i - (len(days) - 270)
        base = 82 + recent_index * (0.16 if recent_index >= 0 else 0.011)
        close = round(base + 3.1 * math.sin(recent_index / 13) + 1.1 * math.cos(recent_index / 7), 2)
        volume = round(1_600_000 + 250_000 * (1 + math.sin(i / 9)))
        prices.append(PricePoint(day, close, close, volume))
        market = round(160 + i * 0.09 + 4 * math.sin(i / 40), 2)
        benchmark.append(PricePoint(day, market, market, 40_000_000))
    comparison = today - relativedelta(months=3)
    specs = [
        ("DGS10", "US 10-year Treasury yield", 4.25, 0.18, "%", "pp", "M1"),
        ("DFF", "Effective federal funds rate", 4.33, -0.25, "%", "pp", "M2"),
        ("CPIAUCSL", "US CPI inflation, year over year", 2.8, -0.3, "%", "pp", "M3"),
        ("UNRATE", "US unemployment rate", 4.1, 0.1, "%", "pp", "M4"),
        ("DCOILWTICO", "WTI crude oil", 73.4, -0.08, "USD/barrel", "percent", "M5"),
        ("DTWEXBGS", "Broad US dollar index", 120.0, 0.015, "index", "percent", "M6"),
        ("GDPC1", "US real GDP growth, year over year", 2.4, 0.1, "%", "pp", "M7"),
        ("T10Y2Y", "US 10-year minus 2-year yield spread", 0.35, 0.25, "pp", "pp", "M8"),
        ("BAMLH0A0HYM2", "US high-yield credit spread", 3.5, 0.2, "%", "pp", "M9"),
        ("VIXCLS", "CBOE volatility index", 18.0, -0.05, "index", "percent", "M10"),
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
        "fiftyTwoWeekLow": min(p.close for p in prices[-252:]),
        "fiftyTwoWeekHigh": max(p.close for p in prices[-252:]),
        "shortPercentOfFloat": 0.052,
        "sharesShort": 4_900_000,
        "sharesShortPriorMonth": 4_400_000,
        "shortRatio": 2.4,
        "heldPercentInstitutions": 0.62,
        "dateShortInterest": (datetime.now(timezone.utc) - timedelta(days=15)).timestamp(),
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
        policy_excerpts=("In this fictional example, government contracts and data regulations may influence public-sector demand and compliance costs.",),
    )
    annuals = [
        AnnualFinancial(date(today.year - 1, 12, 31), 2_040_000_000, 440_000_000, 345_000_000, 510_000_000, -120_000_000, 390_000_000),
        AnnualFinancial(date(today.year - 2, 12, 31), 1_720_000_000, 325_000_000, 240_000_000, 380_000_000, -105_000_000, 275_000_000),
        AnnualFinancial(date(today.year - 3, 12, 31), 1_390_000_000, 205_000_000, 150_000_000, 250_000_000, -90_000_000, 160_000_000),
    ]
    headlines = [
        (1, "Fictional Northstar beats earnings expectations"),
        (3, "Fictional Northstar upgrades its cloud planning platform"),
        (5, "Fictional Northstar customers face slower purchasing cycles"),
        (7, "Fictional Northstar wins a new software contract"),
        (10, "Fictional Northstar expands into new markets"),
        (14, "Fictional Northstar faces rising costs"),
        (19, "Fictional Northstar reports strong customer renewal rates"),
        (25, "Fictional Northstar outlines product investments"),
    ]
    news = [NewsItem(title, "Synthetic demo", str(today - timedelta(days=age)), "") for age, title in headlines]
    politicians = PoliticalContext(
        executives=[Official("Avery Vale", "President", "Fictional Civic Party", today - timedelta(days=600)),
                    Official("Morgan Ellis", "Vice president", "Fictional Civic Party", today - timedelta(days=600))],
        leaders=[Official("Casey Reed", "Speaker of the House", "Fictional Civic Party", today - timedelta(days=500))],
        headquarters_senators=[Official("Rowan Lane", "US senator", "Fictional Public Party", today - timedelta(days=900), state="OR"),
                               Official("Drew Park", "US senator", "Fictional Civic Party", today - timedelta(days=900), state="OR")],
        presidential_winners={year: (f"Fictional winner {year}", "Fictional party") for year in range(today.year - 12, today.year + 1) if year % 4 == 0},
        headquarters_state="OR", retrieved_at=datetime.now(timezone.utc), source_url="",
    )
    analysts = [AnalystPeriod("0m", 4, 7, 4, 1, 0), AnalystPeriod("-1m", 4, 6, 5, 1, 0),
                AnalystPeriod("-2m", 3, 6, 6, 1, 0), AnalystPeriod("-3m", 3, 5, 7, 1, 0)]
    options = OptionsSnapshot(today + timedelta(days=45), 102_000, 76_000, 80, 80, 80, 80, datetime.now(timezone.utc))
    return Snapshot(
        requested_ticker="DEMO", ticker="DEMO", name="Northstar Analytics, Inc.", info=info,
        prices=prices, macro=macro, fetched_at=datetime.now(timezone.utc), filing=filing, annuals=annuals, news=news,
        analyst_trend=analysts, options=options, benchmark_prices=benchmark, politics=politicians,
        warnings=["DEMO ONLY: all companies, people, politicians, prices, financials, news, macro observations and filing excerpts in this report are synthetic."],
        demo=True,
    )
