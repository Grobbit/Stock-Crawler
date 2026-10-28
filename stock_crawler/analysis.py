"""Transparent, rules-based research synthesis.

This is deliberately not an LLM and does not assert that the heuristic is a
validated forecasting model. Missing inputs are excluded rather than invented.
"""
from __future__ import annotations

from datetime import timedelta

from dateutil.relativedelta import relativedelta

from stock_crawler.models import Analysis, Factor, Scenario, Snapshot
from stock_crawler.utils import MINOR_UNIT_CURRENCIES, compact, days_old, number, pct, text

WEIGHTS = {
    "growth": 0.18,
    "profitability": 0.16,
    "balance": 0.12,
    "valuation": 0.12,
    "momentum": 0.12,
    "analysts": 0.10,
    "macro": 0.20,
}
# Explicit, fixed heuristic anchors, NOT observed sector averages or peer data.
PE_ANCHORS = {
    "Technology": 25.0, "Communication Services": 20.0, "Consumer Cyclical": 23.0,
    "Consumer Defensive": 20.0, "Healthcare": 20.0, "Financial Services": 12.0,
    "Industrials": 20.0, "Basic Materials": 15.0, "Energy": 12.0, "Utilities": 18.0,
}
# Sensitivities are subjective sector-level signs/weights, not regression results.
# (10-year yield, unemployment, CPI inflation). An increase is the input direction.
EXPOSURES = {
    "Technology": (-1.0, -0.5, -0.35),
    "Communication Services": (-0.8, -0.6, -0.4),
    "Consumer Cyclical": (-0.6, -1.0, -0.9),
    "Consumer Defensive": (-0.4, -0.5, -0.8),
    "Healthcare": (-0.5, -0.3, -0.35),
    "Financial Services": (0.0, -1.0, -0.45),
    "Industrials": (-0.6, -0.8, -0.6),
    "Basic Materials": (-0.4, -0.8, -0.6),
    "Energy": (-0.25, -0.7, -0.3),
    "Utilities": (-1.0, -0.25, -0.4),
    "Real Estate": (-1.0, -0.6, -0.4),
}
SECTOR_CHANNELS = {
    "Technology": "discount rates and customer technology budgets",
    "Communication Services": "advertising or subscription demand and financing costs",
    "Consumer Cyclical": "household discretionary spending and credit costs",
    "Consumer Defensive": "household purchasing power and input costs",
    "Healthcare": "financing costs and customer or payer budgets",
    "Financial Services": "borrower credit quality and demand for financial services",
    "Industrials": "customer capital expenditure, order cycles and input costs",
    "Basic Materials": "construction and industrial demand, commodity prices and input costs",
    "Energy": "commodity demand, energy prices and capital spending",
    "Utilities": "financing costs, regulated returns and fuel costs",
    "Real Estate": "financing costs, property demand and capitalization rates",
}


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return min(high, max(low, value))


def _tier(value: float, thresholds: tuple[float, float, float, float]) -> float:
    if value >= thresholds[0]:
        return 1.0
    if value >= thresholds[1]:
        return 0.5
    if value >= thresholds[2]:
        return 0.0
    if value >= thresholds[3]:
        return -0.5
    return -1.0


def _return_at(snapshot: Snapshot, months: int) -> float | None:
    target = snapshot.price_date - relativedelta(months=months)
    earlier = [point for point in snapshot.prices if point.date <= target]
    if not earlier:
        return None
    point = earlier[-1]
    if (target - point.date) > timedelta(days=10) or point.close <= 0:
        return None
    return snapshot.price / point.close - 1


