"""A deliberately limited rolling-origin test of observable scorecard factors.

Past fundamentals, peer sets, analyst opinions and headlines are not available
point-in-time from the free feeds. Never reuse today's values in the past.
The retrospective test therefore evaluates momentum, and macro when historical
series are available, using exactly their live weights and thresholds. It is
NOT a backtest of the full current scorecard or its evidence gates.
"""
from __future__ import annotations

import math
import statistics
from bisect import bisect_left, bisect_right
from datetime import date, timedelta
from typing import Callable

from dateutil.relativedelta import relativedelta

from stock_crawler.models import BacktestHorizon, BacktestResult, MacroPoint, PricePoint, Snapshot
from stock_crawler.sources.fred import SERIES, point_from_observations

# Conservative calendar-day release delays. FRED CSVs contain latest revisions,
# not historical ALFRED vintages; these lags cannot remove revision lookahead.
PUBLICATION_LAG = {"DGS10": 1, "DCOILWTICO": 1, "UNRATE": 60, "CPIAUCSL": 60}
MIN_MACRO_ORIGINS = 12


def realized_volatility(prices: list[PricePoint], end_index: int | None = None) -> float | None:
    """Annualized stdev of 63 consecutive daily adjusted-close log returns."""
    end = len(prices) - 1 if end_index is None else end_index
    if end < 63 or end >= len(prices):
        return None
    window = prices[end - 63:end + 1]
    if any((window[i].date - window[i - 1].date).days > 10 for i in range(1, len(window))):
        return None
    values = [point.adjusted_close for point in window]
    if not all(value is not None and math.isfinite(value) and value > 0 for value in values):
        return None
    returns = [math.log(values[i] / values[i - 1]) for i in range(1, len(values))]
    value = statistics.stdev(returns) * math.sqrt(252)
    # Suppress degenerate/unusable data rather than presenting a fake range.
    return value if math.isfinite(value) and 0 < value <= 3 else None


def range_log_parameters(score: float, volatility: float, months: int) -> tuple[float, float]:
    """A heuristic drift and one historical-volatility shock, not a CI."""
    return 0.16 * score * months / 6, volatility * math.sqrt(months / 12)


def historical_macro(snapshot: Snapshot, as_of: date) -> dict[str, MacroPoint]:
    specs = {row[0]: row for row in SERIES}
    result: dict[str, MacroPoint] = {}
    for code, lag in PUBLICATION_LAG.items():
        observations = snapshot.macro_history.get(code, [])
        available = [item for item in observations if item[0] <= as_of - timedelta(days=lag)]
        if not available:
            continue
        try:
            result[code] = point_from_observations(*specs[code], available)
        except ValueError:
            continue
    return result


def run_backtest(snapshot: Snapshot, macro_score: Callable, tier: Callable,
                 weights: dict[str, float]) -> BacktestResult | None:
    prices = [point for point in snapshot.prices if point.date <= snapshot.fetched_at.date()]
    if len(prices) < 190:
        return None
    dates = [point.date for point in prices]
    earliest = dates[-1] - relativedelta(years=10)
    origins = []
    # Last observed trading date of each completed month. A partially completed
    # current month is excluded, even if a current quote exists.
    for i in range(63, len(prices) - 1):
        current = prices[i]
        if current.date < earliest or (dates[i + 1].year, dates[i + 1].month) == (current.date.year, current.date.month):
            continue
        lookback = current.date - relativedelta(months=6)
        earlier_index = bisect_right(dates, lookback) - 1
        if earlier_index < 0 or (lookback - dates[earlier_index]).days > 10:
            continue
        old, new = prices[earlier_index].adjusted_close, current.adjusted_close
        if old is None or new is None or not math.isfinite(old) or not math.isfinite(new) or old <= 0 or new <= 0:
            continue
        momentum = tier(new / old - 1, (0.20, 0.05, -0.05, -0.20))
        macro, _ = macro_score(snapshot, macro_override=historical_macro(snapshot, current.date), as_of=current.date)
        origins.append((i, momentum, macro, realized_volatility(prices, i)))
    if not origins:
        return None

    use_macro = sum(item[2] is not None for item in origins) >= MIN_MACRO_ORIGINS
    if use_macro:
        origins = [item for item in origins if item[2] is not None]
    horizons = []
    for months in (1, 3, 6):
        calls = hits = up_hits = bulls = bears = flats = range_n = range_hits = 0
        first = last = None
        next_available = date.min
        for index, momentum, macro, volatility in origins:
            start = prices[index]
            if start.date < next_available:
                continue
            wanted = start.date + relativedelta(months=months)
            end_index = bisect_left(dates, wanted)
            if end_index >= len(prices) or (dates[end_index] - wanted).days > 10:
                continue
            end = prices[end_index]
            if end.adjusted_close is None or not math.isfinite(end.adjusted_close) or end.adjusted_close <= 0:
                continue
            next_available = end.date  # Non-overlapping windows per horizon.
            if use_macro:
                score = (weights["momentum"] * momentum + weights["macro"] * macro) / (weights["momentum"] + weights["macro"])
            else:
                score = momentum
            realized = end.adjusted_close / start.adjusted_close - 1
            if volatility is not None:
                drift, width = range_log_parameters(score, volatility, months)
                range_n += 1
                if drift - width <= math.log1p(realized) <= drift + width:
                    range_hits += 1
            direction = 1 if score >= 0.20 else -1 if score <= -0.20 else 0
            if direction == 0:
                continue
            if abs(realized) < 1e-12:
                flats += 1
                continue
            calls += 1
            bulls += direction > 0
            bears += direction < 0
            hits += (direction > 0 and realized > 0) or (direction < 0 and realized < 0)
            up_hits += realized > 0
            first = first or start.date
            last = start.date
        horizons.append(BacktestHorizon(months, calls, hits, up_hits, bulls, bears, flats,
                                       range_n, range_hits, first, last))
    notes = [
        "Retrospective test of only the historically reconstructable scorecard subset, not the full live verdict, quality gates, peer selection, fundamentals, analyst views or headline sentiment.",
        "Non-overlapping month-end origins per horizon; adjusted-close total returns include distributions where the provider adjusts for them. Neutral calls and exactly flat outcomes are excluded from directional hit rate.",
        "No transaction costs, delistings or portfolio effects. One ticker is not a representative universe. Results are descriptive, not independently validated probabilities.",
    ]
    if use_macro:
        notes.append("Macro uses today's revised FRED history with conservative assumed publication lags and today's sector classification. Revisions and classification changes can introduce hindsight; this is not a strict vintage-correct backtest.")
    else:
        notes.append("Historical macro was insufficient for a consistent test, so only the price-momentum factor is tested.")
    method = "Momentum + macro subset" if use_macro else "Momentum-only subset"
    return BacktestResult(method, ("momentum", "macro") if use_macro else ("momentum",), tuple(horizons), tuple(notes))


