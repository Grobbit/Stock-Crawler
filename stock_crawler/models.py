"""Small, provider-independent types used by the collector and research engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class PricePoint:
    date: date
    close: float
    adjusted_close: float | None = None
    volume: float | None = None


@dataclass(frozen=True)
class MacroPoint:
    code: str
    label: str
    value: float
    as_of: date
    # For rates and inflation this is a change in percentage points; for
    # commodity prices and the dollar index it is a fractional price change.
    change_3m: float | None
    comparison_date: date | None
    unit: str
    change_kind: str  # "pp" or "percent"
    source_url: str
    source_id: str


@dataclass(frozen=True)
class RevenueComponent:
    # Labels are derived from XBRL member names, not invented product names.
    label: str
    value: float
    member: str
    prior_value: float | None = None


@dataclass(frozen=True)
class RevenueBreakdown:
    kind: str
    start: date
    end: date
    currency: str
    total: float
    components: tuple[RevenueComponent, ...]
    concept: str
    prior_start: date | None = None
    prior_end: date | None = None
    prior_total: float | None = None


@dataclass(frozen=True)
class FilingEvent:
    form: str
    filing_date: date
    report_date: date | None
    url: str
    items: tuple[str, ...] = ()


@dataclass(frozen=True)
class Filing:
    form: str
    filing_date: date
    report_date: date | None
    url: str
    customer_excerpts: tuple[str, ...] = ()
    risk_excerpts: tuple[str, ...] = ()
    truncated: bool = False
    policy_excerpts: tuple[str, ...] = ()
    operating_excerpts: tuple[str, ...] = ()
    revenue_breakdowns: tuple[RevenueBreakdown, ...] = ()
    recent_events: tuple[FilingEvent, ...] = ()
    latest_quarter: Filing | None = None
    sec_annuals: tuple[AnnualFinancial, ...] = ()
    sec_quarters: tuple[QuarterFinancial, ...] = ()
    companyfacts_url: str = ""


@dataclass(frozen=True)
class AnnualFinancial:
    period_end: date
    revenue: float | None
    operating_income: float | None
    net_income: float | None
    operating_cash_flow: float | None = None
    capital_expenditure: float | None = None
    free_cash_flow: float | None = None
    gross_profit: float | None = None
    stock_compensation: float | None = None
    diluted_shares: float | None = None
    cash: float | None = None
    total_debt: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    source: str = "Yahoo Finance"
    currency: str = ""
    revenue_concept: str = ""
    operating_concept: str = ""
    period_start: date | None = None


@dataclass(frozen=True)
class QuarterFinancial:
    period_end: date
    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    diluted_eps: float | None = None
    diluted_shares: float | None = None
    source: str = "Yahoo Finance"
    currency: str = ""
    revenue_concept: str = ""
    operating_concept: str = ""
    period_start: date | None = None


@dataclass(frozen=True)
class ResearchInsight:
    label: str
    evidence: str
    implication: str
    direction: str  # positive, negative or mixed; descriptive, not a forecast
    source: str


@dataclass(frozen=True)
class NewsItem:
    title: str
    publisher: str
    published_at: str
    url: str
    language: str = ""
    related_symbols: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompanyProfile:
    entity_id: str
    name: str
    products: tuple[str, ...] = ()
    subsidiaries: tuple[str, ...] = ()
    founders: tuple[str, ...] = ()
    inception: str = ""
    retrieved_at: datetime | None = None


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    snippet: str
    publisher: str
    published_at: str
    topic: str
    source: str


@dataclass(frozen=True)
class PeerValuation:
    ticker: str
    name: str
    industry: str
    forward_pe: float
    revenue_growth: float | None = None
    operating_margin: float | None = None


@dataclass(frozen=True)
class PeerGroup:
    industry_key: str
    industry: str
    members: tuple[PeerValuation, ...]
    retrieved_at: datetime


@dataclass(frozen=True)
class AnalystPeriod:
    period: str
    strong_buy: int
    buy: int
    hold: int
    sell: int
    strong_sell: int

    @property
    def count(self) -> int:
        return self.strong_buy + self.buy + self.hold + self.sell + self.strong_sell


@dataclass(frozen=True)
class OptionsSnapshot:
    expiration: date
    call_open_interest: int
    put_open_interest: int
    call_known: int
    call_total: int
    put_known: int
    put_total: int
    retrieved_at: datetime


@dataclass(frozen=True)
class Official:
    name: str
    role: str
    party: str
    start: date
    end: date | None = None
    state: str = ""


@dataclass
class PoliticalContext:
    executives: list[Official] = field(default_factory=list)
    leaders: list[Official] = field(default_factory=list)
    headquarters_senators: list[Official] = field(default_factory=list)
    # A verified presidential term starting in year+1 identifies that year's winner.
    presidential_winners: dict[int, tuple[str, str]] = field(default_factory=dict)
    headquarters_state: str = ""
    retrieved_at: datetime | None = None
    source_url: str = "https://github.com/unitedstates/congress-legislators"


@dataclass(frozen=True)
class ScoredHeadline:
    item: NewsItem
    published_date: date
    compound: float
    tone: str


@dataclass
class SentimentSummary:
    headlines: list[ScoredHeadline]
    average: float | None
    recent_average: float | None
    prior_average: float | None
    recent_count: int
    prior_count: int
    positive_count: int
    neutral_count: int
    negative_count: int


@dataclass(frozen=True)
class ElectionReaction:
    election_date: date
    election_type: str
    outcome: str
    anchor_date: date
    return_10d: float | None
    return_63d: float | None
    return_126d: float | None
    benchmark_63d: float | None
    end_63d: date | None


@dataclass(frozen=True)
class RecordedSignal:
    observed_at: datetime
    score: float
    verdict: str


@dataclass
class Snapshot:
    requested_ticker: str
    ticker: str
    name: str
    info: dict[str, Any]
    prices: list[PricePoint]
    macro: dict[str, MacroPoint]
    fetched_at: datetime
    # The price provider is tracked separately from Yahoo profile/financial sources.
    price_source: str = "Yahoo Finance"
    macro_history: dict[str, list[tuple[date, float]]] = field(default_factory=dict)
    peers: PeerGroup | None = None
    recorded_signals: list[RecordedSignal] = field(default_factory=list)
    filing: Filing | None = None
    company_profile: CompanyProfile | None = None
    holdings: list[tuple[str, str, float | None]] = field(default_factory=list)
    annuals: list[AnnualFinancial] = field(default_factory=list)
    quarters: list[QuarterFinancial] = field(default_factory=list)
    news: list[NewsItem] = field(default_factory=list)
    web_news: list[NewsItem] = field(default_factory=list)
    web_results: list[WebResult] = field(default_factory=list)
    web_search_enabled: bool = False
    analyst_trend: list[AnalystPeriod] = field(default_factory=list)
    options: OptionsSnapshot | None = None
    benchmark_prices: list[PricePoint] = field(default_factory=list)
    politics: PoliticalContext | None = None
    warnings: list[str] = field(default_factory=list)
    demo: bool = False

    @property
    def price(self) -> float:
        return self.prices[-1].close

    @property
    def price_date(self) -> date:
        return self.prices[-1].date

    @property
    def currency(self) -> str:
        return str(self.info.get("currency") or "quote currency")[:12]

    @property
    def quote_type(self) -> str:
        return str(self.info.get("quoteType") or "UNKNOWN").upper()


@dataclass(frozen=True)
class Factor:
    key: str
    label: str
    weight: float
    score: float | None  # -1 to +1; None means missing, not neutral
    evidence: str
    source: str


@dataclass(frozen=True)
class PriceRange:
    months: int
    end_date: date
    low: float
    high: float
    log_drift: float
    log_half_width: float


@dataclass(frozen=True)
class BacktestHorizon:
    months: int
    directional_calls: int
    correct_calls: int
    always_up_correct: int
    bullish_calls: int
    bearish_calls: int
    flat_outcomes: int
    range_observations: int
    range_hits: int
    first_anchor: date | None
    last_anchor: date | None

    @property
    def hit_rate(self) -> float | None:
        return self.correct_calls / self.directional_calls if self.directional_calls else None

    @property
    def always_up_rate(self) -> float | None:
        return self.always_up_correct / self.directional_calls if self.directional_calls else None


@dataclass(frozen=True)
class BacktestResult:
    method: str
    factors: tuple[str, ...]
    horizons: tuple[BacktestHorizon, ...]
    notes: tuple[str, ...]


@dataclass
class Analysis:
    factors: list[Factor]
    coverage: float
    score: float | None
    verdict: str
    ranges: list[PriceRange]
    realized_volatility: float | None
    backtest: BacktestResult | None
    recorded_backtest: BacktestResult | None
    macro_channels: list[tuple[str, str]]
    positives: list[str]
    negatives: list[str]
    limitations: list[str]
    returns: dict[str, float | None]
    data_stale: bool
    sentiment: SentimentSummary | None = None
    election_reactions: list[ElectionReaction] = field(default_factory=list)
    next_election: date | None = None
    positioning: dict[str, float | None] = field(default_factory=dict)
    policy_channels: list[tuple[str, str]] = field(default_factory=list)
    research_insights: list[ResearchInsight] = field(default_factory=list)
