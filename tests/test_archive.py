import math
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from stock_crawler.analysis import analyze
from stock_crawler.archive import MODEL_REVISION, load_signals, record_signal
from stock_crawler.backtest import run_recorded_backtest
from stock_crawler.demo import demo_snapshot
from stock_crawler.models import PricePoint, RecordedSignal


def utc(day):
    return datetime.combine(day, datetime.min.time(), timezone.utc)


def test_archive_is_local_frozen_by_day_versioned_and_excludes_demo(tmp_path):
    path = tmp_path / "history.sqlite"
    snapshot = demo_snapshot()
    analysis = analyze(snapshot)
    assert not record_signal(snapshot, analysis, path, utc(date(2023, 1, 1)))
    assert not path.exists()  # Demo inputs are never mistaken for real forecasts.
    snapshot.demo = False
    assert not record_signal(snapshot, analysis, path, utc(date(2023, 1, 1)))
    analysis.verdict, analysis.score = "Bearish", -0.8
    assert not record_signal(snapshot, analysis, path, utc(date(2023, 1, 1)) + timedelta(hours=1))
    records, warnings = load_signals(snapshot.ticker, path)
    assert not warnings and len(records) == 1
    assert records[0].verdict == "Bullish" and records[0].score > 0  # first run is immutable
    with sqlite3.connect(path) as db:
        row = db.execute("SELECT model_revision, factors_json FROM signals").fetchone()
        assert row[0] == MODEL_REVISION and '"key":"macro"' in row[1]
        db.execute("UPDATE signals SET model_revision='other-revision'")
    assert load_signals(snapshot.ticker, path)[0] == []


def test_failed_or_insufficient_archive_does_not_fake_a_signal(tmp_path):
    snapshot = demo_snapshot()
    snapshot.demo = False
    snapshot.macro = {}
    analysis = analyze(snapshot)
    path = tmp_path / "history.sqlite"
    assert not record_signal(snapshot, analysis, path)
    assert not path.exists()
    path.write_text("not a database")
    assert load_signals(snapshot.ticker, path)[0] == []
    assert "could not be read" in load_signals(snapshot.ticker, path)[1][0]


def test_archived_full_scorecard_uses_next_close_mature_nonoverlapping_windows():
    snapshot = demo_snapshot()
    start = date(2023, 1, 1)
    snapshot.prices = []
    day = start
    index = 0
    while day <= date(2024, 12, 31):
        if day.weekday() < 5:
            value = 100 * math.exp(0.001 * index)
            snapshot.prices.append(PricePoint(day, value, value))
            index += 1
        day += timedelta(days=1)
    snapshot.fetched_at = utc(date(2024, 12, 31)) + timedelta(hours=23)
    snapshot.recorded_signals = [
        RecordedSignal(utc(date(2023, 3, 1)), 0.7, "Bullish"),
        RecordedSignal(utc(date(2023, 3, 15)), -0.8, "Bearish"),  # overlaps first outcome
        RecordedSignal(utc(date(2023, 9, 1)), -0.5, "Bearish"),
        RecordedSignal(utc(date(2023, 10, 1)), 0.0, "Mixed / neutral"),
        RecordedSignal(utc(date(2025, 1, 1)), 0.9, "Bullish"),  # future signal is ignored
    ]
    result = run_recorded_backtest(snapshot)
    assert result.method == "Locally archived full-scorecard verdicts"
    for horizon in result.horizons:
        assert horizon.first_anchor == date(2023, 3, 2)  # never the report-date close
        assert horizon.directional_calls == 2
        assert horizon.correct_calls == 1
        assert horizon.always_up_correct == 2
        assert horizon.hit_rate == pytest.approx(0.5)
        assert horizon.always_up_rate == pytest.approx(1.0)
    snapshot.prices = [point for point in snapshot.prices if point.date <= date(2023, 4, 5)]
    short = run_recorded_backtest(snapshot)
    assert short.horizons[0].directional_calls == 1
    assert short.horizons[1].directional_calls == 0
    assert short.horizons[2].directional_calls == 0


def test_archive_does_not_evaluate_nonfinite_prices_or_inconsistent_verdicts():
    snapshot = demo_snapshot()
    snapshot.recorded_signals = [RecordedSignal(utc(snapshot.price_date - timedelta(days=100)), -0.8, "Bullish")]
    result = run_recorded_backtest(snapshot)
    assert all(item.directional_calls == 0 for item in result.horizons)
