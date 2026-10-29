"""Conservative extraction of numerically reconciled inline-XBRL revenue mixes.

Only standard revenue concepts, a single recognized dimension, the registrant's
annual duration and currency units are considered. A mix is published only if
one unambiguous most-detailed subset reconciles to the filing's consolidated
revenue. Reconciliation alone does not prove members are non-overlapping. This
intentionally misses many issuers rather than guessing.
"""
from __future__ import annotations

import itertools
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

from stock_crawler.models import RevenueBreakdown, RevenueComponent

REVENUE_CONCEPTS = {
    "revenuefromcontractwithcustomerexcludingassessedtax",
    "revenuefromcontractwithcustomerincludingassessedtax",
    "revenues",
    "salesrevenuenet",
}
AXES = {
    "statementbusinesssegmentsaxis": "Reported business segments",
    "productorserviceaxis": "Products and services",
    "statementgeographicalaxis": "Geographic areas",
}


def _local(value: str) -> str:
    return value.rsplit(":", 1)[-1]


def _label(member: str) -> str:
    name = _local(member)
    name = re.sub(r"Member$", "", name)
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    name = re.sub(r"\bI Phone\b", "iPhone", name)
    name = re.sub(r"\bI Pad\b", "iPad", name)
    name = re.sub(r"\bHomeand\b", "Home and", name)
    return re.sub(r"\s+", " ", name).strip()[:100]


class _InlineParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.contexts = {}
        self.units = {}
        self.facts = []
        self.context = None
        self.unit = None
        self.fact = None
        self.field = ""
        self.field_text: list[str] = []
        self.dimension = ""

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        values = dict(attrs)
        if tag == "xbrli:context":
            self.context = {"id": values.get("id", ""), "dimensions": [], "typed": False}
        elif self.context is not None:
            if tag in {"xbrli:identifier", "xbrli:startdate", "xbrli:enddate", "xbrldi:explicitmember"}:
                self.field, self.field_text = tag, []
                self.dimension = values.get("dimension", "") if tag == "xbrldi:explicitmember" else ""
            elif tag == "xbrldi:typedmember":
                self.context["typed"] = True
        elif tag == "xbrli:unit":
            self.unit = {"id": values.get("id", ""), "measures": [], "divide": False}
        elif self.unit is not None:
            if tag == "xbrli:measure":
                self.field, self.field_text = tag, []
            elif tag == "xbrli:divide":
                self.unit["divide"] = True
        elif tag == "ix:nonfraction":
            concept = values.get("name", "")
            if _local(concept).lower() in REVENUE_CONCEPTS:
                self.fact = {"attrs": values, "text": []}

    def handle_data(self, data):
        if self.field:
            self.field_text.append(data)
        if self.fact is not None:
            self.fact["text"].append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.field == tag:
            value = "".join(self.field_text).strip()
            if self.context is not None:
                if tag == "xbrldi:explicitmember":
                    self.context["dimensions"].append((self.dimension, value))
                else:
                    self.context[_local(tag)] = value
            elif self.unit is not None and tag == "xbrli:measure":
                self.unit["measures"].append(value)
            self.field, self.field_text = "", []
        if tag == "xbrli:context" and self.context is not None:
            if self.context["id"]:
                self.contexts[self.context["id"]] = self.context
            self.context = None
        elif tag == "xbrli:unit" and self.unit is not None:
            if self.unit["id"]:
                self.units[self.unit["id"]] = self.unit
            self.unit = None
        elif tag == "ix:nonfraction" and self.fact is not None:
            self.facts.append(self.fact)
            self.fact = None


def _amount(fact) -> Decimal | None:
    attrs = fact["attrs"]
    if attrs.get("xsi:nil", "").lower() == "true":
        return None
    transform = _local(attrs.get("format", "")).lower()
    if transform and transform not in {"num-dot-decimal", "numdotdecimal"}:
        return None
    raw = "".join(fact["text"]).strip().replace(",", "").replace("\u00a0", "").replace(" ", "")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", raw):
        return None
    try:
        scale = int(attrs.get("scale", "0"))
        if not -9 <= scale <= 12:
            return None
        value = Decimal(raw) * (Decimal(10) ** scale)
        if attrs.get("sign") == "-":
            value = -abs(value)
        return value if value.is_finite() and abs(value) <= Decimal("1e18") else None
    except (ValueError, InvalidOperation):
        return None


