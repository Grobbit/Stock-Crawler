"""Evidence-led company-specific interpretation, kept outside the scorecard.

These descriptive comparisons explain what changed and why to investigate it;
they do not invent causes or change the archived scoring model.
"""
from __future__ import annotations

import statistics

from stock_crawler.models import (
    AnnualFinancial,
    QuarterFinancial,
    ResearchInsight,
    Snapshot,
)
from stock_crawler.utils import compact, number, pct, text


def selected_quarters(snapshot: Snapshot) -> list[QuarterFinancial]:
    """Use the more recent source; prefer primary SEC data for the same end date."""
    today = snapshot.fetched_at.date()
    yahoo = [item for item in snapshot.quarters if item.period_end <= today]
    sec = [item for item in (snapshot.filing.sec_quarters if snapshot.filing else ()) if item.period_end <= today]
    if sec and (not yahoo or max(x.period_end for x in sec) >= max(x.period_end for x in yahoo)):
        return sorted(sec, key=lambda x: x.period_end, reverse=True)
    return sorted(yahoo, key=lambda x: x.period_end, reverse=True)


def selected_annuals(snapshot: Snapshot) -> list[AnnualFinancial]:
    today = snapshot.fetched_at.date()
    yahoo = [item for item in snapshot.annuals if item.period_end <= today]
    sec = [item for item in (snapshot.filing.sec_annuals if snapshot.filing else ()) if item.period_end <= today]
    if sec and (not yahoo or max(x.period_end for x in sec) >= max(x.period_end for x in yahoo)):
        return sorted(sec, key=lambda x: x.period_end, reverse=True)
    return sorted(yahoo, key=lambda x: x.period_end, reverse=True)


def _currency(snapshot: Snapshot, record) -> str:
    return record.currency or text(snapshot.info.get("financialCurrency"), 12) or "reporting currency"


def _compatible(first, second, field: str) -> bool:
    if first.source != second.source or first.currency != second.currency:
        return False
    a, b = getattr(first, field), getattr(second, field)
    if a or b:
        return bool(a and b and a == b)
    return True


def _comparable_periods(first, second) -> bool:
    distance = (first.period_end - second.period_end).days
    if not 330 <= distance <= 400:
        return False
    if first.period_start and second.period_start:
        first_length = (first.period_end - first.period_start).days
        second_length = (second.period_end - second.period_start).days
        if abs(first_length - second_length) > 14:
            return False
    return True


def _source(record) -> str:
    return "X" if record.source == "SEC XBRL" else "S"


def _growth_insight(snapshot: Snapshot, rows: list, kind: str) -> ResearchInsight | None:
    if not rows:
        return None
    latest = rows[0]
    previous = next((item for item in rows[1:] if _comparable_periods(latest, item)), None)
    if (previous is None or not _compatible(latest, previous, "revenue_concept")
            or latest.revenue is None or previous.revenue is None or latest.revenue <= 0 or previous.revenue <= 0):
        return None
    growth = latest.revenue / previous.revenue - 1
    currency = _currency(snapshot, latest)
    evidence = (f"{kind} ended {latest.period_end}: revenue {compact(latest.revenue, currency)} versus "
                f"{compact(previous.revenue, currency)} for the comparable period ended {previous.period_end} "
                f"({pct(growth, signed=True)}).")
    direction = "positive" if growth > 0.01 else "negative" if growth < -0.01 else "mixed"
    implication = "Revenue growth or contraction changes the sales base; compare it with margins and cash generation before interpreting quality."
    if (latest.operating_income is not None and previous.operating_income is not None
            and _compatible(latest, previous, "operating_concept")):
        current_margin = latest.operating_income / latest.revenue
        prior_margin = previous.operating_income / previous.revenue
        move = (current_margin - prior_margin) * 100
        evidence += f" Operating margin was {pct(current_margin)} versus {pct(prior_margin)} ({move:+.1f} percentage points)."
        if growth > 0.01 and move > 0.5:
            direction = "positive"
            implication = "Sales expanded while operating profit per revenue dollar improved. That is consistent with operating leverage, but mix, pricing, costs and one-offs require verification."
        elif growth > 0.01 and move < -0.5:
            direction = "mixed"
            implication = "Sales grew but operating profit per revenue dollar fell. Check whether pricing, product mix, investment or costs explain the tension; the data alone do not establish the cause."
        elif growth < -0.01 and move < -0.5:
            direction = "negative"
            implication = "Both sales and operating margin declined. Check whether the pressure is temporary and whether cash generation can support the business."
        elif growth < -0.01 and move > 0.5:
            direction = "mixed"
            implication = "Sales declined even as operating margin improved. Check whether the improvement is durable or reflects one-time costs or mix."
        if current_margin < 0:
            implication += " The latest reported operating margin remains negative."
    return ResearchInsight("Growth versus profitability", evidence, implication, direction, _source(latest))