def _macro_score(snapshot: Snapshot) -> tuple[float | None, str]:
    sector = text(snapshot.info.get("sector"), 80)
    industry = text(snapshot.info.get("industry"), 100).lower()
    if sector not in EXPOSURES:
        return None, "No sector-specific macro sensitivity assumptions are defined for this instrument."
    rate, jobs, cpi = EXPOSURES[sector]
    # A normalizing move is 0.5 pp in yields, 0.4 pp in unemployment,
    # 0.8 pp in CPI YoY, or 20% in oil. Inputs are capped at +/-1.
    specs = [("DGS10", rate, 0.5), ("UNRATE", jobs, 0.4), ("CPIAUCSL", cpi, 0.8)]
    if sector == "Energy" and any(term in industry for term in ("exploration", "production", "e&p")):
        specs.append(("DCOILWTICO", 1.0, 0.20))
    elif "airline" in industry:
        specs.append(("DCOILWTICO", -1.0, 0.20))
    total = 0.0
    weights = 0.0
    observed: list[str] = []
    for code, exposure, scale in specs:
        point = snapshot.macro.get(code)
        if not exposure or not point or point.change_3m is None or days_old(point.as_of, snapshot.fetched_at.date()) > 90:
            continue
        total += exposure * _clamp(point.change_3m / scale)
        weights += abs(exposure)
        if point.change_kind == "percent":
            move = pct(point.change_3m, signed=True)
        else:
            move = f"{point.change_3m:+.2f} pp"
        observed.append(f"{point.label}: {move} [{point.source_id}]")
    if len(observed) < 2 or not weights:
        return None, "At least two recent, relevant macro changes are required for the macro overlay."
    result = _clamp(total / weights)
    return result, "; ".join(observed) + ". Directional sector assumptions, not measured company correlations."


def _macro_channels(snapshot: Snapshot) -> list[tuple[str, str]]:
    info = snapshot.info
    name = text(snapshot.name, 80)
    sector = text(info.get("sector"), 80)
    industry = text(info.get("industry"), 90) or "business"
    channel = SECTOR_CHANNELS.get(sector, "customer demand, costs and financing")
    financial_currency = text(info.get("financialCurrency"), 12)
    debt, cash = number(info.get("totalDebt")), number(info.get("totalCash"))
    if debt is not None and cash is not None and financial_currency and sector != "Financial Services":
        balance = f"Reported debt is {compact(debt, financial_currency)} and cash is {compact(cash, financial_currency)}; any refinancing effect depends on maturities and fixed/floating terms not established here."
    else:
        balance = "The effect on financing depends on debt maturities and fixed/floating terms, which are not established here."
    margin = number(info.get("operatingMargins"))
    margin_text = f" The provider-reported operating margin is {pct(margin)}." if margin is not None else " Company-specific pricing power is not established here."
    results = [
        ("Interest rates", f"For {name}, a sustained rise in yields can pressure valuation and financing; the relevant business channel is {channel}. {balance}"),
        ("Inflation", f"Higher input or wage inflation can squeeze {name}'s margins if prices cannot keep pace; lower inflation can ease that pressure.{margin_text} The net impact depends on contracts and pricing power."),
        ("Employment / demand", f"A weakening US labor market can reduce spending or budgets relevant to the {industry} industry. The magnitude and geographic exposure of {name}'s customers are not inferred from the sector alone."),
    ]
    ind = industry.lower()
    if sector == "Energy":
        oil = "Higher crude prices can support upstream revenue, while refining, hedging and customer demand may have different or offsetting effects. The business mix matters."
    elif "airline" in ind or "transport" in ind:
        oil = "Higher oil prices can increase fuel costs; the actual effect depends on fuel hedges and the ability to pass costs on to customers."
    else:
        oil = "Oil affects energy, freight and customer budgets; the net effect on this issuer depends on contracts and cost pass-through and is not assumed to be one-directional."
    results.append(("Oil", oil))
    results.append(("US dollar", "A stronger US dollar can reduce translated foreign-currency revenue for a US reporter, or alter competitiveness; foreign sales mix and hedges must be verified. This channel is not scored."))
    return results


