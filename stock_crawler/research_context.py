"""Sentiment, positioning and election-event context based on observed data.

These are descriptive proxies, not claims about the cause of price moves or a
substitute for comprehensive social-media/order-flow data.
"""
from __future__ import annotations

import math
import re
import statistics
from datetime import date, datetime, timedelta, timezone

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from stock_crawler.models import ElectionReaction, ScoredHeadline, SentimentSummary, Snapshot
from stock_crawler.utils import text

VADER = SentimentIntensityAnalyzer()
# VADER is a general-language tool. A small, explicit finance-oriented override
# avoids treating "earnings beat" as violent language. It is not FinBERT.
VADER.lexicon.update({"beat": 1.4, "beats": 1.4, "upgrade": 1.6, "upgrades": 1.6,
                      "downgrade": -1.6, "downgrades": -1.6, "miss": -1.2, "misses": -1.2,
                      "bankruptcy": -2.5, "layoffs": -1.7, "surge": 1.2, "plunge": -1.7})


def _published_date(value: str) -> date | None:
    try:
        # Yahoo normally returns ISO-8601. Date-only demo data are also valid.
        raw = value.strip()
        if len(raw) == 10:
            return date.fromisoformat(raw)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).date() if parsed.tzinfo else parsed.date()
    except (TypeError, ValueError, AttributeError):
        return None


def _relevant_headline(item, snapshot: Snapshot) -> bool:
    ticker = snapshot.ticker.upper()
    if ticker in item.related_symbols:
        return True
    title = item.title
    # Tiny symbols such as A or T are too ambiguous as ordinary words.
    if len(ticker) >= 3 and re.search(rf"(?<![A-Za-z0-9]){re.escape(ticker)}(?![A-Za-z0-9])", title):
        return True
    generic = {"the", "american", "international", "national", "united", "global", "first", "general", "new"}
    for raw in (snapshot.info.get("shortName"), snapshot.info.get("longName"), snapshot.name):
        words = re.findall(r"[A-Za-z0-9]+", text(raw, 100))
        while words and words[0].lower() == "the":
            words.pop(0)
        if not words:
            continue
        alias = " ".join(words[:2]) if words[0].lower() in generic and len(words) > 1 else words[0]
        if len(alias) >= 4 and re.search(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])", title, re.I):
            return True
    return False


def headline_sentiment(snapshot: Snapshot) -> SentimentSummary:
    today = snapshot.fetched_at.astimezone(timezone.utc).date()
    scored: list[ScoredHeadline] = []
    seen: set[str] = set()
    for item in snapshot.news:
        day = _published_date(item.published_at)
        if (day is None or not 0 <= (today - day).days <= 30 or item.title.casefold() in seen
                or (item.language and not item.language.lower().startswith("en"))
                or not _relevant_headline(item, snapshot)):
            continue
        seen.add(item.title.casefold())
        compound = VADER.polarity_scores(item.title)["compound"]
        tone = "Positive" if compound >= 0.05 else "Negative" if compound <= -0.05 else "Neutral"
        scored.append(ScoredHeadline(item, day, compound, tone))
    scored.sort(key=lambda item: item.published_date, reverse=True)
    recent = [item.compound for item in scored if (today - item.published_date).days <= 7]
    prior = [item.compound for item in scored if 8 <= (today - item.published_date).days <= 30]
    return SentimentSummary(
        headlines=scored,
        average=statistics.mean(item.compound for item in scored) if len(scored) >= 5 else None,
        recent_average=statistics.mean(recent) if len(recent) >= 3 else None,
        prior_average=statistics.mean(prior) if len(prior) >= 3 else None,
        recent_count=len(recent), prior_count=len(prior),
        positive_count=sum(item.tone == "Positive" for item in scored),
        neutral_count=sum(item.tone == "Neutral" for item in scored),
        negative_count=sum(item.tone == "Negative" for item in scored),
    )


def positioning(snapshot: Snapshot) -> dict[str, float | None]:
    prices = snapshot.prices
    result: dict[str, float | None] = {"volume_ratio": None, "vs_ma50": None, "vs_ma200": None,
                                       "volatility_63d": None, "put_call_oi": None}
    if len(prices) >= 80:
        recent = [point.volume for point in prices[-20:]]
        prior = [point.volume for point in prices[-80:-20]]
        if all(value is not None for value in recent + prior):
            prior_mean = statistics.mean(prior)
            if prior_mean > 0:
                result["volume_ratio"] = statistics.mean(recent) / prior_mean
    for count, key in ((50, "vs_ma50"), (200, "vs_ma200")):
        if len(prices) >= count:
            vals = [point.adjusted_close for point in prices[-count:]]
            if all(value is not None and value > 0 for value in vals):
                result[key] = vals[-1] / statistics.mean(vals) - 1
    if len(prices) >= 64:
        vals = [point.adjusted_close for point in prices[-64:]]
        if all(value is not None and value > 0 for value in vals):
            log_returns = [math.log(vals[i] / vals[i - 1]) for i in range(1, len(vals))]
            result["volatility_63d"] = statistics.stdev(log_returns) * math.sqrt(252)
    options = snapshot.options
    if (options and options.call_total > 0 and options.put_total > 0
            and options.call_known == options.call_total and options.put_known == options.put_total
            and options.call_open_interest > 0):
        result["put_call_oi"] = options.put_open_interest / options.call_open_interest
    return result


