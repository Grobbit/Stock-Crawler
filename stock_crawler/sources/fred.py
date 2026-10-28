"""Fetch public FRED observations without an API key.

A macro point's change is always measured against the nearest observation at
or before three calendar months ago, never against an assumed fixed row count.
"""
from __future__ import annotations

import csv
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import requests
from dateutil.relativedelta import relativedelta

from stock_crawler.models import MacroPoint
from stock_crawler.utils import number

# code, label, displayed unit, change kind, citation id
SERIES = (
    ("DGS10", "US 10-year Treasury yield", "%", "pp", "M1"),
    ("DFF", "Effective federal funds rate", "%", "pp", "M2"),
    ("CPIAUCSL", "US CPI inflation, year over year", "%", "pp", "M3"),
    ("UNRATE", "US unemployment rate", "%", "pp", "M4"),
    ("DCOILWTICO", "WTI crude oil", "USD/barrel", "percent", "M5"),
    ("DTWEXBGS", "Broad US dollar index", "index", "percent", "M6"),
)


def _at_or_before(points: list[tuple[date, float]], target: date, max_gap: int = 45) -> tuple[date, float] | None:
    candidates = [point for point in points if point[0] <= target]
    if not candidates:
        return None
    result = candidates[-1]
    return result if (target - result[0]).days <= max_gap else None


def _same_month(points: list[tuple[date, float]], target: date) -> tuple[date, float] | None:
    # CPI year-over-year must compare the same calendar month, not merely a
    # nearby earlier observation (which could silently become 13-month growth).
    matches = [point for point in points if point[0].year == target.year and point[0].month == target.month]
    return matches[-1] if matches else None


def parse_series(code: str, label: str, unit: str, kind: str, source_id: str, csv_text: str) -> MacroPoint:
    points: list[tuple[date, float]] = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        try:
            observation_date = date.fromisoformat(row.get("observation_date") or row.get("DATE") or "")
        except (ValueError, TypeError):
            continue
        value = number(row.get(code))
        if value is not None:
            points.append((observation_date, value))
    points.sort(key=lambda point: point[0])
    if not points:
        raise ValueError("No observations")
    latest_date, latest = points[-1]
    prior = _at_or_before(points, latest_date - relativedelta(months=3))
    comparison_date = prior[0] if prior else None

    if code == "CPIAUCSL":
        year_ago = _same_month(points, latest_date - relativedelta(years=1))
        if not year_ago or year_ago[1] <= 0:
            raise ValueError("Not enough CPI history to calculate year-over-year inflation")
        value = (latest / year_ago[1] - 1) * 100
        change = None
        if prior:
            prior_year = _same_month(points, prior[0] - relativedelta(years=1))
            if prior_year and prior_year[1] > 0:
                prior_yoy = (prior[1] / prior_year[1] - 1) * 100
                change = value - prior_yoy
    else:
        value = latest
        change = None
        if prior:
            if kind == "percent" and prior[1] != 0:
                change = latest / prior[1] - 1
            elif kind == "pp":
                change = latest - prior[1]

    return MacroPoint(
        code=code,
        label=label,
        value=value,
        as_of=latest_date,
        change_3m=change,
        comparison_date=comparison_date,
        unit=unit,
        change_kind=kind,
        source_url=f"https://fred.stlouisfed.org/series/{code}",
        source_id=source_id,
    )


def _fetch_one(spec: tuple[str, str, str, str, str]) -> MacroPoint:
    code, label, unit, kind, source_id = spec
    response = requests.get(
        "https://fred.stlouisfed.org/graph/fredgraph.csv",
        params={"id": code},
        headers={"User-Agent": "StockCrawler/1.0 (research application)"},
        timeout=(5, 15),
    )
    response.raise_for_status()
    return parse_series(code, label, unit, kind, source_id, response.text)


def fetch_macro() -> tuple[dict[str, MacroPoint], list[str]]:
    results: dict[str, MacroPoint] = {}
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=len(SERIES), thread_name_prefix="fred") as executor:
        futures = {executor.submit(_fetch_one, spec): spec for spec in SERIES}
        for future in as_completed(futures):
            spec = futures[future]
            try:
                point = future.result()
                results[point.code] = point
            except (requests.RequestException, ValueError, KeyError, OSError):
                failed.append(spec[0])
    warnings: list[str] = []
    if failed:
        warnings.append("FRED observations unavailable for: " + ", ".join(sorted(failed)) + ".")
    return results, warnings
