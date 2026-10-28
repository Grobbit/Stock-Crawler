"""Small, provider-independent types used by the collector and research engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class PricePoint:
    date: date
    close: float


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


@dataclass(frozen=True)
class AnnualFinancial:
    period_end: date
    revenue: float | None
    operating_income: float | None
    net_income: float | None


@dataclass(frozen=True)
class NewsItem:
    title: str
    publisher: str
    published_at: str
    url: str


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