def general_election_day(year: int) -> date:
    """US federal general election: Tuesday after the first Monday in November."""
    first = date(year, 11, 1)
    first_monday = first + timedelta(days=(7 - first.weekday()) % 7)
    return first_monday + timedelta(days=1)


def next_general_election(as_of: date) -> date:
    year = as_of.year if as_of.year % 2 == 0 else as_of.year + 1
    while general_election_day(year) < as_of:
        year += 2
    return general_election_day(year)


def election_reactions(snapshot: Snapshot) -> list[ElectionReaction]:
    prices = snapshot.prices
    if not prices:
        return []
    benchmark = {point.date: point.adjusted_close for point in snapshot.benchmark_prices}
    as_of = snapshot.fetched_at.astimezone(timezone.utc).date()
    winners = snapshot.politics.presidential_winners if snapshot.politics else {}
    reactions: list[ElectionReaction] = []
    first_year = prices[0].date.year
    for year in range(first_year, as_of.year + 1):
        if year % 2:
            continue
        event = general_election_day(year)
        if event > as_of:
            continue
        prior_indices = [index for index, point in enumerate(prices) if point.date < event]
        if not prior_indices:
            continue
        index = prior_indices[-1]
        anchor = prices[index]
        if (event - anchor.date).days > 7 or anchor.adjusted_close is None or anchor.adjusted_close <= 0:
            continue

        def result(horizon: int):
            if index + horizon >= len(prices):
                return None, None
            end = prices[index + horizon]
            if end.date > as_of or end.adjusted_close is None or end.adjusted_close <= 0:
                return None, None
            return end.adjusted_close / anchor.adjusted_close - 1, end.date

        r10, _ = result(10)
        r63, end63 = result(63)
        r126, _ = result(126)
        benchmark_return = None
        if end63 and benchmark.get(anchor.date) and benchmark.get(end63):
            benchmark_return = benchmark[end63] / benchmark[anchor.date] - 1
        kind = "Presidential" if year % 4 == 0 else "Midterm"
        if kind == "Presidential" and year in winners:
            winner, party = winners[year]
            outcome = f"{winner} ({party})"
        else:
            outcome = "Not established in source" if kind == "Presidential" else "Congressional elections"
        reactions.append(ElectionReaction(event, kind, outcome, anchor.date, r10, r63, r126, benchmark_return, end63))
    return reactions[-8:][::-1]


def policy_channels(snapshot: Snapshot) -> list[tuple[str, str]]:
    sector = text(snapshot.info.get("sector"), 80)
    industry = text(snapshot.info.get("industry"), 100)
    name = text(snapshot.name, 80)
    low = industry.lower()
    channels: list[tuple[str, str]] = []
    if "semiconductor" in low:
        channels.append(("Chip exports & industrial policy", f"Export controls, tariffs, fabrication incentives and foreign-market access can affect {name}'s semiconductor supply or sales. Confirm its actual products, destinations and eligibility; no specific restriction or subsidy is assumed."))
    elif "aerospace" in low or "defense" in low:
        channels.append(("Defense procurement", f"Government budgets, contract awards and export approvals can affect {name} if government customers are material. Contract backlog and concentration must be verified in filings."))
    elif "auto" in low:
        channels.append(("Autos, trade & incentives", f"Tariffs, emissions rules and vehicle or battery tax credits can change costs or customer demand for {name}; actual eligibility and geographic production mix need verification."))
    elif sector == "Healthcare":
        channels.append(("Drug pricing & reimbursement", f"Pricing legislation, reimbursement and regulatory approvals can affect {name} if relevant to its product mix. Do not infer payer exposure or a specific policy outcome without issuer disclosures."))
    elif sector == "Energy":
        channels.append(("Energy permitting & taxes", f"Leasing, permits, environmental rules and energy tax provisions can change investment economics for {name}. Effects differ for upstream, services, refining and hedged production."))
    elif sector == "Financial Services":
        channels.append(("Financial regulation", f"Capital requirements, consumer rules and enforcement can affect {name}'s lending capacity and costs; business mix and current rules must be checked."))
    elif sector == "Technology":
        channels.append(("Technology regulation", f"Antitrust, data privacy, AI rules, export restrictions and public-sector purchasing may affect {name}, depending on its products and customer mix. No specific policy change is assumed."))
    elif sector == "Utilities":
        channels.append(("Regulated returns & energy policy", f"State-regulated allowed returns, power-generation rules and federal incentives can affect {name}; the utility's actual service territories and rate cases matter."))
    elif sector == "Real Estate":
        channels.append(("Property & financing rules", f"Tax, zoning and housing-policy changes may affect {name}'s properties or tenants; local exposures and debt structure must be verified."))
    else:
        channels.append(("Industry rules", f"Regulation, government purchasing and enforcement can affect the {industry or 'issuer’s'} industry; verify whether these are material to {name}."))
    channels.extend([
        ("Trade & tariffs", "Import duties, sanctions and export controls can change input costs and market access. The net effect depends on suppliers, production and sales geography."),
        ("Taxes & public spending", "Business taxation, credits and federal or state purchasing can change cash flows or demand, but eligibility and customer exposure need evidence from filings."),
        ("Rates & central bank", "Elected officials can shape fiscal and regulatory conditions; monetary policy is set by the Federal Reserve. Do not attribute every yield or stock move to an election."),
    ])
    return channels