def analyze(snapshot: Snapshot) -> Analysis:
    info = snapshot.info
    sector = text(info.get("sector"), 80)
    financial_currency = text(info.get("financialCurrency"), 12)
    quote_currency = text(info.get("currency"), 12)
    is_equity = snapshot.quote_type == "EQUITY"
    growth = number(info.get("revenueGrowth")) if is_equity else None
    margin = number(info.get("operatingMargins")) if is_equity else None
    debt = number(info.get("totalDebt")) if is_equity else None
    cash = number(info.get("totalCash")) if is_equity else None
    cap = number(info.get("marketCap")) if is_equity else None
    forward_pe = number(info.get("forwardPE")) if is_equity else None
    recommendation = number(info.get("recommendationMean")) if is_equity else None
    analyst_count = number(info.get("numberOfAnalystOpinions")) if is_equity else None
    returns = {"1m": _return_at(snapshot, 1), "3m": _return_at(snapshot, 3), "6m": _return_at(snapshot, 6)}
    factors: list[Factor] = []

    def add(key: str, label: str, score: float | None, evidence: str, source: str) -> None:
        factors.append(Factor(key, label, WEIGHTS[key], score, evidence, source))

    add("growth", "Revenue growth", _tier(growth, (0.15, 0.05, -0.05, -0.15)) if growth is not None else None,
        f"Provider-reported revenue growth: {pct(growth, signed=True)}; thresholds are +15%, +5%, -5%, and -15%." if growth is not None else "Provider-reported revenue growth is unavailable.", "Q")
    add("profitability", "Operating profitability", _tier(margin, (0.20, 0.10, 0.0, -0.10)) if margin is not None else None,
        f"Provider-reported operating margin: {pct(margin)}; thresholds are 20%, 10%, 0%, and -10%." if margin is not None else "Provider-reported operating margin is unavailable.", "Q")

    # ISO-style currency labels can be case-sensitive (notably GBp pence vs
    # GBP pounds). Never silently treat different units as interchangeable.
    same_currency = bool(financial_currency and quote_currency and financial_currency == quote_currency
                         and quote_currency not in MINOR_UNIT_CURRENCIES)
    if sector == "Financial Services":
        balance_score, balance_evidence = None, "Net debt relative to market value is not used for financial institutions."
    elif debt is not None and cash is not None and cap is not None and cap > 0 and same_currency:
        net_debt_ratio = (debt - cash) / cap
        balance_score = _tier(-net_debt_ratio, (0.10, 0.0, -0.30, -0.75))
        balance_evidence = f"Net debt / market value: {pct(net_debt_ratio, signed=True)}; debt and cash use {financial_currency}. This is not a maturity or solvency assessment."
    else:
        balance_score = None
        balance_evidence = "Debt, cash, market value, or matching unambiguous quote/reporting currency units are unavailable; no cross-currency ratio was calculated."
    add("balance", "Balance sheet", balance_score, balance_evidence, "Q")

    anchor = PE_ANCHORS.get(sector)
    if forward_pe is not None and forward_pe > 0 and anchor and is_equity:
        ratio = forward_pe / anchor
        valuation_score = 1.0 if ratio <= 0.75 else 0.5 if ratio <= 1.0 else 0.0 if ratio <= 1.25 else -0.5 if ratio <= 1.75 else -1.0
        valuation_evidence = f"Forward P/E {forward_pe:.1f}x versus a fixed {anchor:.0f}x {sector} heuristic anchor; the anchor is not an observed peer average."
    else:
        valuation_score = None
        valuation_evidence = "A positive forward P/E and an applicable sector anchor are required; P/E is not scored for REITs or unknown sectors."
    add("valuation", "Valuation", valuation_score, valuation_evidence, "Q")
    momentum = returns["6m"]
    add("momentum", "Six-month price trend", _tier(momentum, (0.20, 0.05, -0.05, -0.20)) if momentum is not None else None,
        f"Six-month price return: {pct(momentum, signed=True)}, excluding dividends; past performance is not a forecast." if momentum is not None else "Six months of comparable daily closes are unavailable.", "H")
    if recommendation is not None and 1 <= recommendation <= 5 and analyst_count is not None and analyst_count >= 3:
        analyst_score = _tier(3 - recommendation, (1.0, 0.5, -0.5, -1.0))
        analyst_evidence = f"Provider analyst recommendation mean {recommendation:.2f}/5 from {int(analyst_count)} analysts (1 = strong buy, 5 = sell)."
    else:
        analyst_score = None
        analyst_evidence = "A provider recommendation mean with at least three analysts is required; unavailable or too few analysts."
    add("analysts", "Analyst sentiment", analyst_score, analyst_evidence, "A")
    macro_score, macro_evidence = _macro_score(snapshot)
    add("macro", "Macro backdrop", macro_score, macro_evidence, "M")

    available = [f for f in factors if f.score is not None]
    coverage = sum(f.weight for f in available)
    score = sum(f.weight * f.score for f in available if f.score is not None) / coverage if coverage else None
    stale = days_old(snapshot.price_date, snapshot.fetched_at.date()) > 14
    fundamental_count = sum(f.score is not None for f in factors if f.key in {"growth", "profitability", "balance", "valuation"})
    enough = bool(is_equity and not stale and coverage >= 0.65 - 1e-9 and fundamental_count >= 2 and macro_score is not None and score is not None)
    if not enough:
        verdict = "Insufficient evidence"
    elif score >= 0.20:
        verdict = "Bullish"
    elif score <= -0.20:
        verdict = "Bearish"
    else:
        verdict = "Mixed / neutral"

    target_date = snapshot.price_date + relativedelta(months=6)
    scenarios: list[Scenario] = []
    target = expected_return = spread = None
    spread_basis = "Not applicable while the target is withheld."
    if enough and score is not None:
        base_return = 0.16 * score
        beta = number(info.get("beta"))
        if beta is not None and 0 < beta <= 5:
            spread = _clamp(0.20 * beta, 0.12, 0.35)
            spread_basis = f"20% multiplied by provider beta {beta:.2f}, capped at 12%-35%; beta is a market-sensitivity proxy, not volatility or a confidence interval."
        else:
            spread = 0.20
            spread_basis = "A default 20 percentage-point scenario half-width is used because a suitable beta is unavailable."
        for label, probability, scenario_return in (
            ("Bull", 0.25, base_return + spread),
            ("Base", 0.50, base_return),
            ("Bear", 0.25, base_return - spread),
        ):
            scenarios.append(Scenario(label, probability, scenario_return, snapshot.price * (1 + scenario_return)))
        target = sum(s.probability * s.price for s in scenarios)
        expected_return = target / snapshot.price - 1

    positive_factors = sorted((f for f in available if f.score is not None and f.score > 0), key=lambda f: f.weight * float(f.score), reverse=True)
    negative_factors = sorted((f for f in available if f.score is not None and f.score < 0), key=lambda f: f.weight * float(f.score))
    positives = [f"{f.label}: {f.evidence}" for f in positive_factors[:4]]
    negatives = [f"{f.label}: {f.evidence}" for f in negative_factors[:4]]
    if not positives:
        positives.append("Conditional upside: revenue growth, operating margins or the macro backdrop would need to improve; the available inputs do not provide a positive scored signal.")
    if not negatives:
        negatives.append("Even supportive inputs can reverse: slower growth, margin compression, higher rates or a weaker market could undermine the case.")
    if snapshot.filing and snapshot.filing.risk_excerpts:
        negatives.append("Filing excerpt: " + text(snapshot.filing.risk_excerpts[0], 300))

    limitations = list(snapshot.warnings)
    if not is_equity:
        limitations.append("The single-company model does not assign a stock verdict or price target to funds, indices, currencies, cryptocurrencies or other non-equity instruments.")
    if stale:
        limitations.append("The latest close is more than 14 calendar days old; the verdict and price target are withheld.")
    if macro_score is None:
        limitations.append("The macro overlay lacks at least two recent relevant observations; the verdict and price target are withheld.")
    if fundamental_count < 2:
        limitations.append("Fewer than two company fundamental factors are available; the verdict and price target are withheld.")
    if coverage < 0.65 - 1e-9:
        limitations.append("Available factor weight is below the 65% minimum needed for a verdict and target.")
    country = text(info.get("country"), 80)
    if country and country.lower() not in {"united states", "united states of america", "usa", "us"}:
        limitations.append("Macro data are US-centric proxies and do not cover this issuer's local rates, inflation or full geographic mix.")
    if not same_currency and debt is not None and cash is not None:
        limitations.append("Financial-statement and quote currency units differ, are unspecified, or use an ambiguous minor-unit quote; cross-currency balance and yield ratios are not calculated.")
    limitations.append("This is an uncalibrated, rules-based scenario exercise, not a statistically validated forecast or personalized investment advice.")
    # Preserve order while avoiding duplicate caveats.
    limitations = list(dict.fromkeys(limitations))
    return Analysis(factors, coverage, score, verdict, target, target_date, expected_return, scenarios, spread, spread_basis,
                    _macro_channels(snapshot), positives, negatives, limitations, returns, stale)
