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
class Filing:
    form: str
    filing_date: date
    report_date: date | None
    url: str
    customer_excerpts: tuple[str, ...] = ()
    risk_excerpts: tuple[str, ...] = ()
    truncated: bool = False
    policy_excerpts: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnnualFinancial:
    period_end: date
    revenue: float | None
    operating_income: float | None
    net_income: float | None
    operating_cash_flow: float | None = None
    capital_expenditure: float | None = None
    free_cash_flow: float | None = None


@dataclass(frozen=True)
class NewsItem:
    title: str
    publisher: str
    published_at: str
    url: str
    language: str = ""
    related_symbols: tuple[str, ...] = ()


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


@dataclass
class Snapshot:
    requested_ticker: str
    ticker: str
    name: str
    info: dict[str, Any]
    prices: list[PricePoint]
    macro: dict[str, MacroPoint]
    fetched_at: datetime
    filing: Filing | None = None
    holdings: list[tuple[str, str, float | None]] = field(default_factory=list)
    annuals: list[AnnualFinancial] = field(default_factory=list)
    news: list[NewsItem] = field(default_factory=list)
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
class Scenario:
    label: str
    probability: float
    return_pct: float  # fraction, not percentage points
    price: float


@dataclass
class Analysis:
    factors: list[Factor]
    coverage: float
    score: float | None
    verdict: str
    target: float | None
    target_date: date
    expected_return: float | None
    scenarios: list[Scenario]
    spread: float | None
    spread_basis: str
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
