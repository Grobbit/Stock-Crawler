from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from stock_crawler.analysis import analyze
from stock_crawler.demo import demo_snapshot
from stock_crawler.models import NewsItem, OptionsSnapshot, PoliticalContext, PricePoint
from stock_crawler.research_context import (
    election_reactions,
    general_election_day,
    headline_sentiment,
    next_general_election,
    positioning,
)


def news(title, day, language="", symbols=()):
    return NewsItem(title, "Example News", day.isoformat(), "https://example.org/article", language, symbols)


def test_election_calendar_is_the_tuesday_after_first_monday():
    assert general_election_day(2016) == date(2016, 11, 8)
    assert general_election_day(2020) == date(2020, 11, 3)
    assert general_election_day(2024) == date(2024, 11, 5)
    assert general_election_day(2026) == date(2026, 11, 3)
    assert next_general_election(date(2026, 11, 3)) == date(2026, 11, 3)
    assert next_general_election(date(2026, 11, 4)) == date(2028, 11, 7)


def _event_snapshot():
    snapshot = demo_snapshot()
    snapshot.fetched_at = datetime(2025, 8, 1, tzinfo=timezone.utc)
    days = []
    current = date(2024, 11, 4)  # Last observation before the election.
    while len(days) < 140:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    # Deliberately different adjusted and unadjusted values to catch mix-ups.
    snapshot.prices = [PricePoint(day, 1000 + i, 100 + i, 1000) for i, day in enumerate(days)]
    snapshot.benchmark_prices = [PricePoint(day, 200 + i, 200 + i) for i, day in enumerate(days)]
    snapshot.politics = PoliticalContext(presidential_winners={2024: ("Example Winner", "Example Party")})
    return snapshot


def test_election_event_windows_use_adjusted_closes_and_exact_benchmark_dates():
    snapshot = _event_snapshot()
    [event] = election_reactions(snapshot)
    assert event.election_date == date(2024, 11, 5)
    assert event.anchor_date == date(2024, 11, 4)
    assert event.outcome == "Example Winner (Example Party)"
    assert event.return_10d == pytest.approx(0.10)
    assert event.return_63d == pytest.approx(0.63)
    assert event.return_126d == pytest.approx(1.26)
    assert event.end_63d == snapshot.prices[63].date
    assert event.benchmark_63d == pytest.approx(63 / 200)

    # A missing matching benchmark close must not be replaced by an adjacent day.
    snapshot.benchmark_prices = [p for p in snapshot.benchmark_prices if p.date != event.end_63d]
    assert election_reactions(snapshot)[0].benchmark_63d is None


def test_election_windows_do_not_guess_missing_history_or_future_returns():
    snapshot = _event_snapshot()
    snapshot.prices[0] = replace(snapshot.prices[0], adjusted_close=None)
    assert election_reactions(snapshot) == []

    snapshot = _event_snapshot()
    snapshot.prices = snapshot.prices[:25]
    [event] = election_reactions(snapshot)
    assert event.return_10d is not None
    assert event.return_63d is None and event.return_126d is None
    assert event.benchmark_63d is None

    snapshot.prices = snapshot.prices[1:]  # No pre-election anchor.
    assert election_reactions(snapshot) == []


def test_sentiment_filters_date_language_duplicates_and_issuer_relevance():
    snapshot = demo_snapshot()
    today = snapshot.fetched_at.date()
    snapshot.news = [news(f"Northstar beats estimates {n}", today - timedelta(days=n)) for n in range(1, 5)]
    snapshot.news += [
        news("Another company wins a big contract", today - timedelta(days=1)),
        news("Northstar gana un contrato", today - timedelta(days=1), "es"),
        news("Northstar beats estimates 1", today - timedelta(days=2)),  # duplicate title
        news("Northstar wins new business", today - timedelta(days=31)),
        news("Northstar wins future business", today + timedelta(days=1)),
        news("Northstar reports news", today - timedelta(days=1), "not-a-language"),
    ]
    result = headline_sentiment(snapshot)
    assert len(result.headlines) == 4
    assert result.average is None  # Five eligible articles are required for scoring.

    # A provider ticker tag may establish relevance even without a name in the title.
    snapshot.news.append(news("Earnings upgrade announced", today - timedelta(days=5), "en-US", ("DEMO",)))
    result = headline_sentiment(snapshot)
    assert len(result.headlines) == 5
    assert result.average is not None and result.average > 0


def test_sentiment_trend_and_8_percent_factor_affect_ranges_without_claiming_broad_sentiment():
    positive = demo_snapshot()
    today = positive.fetched_at.date()
    positive.news = [news(f"Northstar beats earnings estimates {i}", today - timedelta(days=age))
                     for i, age in enumerate((1, 2, 3, 10, 15, 20))]
    negative = deepcopy(positive)
    negative.news = [news(f"Northstar bankruptcy and layoffs {i}", today - timedelta(days=age))
                     for i, age in enumerate((1, 2, 3, 10, 15, 20))]
    up, down = analyze(positive), analyze(negative)
    factor_up = next(f for f in up.factors if f.key == "headlines")
    factor_down = next(f for f in down.factors if f.key == "headlines")
    assert factor_up.weight == pytest.approx(0.08)
    assert factor_up.score > 0 > factor_down.score
    assert up.ranges[-1].low > down.ranges[-1].low
    assert up.ranges[-1].high > down.ranges[-1].high

    mixed = deepcopy(positive)
    mixed.news[:3] = negative.news[:3]
    summary = headline_sentiment(mixed)
    assert summary.recent_count == 3 and summary.prior_count == 3
    assert summary.recent_average < summary.prior_average
    mixed.news.pop()  # Only two older headlines: do not claim a trend.
    assert headline_sentiment(mixed).prior_average is None


def test_positioning_requires_complete_data_and_handles_zero_calls():
    snapshot = demo_snapshot()
    snapshot.prices = [replace(point, volume=200 if i >= 80 else 100) for i, point in enumerate(snapshot.prices[-100:])]
    now = snapshot.fetched_at
    snapshot.options = OptionsSnapshot(date(2027, 1, 1), 100, 50, 2, 2, 2, 2, now)
    result = positioning(snapshot)
    assert result["volume_ratio"] == pytest.approx(2.0)
    assert result["vs_ma50"] is not None and result["volatility_63d"] is not None
    assert result["vs_ma200"] is None
    assert result["put_call_oi"] == pytest.approx(0.5)

    snapshot.options = replace(snapshot.options, put_known=1)
    assert positioning(snapshot)["put_call_oi"] is None
    snapshot.options = replace(snapshot.options, put_known=2, call_open_interest=0)
    assert positioning(snapshot)["put_call_oi"] is None
    snapshot.prices[-1] = replace(snapshot.prices[-1], volume=None, adjusted_close=None)
    result = positioning(snapshot)
    assert result["volume_ratio"] is None and result["vs_ma50"] is None and result["volatility_63d"] is None