def run_recorded_backtest(snapshot: Snapshot) -> BacktestResult | None:
    """Evaluate frozen full-scorecard verdicts, only after their outcomes mature.

    Entry is the first observed close strictly after the UTC report date. This
    deliberately avoids treating a verdict assembled after a close as if it
    had been available at that close. Signals are never rewritten with present
    financial data. Results depend on the user's local archive and cannot be
    generalized to all tickers or users.
    """
    if not snapshot.recorded_signals or not snapshot.prices:
        return None
    prices = [p for p in snapshot.prices if p.date <= snapshot.fetched_at.date()]
    dates = [p.date for p in prices]
    records = sorted(snapshot.recorded_signals, key=lambda item: item.observed_at)
    horizons = []
    for months in (1, 3, 6):
        calls = hits = up_hits = bulls = bears = flats = 0
        first = last = None
        next_available = date.min
        for signal in records:
            signal_day = signal.observed_at.date()
            if signal.observed_at > snapshot.fetched_at or signal.verdict not in {"Bullish", "Bearish"}:
                continue
            if (signal.verdict == "Bullish" and signal.score < 0.20) or (signal.verdict == "Bearish" and signal.score > -0.20):
                continue
            start_idx = bisect_right(dates, signal_day)
            if start_idx >= len(prices) or (dates[start_idx] - signal_day).days > 10:
                continue
            start = prices[start_idx]
            if start.date < next_available or start.adjusted_close is None or not math.isfinite(start.adjusted_close) or start.adjusted_close <= 0:
                continue
            wanted = start.date + relativedelta(months=months)
            end_idx = bisect_left(dates, wanted)
            if end_idx >= len(prices) or (dates[end_idx] - wanted).days > 10:
                continue
            end = prices[end_idx]
            if end.adjusted_close is None or not math.isfinite(end.adjusted_close) or end.adjusted_close <= 0:
                continue
            next_available = end.date
            realized = end.adjusted_close / start.adjusted_close - 1
            if abs(realized) < 1e-12:
                flats += 1
                continue
            bullish = signal.verdict == "Bullish"
            calls += 1
            bulls += bullish
            bears += not bullish
            hits += (bullish and realized > 0) or (not bullish and realized < 0)
            up_hits += realized > 0
            first = first or start.date
            last = start.date
        horizons.append(BacktestHorizon(months, calls, hits, up_hits, bulls, bears, flats, 0, 0, first, last))
    return BacktestResult(
        "Locally archived full-scorecard verdicts", ("full scorecard",), tuple(horizons),
        ("Frozen verdicts are recorded prospectively when live reports are generated; the first report per ticker and UTC day is retained.",
         "Returns begin at the first available close after the report date and end at the first close on or after the horizon. Windows are non-overlapping, and neutral calls and flat outcomes are excluded.",
         "Only this installation's archived reports and this exact model revision are evaluated. The sample is user-selected, may be tiny and is not a representative market backtest."),
    )
