"""Reproduce the retrospective subset test from explicitly supplied CSV files."""
from __future__ import annotations

import csv
from datetime import date, datetime, time, timezone
from pathlib import Path

from stock_crawler.analysis import WEIGHTS, _macro_score, _tier
from stock_crawler.backtest import run_backtest
from stock_crawler.models import PricePoint, Snapshot
from stock_crawler.sources.fred import parse_observations
from stock_crawler.utils import normalize_ticker, number


def load_price_csv(path: Path) -> list[PricePoint]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or not {"Date", "Close", "Adj Close"}.issubset(reader.fieldnames):
            raise ValueError("Price CSV must contain Date, Close, and Adj Close columns; adjusted data are not inferred.")
        points: dict[date, PricePoint] = {}
        for row in reader:
            try:
                day = date.fromisoformat((row.get("Date") or "")[:10])
            except ValueError:
                continue
            close, adjusted, volume = number(row.get("Close")), number(row.get("Adj Close")), number(row.get("Volume"))
            if close is not None and close > 0:
                points[day] = PricePoint(day, close, adjusted if adjusted is not None and adjusted > 0 else None,
                                         volume if volume is not None and volume >= 0 else None)
    return [points[day] for day in sorted(points)]


def backtest_from_csv(ticker: str, prices_path: Path, sector: str = "", macro_dir: Path | None = None):
    ticker = normalize_ticker(ticker)
    prices = load_price_csv(prices_path)
    if not prices:
        raise ValueError("No valid daily prices were found.")
    macro_history = {}
    if macro_dir:
        for code in ("DGS10", "UNRATE", "CPIAUCSL", "DCOILWTICO"):
            path = macro_dir / f"{code}.csv"
            if path.exists():
                macro_history[code] = parse_observations(code, path.read_text(encoding="utf-8-sig"))
    snapshot = Snapshot(ticker, ticker, ticker, {"quoteType": "EQUITY", "sector": sector}, prices, {},
                        datetime.combine(prices[-1].date, time.max, timezone.utc), macro_history=macro_history)
    result = run_backtest(snapshot, _macro_score, _tier, WEIGHTS)
    if result is None:
        raise ValueError("Insufficient adjusted-price history for a historical test.")
    return result


def print_backtest(ticker: str, result) -> None:
    print(f"{ticker.upper()}: {result.method} (not the complete scorecard)")
    print("Horizon | correct/calls | hit rate | always-up baseline | partial-range adjusted-return coverage")
    for item in result.horizons:
        hit = f"{item.hit_rate:.1%}" if item.hit_rate is not None else "unavailable"
        baseline = f"{item.always_up_rate:.1%}" if item.always_up_rate is not None else "unavailable"
        within = f"{item.range_hits}/{item.range_observations}" if item.range_observations else "unavailable"
        print(f"{item.months}m | {item.correct_calls}/{item.directional_calls} | {hit} | {baseline} | {within}")
        if item.first_anchor:
            print(f"    Directional anchors {item.first_anchor} through {item.last_anchor}; {item.bullish_calls} bullish, {item.bearish_calls} bearish.")
    for note in result.notes:
        print("Note:", note)