def research_insights(snapshot: Snapshot) -> list[ResearchInsight]:
    if snapshot.quote_type != "EQUITY":
        return []
    insights: list[ResearchInsight] = []
    quarters = selected_quarters(snapshot)
    annuals = selected_annuals(snapshot)
    growth = _growth_insight(snapshot, quarters, "Quarter") or _growth_insight(snapshot, annuals, "Fiscal year")
    if growth:
        insights.append(growth)
    if annuals:
        latest = annuals[0]
        currency = _currency(snapshot, latest)
        ocf, net, fcf = latest.operating_cash_flow, latest.net_income, latest.free_cash_flow
        if ocf is not None and net is not None and net > 0:
            conversion = ocf / net
            evidence = (f"Fiscal year ended {latest.period_end}: operating cash flow {compact(ocf, currency)} "
                        f"versus net income {compact(net, currency)} ({conversion:.2f}x); "
                        f"free cash flow {compact(fcf, currency)}.")
            direction = "positive" if conversion >= 1 else "negative" if conversion < 0.7 else "mixed"
            implication = ("Cash conversion helps distinguish accounting profit from cash inflows, but working capital, taxes and one-time items can make one year unrepresentative. "
                           "Free cash flow definitions differ; inspect the cash-flow statement.")
            insights.append(ResearchInsight("Earnings versus cash", evidence, implication, direction, _source(latest)))
        stock_comp = latest.stock_compensation
        if stock_comp is not None and stock_comp >= 0 and latest.revenue is not None and latest.revenue > 0:
            evidence = (f"Fiscal {latest.period_end}: stock-based compensation {compact(stock_comp, currency)}, "
                        f"or {pct(stock_comp / latest.revenue)} of revenue; free cash flow {compact(fcf, currency)}.")
            implication = ("Stock compensation is generally noncash in operating cash flow but can dilute shareholders. "
                           "It is not automatically subtracted from free cash flow; compare it with share-count changes and repurchases.")
            insights.append(ResearchInsight("Stock compensation and dilution", evidence, implication, "mixed", _source(latest)))
        previous = next((item for item in annuals[1:] if _comparable_periods(latest, item)), None)
        if (previous and latest.diluted_shares is not None and previous.diluted_shares is not None
                and latest.diluted_shares > 0 and previous.diluted_shares > 0 and latest.source == previous.source):
            delta = latest.diluted_shares / previous.diluted_shares - 1
            evidence = (f"Diluted weighted-average shares moved from {compact(previous.diluted_shares)} for {previous.period_end} "
                        f"to {compact(latest.diluted_shares)} for {latest.period_end} ({pct(delta, signed=True)}).")
            implication = ("A rising share count can dilute per-share ownership; a decline can offset it. "
                           "These are period averages, not the year-end share count, and do not by themselves identify the cause.")
            insights.append(ResearchInsight("Per-share ownership", evidence, implication,
                                             "negative" if delta > 0.01 else "positive" if delta < -0.01 else "mixed", _source(latest)))
    if snapshot.filing and snapshot.filing.revenue_breakdowns:
        mix = next((item for item in snapshot.filing.revenue_breakdowns if item.kind == "Products and services"),
                   snapshot.filing.revenue_breakdowns[0])
        lead = mix.components[0]
        share = lead.value / mix.total
        evidence = (f"In the {mix.end} filing, the largest {mix.kind.lower()} component was {lead.label}, "
                    f"{compact(lead.value, mix.currency)} of {compact(mix.total, mix.currency)} "
                    f"({pct(share)} of reported revenue).")
        implication = ("This makes the component an important driver to investigate, not proof of customer concentration or its future growth. "
                       "Member labels come from filing tags; verify the original table.")
        insights.append(ResearchInsight("Where revenue is concentrated", evidence, implication, "mixed", "F"))
        if (mix.prior_end and mix.prior_total and mix.prior_total > 0 and
                all(item.prior_value is not None and item.prior_value > 0 for item in mix.components)):
            driver = max(mix.components, key=lambda item: abs(item.value - item.prior_value))
            change = driver.value / driver.prior_value - 1
            total_change = mix.total / mix.prior_total - 1
            evidence = (f"From the year ended {mix.prior_end} to {mix.end}, {driver.label} had the largest absolute change "
                        f"among the matched {mix.kind.lower()} categories: {compact(driver.prior_value, mix.currency)} to "
                        f"{compact(driver.value, mix.currency)} ({pct(change, signed=True)}), while total revenue changed "
                        f"{pct(total_change, signed=True)}.")
            implication = ("That line is a material place to investigate product demand and business mix; revenue change alone "
                           "does not establish its profit contribution or the cause. Verify the issuer's segment definitions.")
            insights.append(ResearchInsight("Revenue mix shifts", evidence, implication, "mixed", "F"))
    group = snapshot.peers
    issuer_growth = number(snapshot.info.get("revenueGrowth"))
    issuer_margin = number(snapshot.info.get("operatingMargins"))
    growths = [x.revenue_growth for x in group.members if x.revenue_growth is not None] if group else []
    margins = [x.operating_margin for x in group.members if x.operating_margin is not None] if group else []
    evidence_parts = []
    if issuer_growth is not None and len(growths) >= 3:
        evidence_parts.append(f"revenue growth {pct(issuer_growth, signed=True)} versus peer median {pct(statistics.median(growths), signed=True)} ({len(growths)} peers)")
    if issuer_margin is not None and len(margins) >= 3:
        evidence_parts.append(f"operating margin {pct(issuer_margin)} versus peer median {pct(statistics.median(margins))} ({len(margins)} peers)")
    if evidence_parts:
        insights.append(ResearchInsight("Business quality versus peers", "; ".join(evidence_parts) + ".",
                                         "Peers are a small same-industry sample selected for positive forward P/E. Definitions, fiscal periods and business mixes differ; a spread is not a fair-value estimate.",
                                         "mixed", "R"))
    return insights
