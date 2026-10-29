"""Select comparable, entity-wide US-GAAP facts from SEC Company Facts.

Period start/end, units and source concepts are retained. No quarter is inferred
from a year-to-date value and no revenue concepts are silently spliced together.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from stock_crawler.models import AnnualFinancial, QuarterFinancial
from stock_crawler.utils import number

DURATION_TAGS = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"),
    "gross": ("GrossProfit",),
    "operating": ("OperatingIncomeLoss",),
    "net": ("NetIncomeLoss", "ProfitLoss"),
    "operating_cash": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "stock_comp": ("ShareBasedCompensation",),
    "diluted_shares": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    "diluted_eps": ("EarningsPerShareDiluted",),
}
INSTANT_TAGS = {
    "cash": ("CashAndCashEquivalentsAtCarryingValue",),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
}
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
ALL_FORMS = ANNUAL_FORMS | {"10-Q", "10-Q/A"}


def _entries(gaap: dict, tag: str, unit: str, *, duration: str, today: date):
    concept = gaap.get(tag, {})
    units = concept.get("units", {}) if isinstance(concept, dict) else {}
    values = units.get(unit, []) if isinstance(units, dict) else []
    if not isinstance(values, list):
        return
    for item in values:
        if not isinstance(item, dict) or item.get("form") not in (ANNUAL_FORMS if duration == "annual" else ALL_FORMS):
            continue
        value = number(item.get("val"))
        try:
            end = date.fromisoformat(item["end"])
            filed = date.fromisoformat(item["filed"])
            start = date.fromisoformat(item["start"]) if duration != "instant" else None
        except (TypeError, ValueError, KeyError):
            continue
        if value is None or filed > today or end > today or filed < end:
            continue
        if duration == "annual" and not 330 <= (end - start).days <= 400:
            continue
        if duration == "quarter" and not 65 <= (end - start).days <= 110:
            continue
        yield (start, end), filed, value


def _series(gaap: dict, tags: tuple[str, ...], unit: str, duration: str, today: date):
    # Most recently filed observation wins; same-day conflicting facts for the
    # same concept are withheld. A defined tag priority breaks same-day ties
    # between concepts without adding different concepts together.
    selected: dict[tuple[date | None, date], tuple[date, int, str, set[float]]] = {}
    for priority, tag in enumerate(tags):
        for period, filed, value in _entries(gaap, tag, unit, duration=duration, today=today) or ():
            current = selected.get(period)
            if current is None or filed > current[0] or (filed == current[0] and priority < current[1]):
                selected[period] = (filed, priority, tag, {value})
            elif filed == current[0] and priority == current[1]:
                current[3].add(value)
    return {period: (next(iter(values)), tag) for period, (_, _, tag, values) in selected.items() if len(values) == 1}


def _unit(gaap: dict, today: date) -> str:
    candidates: dict[str, date] = {}
    for tag in DURATION_TAGS["revenue"]:
        concept = gaap.get(tag, {})
        units = concept.get("units", {}) if isinstance(concept, dict) else {}
        if not isinstance(units, dict):
            continue
        for unit in units:
            if not re.fullmatch(r"[A-Z]{3}", unit):
                continue
            for duration in ("annual", "quarter"):
                for (_start, end), _filed, _value in _entries(gaap, tag, unit, duration=duration, today=today) or ():
                    candidates[unit] = max(candidates.get(unit, date.min), end)
    if not candidates:
        return ""
    latest = max(candidates.values())
    matches = [unit for unit, end in candidates.items() if end == latest]
    return matches[0] if len(matches) == 1 else ""


def parse_companyfacts(payload: Any, expected_cik: int, *, as_of: date | None = None):
    today = as_of or datetime.now(timezone.utc).date()
    try:
        if int(payload.get("cik")) != expected_cik:
            return [], []
        gaap = payload["facts"]["us-gaap"]
        if not isinstance(gaap, dict):
            return [], []
    except (AttributeError, KeyError, TypeError, ValueError):
        return [], []
    currency = _unit(gaap, today)
    if not currency:
        return [], []

    def duration_fields(duration):
        fields = {}
        for key, tags in DURATION_TAGS.items():
            unit = "shares" if key == "diluted_shares" else f"{currency}/shares" if key == "diluted_eps" else currency
            fields[key] = _series(gaap, tags, unit, duration, today)
        return fields

    annual_fields = duration_fields("annual")
    quarterly_fields = duration_fields("quarter")
    instant_fields = {key: _series(gaap, tags, currency, "instant", today) for key, tags in INSTANT_TAGS.items()}

    def val(fields, key, period):
        item = fields[key].get(period)
        return item[0] if item else None

    def latest_periods(fields, limit):
        # Require revenue as an anchor and avoid two alternative start dates
        # for the same period end; ambiguous durations are withheld.
        by_end = {}
        for period in fields["revenue"]:
            by_end.setdefault(period[1], []).append(period)
        return [values[0] for end, values in sorted(by_end.items(), reverse=True) if len(values) == 1][:limit]

    annuals = []
    for period in latest_periods(annual_fields, 4):
        start, end = period
        cashflow = val(annual_fields, "operating_cash", period)
        capex_paid = val(annual_fields, "capex", period)
        capex = -capex_paid if capex_paid is not None and capex_paid >= 0 else None
        free = cashflow + capex if cashflow is not None and capex is not None else None
        rev = annual_fields["revenue"][period]
        op = annual_fields["operating"].get(period)
        annuals.append(AnnualFinancial(
            end, rev[0], val(annual_fields, "operating", period), val(annual_fields, "net", period),
            cashflow, capex, free, gross_profit=val(annual_fields, "gross", period),
            stock_compensation=val(annual_fields, "stock_comp", period),
            diluted_shares=val(annual_fields, "diluted_shares", period),
            cash=val(instant_fields, "cash", (None, end)),
            current_assets=val(instant_fields, "current_assets", (None, end)),
            current_liabilities=val(instant_fields, "current_liabilities", (None, end)),
            source="SEC XBRL", currency=currency, revenue_concept=rev[1],
            operating_concept=op[1] if op else "", period_start=start,
        ))
    quarters = []
    for period in latest_periods(quarterly_fields, 6):
        start, end = period
        rev = quarterly_fields["revenue"][period]
        op = quarterly_fields["operating"].get(period)
        quarters.append(QuarterFinancial(
            end, revenue=rev[0], gross_profit=val(quarterly_fields, "gross", period),
            operating_income=val(quarterly_fields, "operating", period),
            net_income=val(quarterly_fields, "net", period), diluted_eps=val(quarterly_fields, "diluted_eps", period),
            diluted_shares=val(quarterly_fields, "diluted_shares", period), source="SEC XBRL",
            currency=currency, revenue_concept=rev[1], operating_concept=op[1] if op else "", period_start=start,
        ))
    return annuals, quarters