def _reconciled_subset(raw_members, totals):
    if len(totals) != 1 or any(len(values) != 1 for values in raw_members.values()):
        return None
    total = next(iter(totals))
    # Negative members can be intersegment eliminations; do not drop them.
    if total <= 0 or any(next(iter(values)) < 0 for values in raw_members.values()):
        return None
    members = [(name, next(iter(values))) for name, values in raw_members.items()
               if 0 < next(iter(values)) < total]
    if not 2 <= len(members) <= 12:
        return None
    tolerance = max(Decimal("1"), total * Decimal("0.003"))
    for size in range(len(members), 1, -1):
        solutions = [part for part in itertools.combinations(members, size)
                     if abs(sum((value for _, value in part), Decimal(0)) - total) <= tolerance]
        if solutions:
            if len(solutions) != 1:
                return None
            return total, sorted(solutions[0], key=lambda item: item[1], reverse=True)
    return None


def extract_revenue_breakdowns(content: bytes, report_date: date | None, cik: int) -> tuple[RevenueBreakdown, ...]:
    if not report_date:
        return ()
    parser = _InlineParser()
    # SEC HTML is normally UTF-8; replacing undecodable bytes fails closed on
    # numeric values and member names rather than guessing an encoding.
    try:
        parser.feed(content.decode("utf-8", errors="replace"))
        parser.close()
    except (ValueError, RecursionError):
        return ()
    consolidated = defaultdict(set)
    dimensional = defaultdict(lambda: defaultdict(set))
    for fact in parser.facts:
        attr = fact["attrs"]
        context = parser.contexts.get(attr.get("contextref", ""))
        unit = parser.units.get(attr.get("unitref", ""))
        if not context or not unit or context.get("typed") or unit["divide"] or len(unit["measures"]) != 1:
            continue
        currency = unit["measures"][0]
        if not re.fullmatch(r"iso4217:[A-Z]{3}", currency):
            continue
        try:
            if int(context.get("identifier", "")) != cik:
                continue
            start = date.fromisoformat(context.get("startdate", ""))
            end = date.fromisoformat(context.get("enddate", ""))
        except (TypeError, ValueError):
            continue
        age = (report_date - end).days
        if age != 0 and not 330 <= age <= 400:
            continue
        if not 330 <= (end - start).days <= 400:
            continue
        amount = _amount(fact)
        if amount is None:
            continue
        concept = attr.get("name", "")
        key = (start, end, currency.split(":")[-1], concept)
        dims = context["dimensions"]
        if not dims:
            consolidated[key].add(amount)
        elif len(dims) == 1:
            axis, member = dims[0]
            kind = AXES.get(_local(axis).lower())
            if kind and re.fullmatch(r"[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+", member):
                dimensional[(key, kind)][member].add(amount)
    results = []
    for (key, kind), raw_members in dimensional.items():
        start, end, currency, concept = key
        if end != report_date:
            continue
        resolved = _reconciled_subset(raw_members, consolidated.get(key, set()))
        if not resolved:
            continue
        total, selected = resolved
        # Compare the previous year only when currency, concept, dimension,
        # duration and every selected member match, and both years reconcile.
        # Multiple plausible prior periods are ambiguous and are withheld.
        priors = []
        for (prior_key, prior_kind), prior_members in dimensional.items():
            prior_start, prior_end, prior_currency, prior_concept = prior_key
            if (prior_kind != kind or prior_currency != currency or prior_concept != concept
                    or not 330 <= (end - prior_end).days <= 400
                    or abs((end - start).days - (prior_end - prior_start).days) > 14):
                continue
            prior_resolved = _reconciled_subset(prior_members, consolidated.get(prior_key, set()))
            if not prior_resolved:
                continue
            prior_total, prior_selected = prior_resolved
            prior_values = dict(prior_selected)
            if set(prior_values) == {member for member, _ in selected}:
                priors.append((prior_start, prior_end, prior_total, prior_values))
        prior = priors[0] if len(priors) == 1 else None
        results.append(RevenueBreakdown(
            kind, start, end, currency, float(total),
            tuple(RevenueComponent(_label(member), float(value), member,
                                   float(prior[3][member]) if prior else None) for member, value in selected),
            concept, prior[0] if prior else None, prior[1] if prior else None, float(prior[2]) if prior else None,
        ))
    # Multiple concepts may report the same dimension. Don't claim two distinct
    # mixes; prefer the most detailed reconciled one for each kind.
    best = {}
    for item in results:
        if item.kind not in best or len(item.components) > len(best[item.kind].components):
            best[item.kind] = item
    return tuple(best[kind] for kind in ("Reported business segments", "Products and services", "Geographic areas")
                 if kind in best)
