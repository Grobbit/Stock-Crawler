"""Small, explicit same-industry peer sample from Yahoo Finance.

This is not a comprehensive or survivorship-free peer universe. If Yahoo's
industry list or individual forward P/Es are missing, valuation is withheld.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import yfinance as yf

from stock_crawler.models import PeerGroup, PeerValuation
from stock_crawler.utils import normalize_ticker, number, text

MIN_PEERS = 3
MAX_CANDIDATES = 8


def _industry_key(info: dict) -> str:
    key = text(info.get("industryKey"), 90).lower()
    if not key:
        key = re.sub(r"[^a-z0-9]+", "-", text(info.get("industry"), 90).lower()).strip("-")
    return key if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", key) else ""


def fetch_peers(ticker: str, info: dict) -> tuple[PeerGroup | None, list[str]]:
    industry = text(info.get("industry"), 100)
    key = _industry_key(info)
    if not industry or not key or text(info.get("sector"), 80) == "Real Estate":
        return None, ["A comparable industry peer list was unavailable or inapplicable; forward P/E is not scored."]
    try:
        candidates = yf.Industry(key).top_companies
        if candidates is None or candidates.empty:
            raise ValueError("No industry candidates")
        symbols = []
        for raw in candidates.index:
            try:
                symbol = normalize_ticker(str(raw))
            except ValueError:
                continue
            if symbol != ticker.upper() and symbol not in symbols:
                symbols.append(symbol)
            if len(symbols) == MAX_CANDIDATES:
                break
    except Exception:
        return None, ["Yahoo's industry peer list was unavailable; forward P/E is not scored."]

    def lookup(symbol: str) -> PeerValuation | None:
        try:
            other = yf.Ticker(symbol).get_info() or {}
            if not isinstance(other, dict) or str(other.get("quoteType", "")).upper() != "EQUITY":
                return None
            other_industry = text(other.get("industry"), 100)
            other_key = text(other.get("industryKey"), 90).lower()
            # Never use merely same-sector companies as comparable peers.
            if not (other_industry and other_industry.casefold() == industry.casefold()) and not (other_key and other_key == key):
                return None
            multiple = number(other.get("forwardPE"))
            if multiple is None or multiple <= 0:
                return None
            return PeerValuation(symbol, text(other.get("shortName") or other.get("longName") or symbol, 80),
                                 other_industry or industry, multiple,
                                 revenue_growth=number(other.get("revenueGrowth")),
                                 operating_margin=number(other.get("operatingMargins")))
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="peers") as pool:
        members = tuple(peer for peer in pool.map(lookup, symbols) if peer is not None)
    group = PeerGroup(key, industry, members, datetime.now(timezone.utc))
    warnings = [] if len(members) >= MIN_PEERS else [
        f"Only {len(members)} verified same-industry peers with positive forward P/E were found; at least {MIN_PEERS} are required for the valuation score."
    ]
    return group, warnings
