import math
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from stock_crawler.analysis import WEIGHTS, _macro_score, _tier
from stock_crawler.backtest import historical_macro, run_backtest
from stock_crawler.backtest_cli import backtest_from_csv, load_price_csv
from stock_crawler.demo import demo_snapshot
from stock_crawler.models import PricePoint


def trend_prices(start: date, count: int, *, direction: int = 1):
    points = []
    day = start
    i = 0
    while len(points) < count:
        if day.weekday() < 5:
            value = 100 * math.exp(direction * 0.002 * i + 0.006 * math.sin(i / 4))
            points.append(PricePoint(day, value, value, 1000))
            i += 1
        day += timedelta(days=1)
    return points


def test_retrospective_hits_baseline_nonoverlap_and_range_counts():
    snapshot = demo_snapshot()
    snapshot.prices = trend_prices(date(2020, 1, 1), 1100)
    snapshot.fetched_at = datetime.combine(snapshot.prices[-1].date, datetime.max.time(), timezone.utc)
    snapshot.macro_history = {}
    result = run_backtest(snapshot, _macro_score, _tier, WEIGHTS)
    assert result.method == "Momentum-only subset" and result.factors == ("momentum",)
    for item in result.horizons:
        assert item.directional_calls > 0
        assert item.bullish_calls == item.directional_calls and item.bearish_calls == 0
        assert item.correct_calls == item.directional_calls == item.always_up_correct
        assert item.hit_rate == pytest.approx(1.0)
        assert 0 <= item.range_hits <= item.range_observations
    assert result.horizons[2].directional_calls < result.horizons[1].directional_calls < result.horizons[0].directional_calls
    assert any("not the full live verdict" in note for note in result.notes)


def test_neutral_and_flat_series_do_not_create_a_fabricated_hit_rate():
    snapshot = demo_snapshot()
    snapshot.prices = [replace(p, close=100, adjusted_close=100) for p in trend_prices(date(2020, 1, 1), 800)]
    snapshot.fetched_at = datetime.combine(snapshot.prices[-1].date, datetime.max.time(), timezone.utc)
    snapshot.macro_history = {}
    result = run_backtest(snapshot, _macro_score, _tier, WEIGHTS)
    assert result is not None
    for item in result.horizons:
        assert item.directional_calls == 0 and item.hit_rate is None and item.always_up_rate is None
        assert item.range_observations == 0


def test_future_price_observations_do_not_change_a_test_as_of_an_earlier_date():
    snapshot = demo_snapshot()
    snapshot.prices = trend_prices(date(2020, 1, 1), 850)
    snapshot.fetched_at = datetime.combine(snapshot.prices[-1].date, datetime.max.time(), timezone.utc)
    snapshot.macro_history = {}
    original = run_backtest(snapshot, _macro_score, _tier, WEIGHTS)
    with_future = deepcopy(snapshot)
    last = snapshot.prices[-1].date
    with_future.prices += [PricePoint(last + timedelta(days=i), 5000, 5000) for i in range(1, 150)]
    assert run_backtest(with_future, _macro_score, _tier, WEIGHTS) == original


def test_historical_macro_excludes_unreleased_future_observations():
    snapshot = demo_snapshot()
    snapshot.macro_history = {
        "DGS10": [(date(2024, 1, 1), 3.0), (date(2024, 4, 1), 4.0), (date(2024, 4, 20), 50.0)],
        "UNRATE": [(date(2023, 11, 1), 3.0), (date(2024, 2, 1), 4.0), (date(2024, 3, 1), 50.0)],
        "CPIAUCSL": [(date(2023, 2, 1), 100.0), (date(2024, 2, 1), 105.0), (date(2024, 3, 1), 500.0)],
    }
    macro = historical_macro(snapshot, date(2024, 4, 20))
    assert macro["DGS10"].as_of == date(2024, 4, 1)  # one-day assumed release lag
    assert macro["DGS10"].value == 4
    assert macro["UNRATE"].as_of == date(2024, 2, 1)  # sixty-day monthly lag
    assert macro["UNRATE"].value == 4
    assert macro["CPIAUCSL"].as_of == date(2024, 2, 1)
    assert macro["CPIAUCSL"].value == pytest.approx(5.0)
    snapshot.macro_history["DGS10"].append((date(2027, 1, 1), -999))
    assert historical_macro(snapshot, date(2024, 4, 20)) == macro


def test_demo_macro_backtest_has_explicit_revision_and_subset_warnings():
    snapshot = demo_snapshot()
    result = run_backtest(snapshot, _macro_score, _tier, WEIGHTS)
    assert result.method == "Momentum + macro subset"
    assert result.factors == ("momentum", "macro")
    assert any("revised FRED" in note and "hindsight" in note for note in result.notes)


def test_price_csv_requires_explicit_adjusted_close_and_reproduces_results(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("Date,Close\n2024-01-01,100\n")
    with pytest.raises(ValueError, match="Adj Close"):
        load_price_csv(bad)
    path = tmp_path / "history.csv"
    points = trend_prices(date(2020, 1, 1), 900)
    path.write_text("Date,Close,Adj Close,Volume\n" + "\n".join(
        f"{p.date},{p.close},{p.adjusted_close},{p.volume}" for p in points
    ))
    result = backtest_from_csv("AAPL", path, "Technology")
    assert result.method == "Momentum-only subset"
    assert result.horizons[0].directional_calls > 0
    assert result.horizons[0].hit_rate == pytest.approx(1)
