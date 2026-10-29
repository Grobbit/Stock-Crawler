import math
import statistics
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from stock_crawler.analysis import analyze
from stock_crawler.backtest import realized_volatility
from stock_crawler.demo import demo_snapshot
from stock_crawler.models import PeerGroup, PeerValuation, PricePoint
from stock_crawler.sources import peers


def test_volatility_uses_63_adjusted_log_returns_not_beta_or_raw_close():
    day = date(2024, 1, 1)
    adjusted = [100.0]
    for i in range(63):
        adjusted.append(adjusted[-1] * math.exp(0.002 if i % 2 else -0.001))
    points = [PricePoint(day + timedelta(days=i), 999 + i * 4, value) for i, value in enumerate(adjusted)]
    returns = [math.log(adjusted[i] / adjusted[i - 1]) for i in range(1, 64)]
    assert realized_volatility(points) == pytest.approx(statistics.stdev(returns) * math.sqrt(252))
    assert realized_volatility(points[:63]) is None
    assert realized_volatility(points[:20] + [replace(points[20], adjusted_close=None)] + points[21:]) is None
    assert realized_volatility([replace(point, adjusted_close=100) for point in points]) is None
    gap = points[:32] + [replace(p, date=p.date + timedelta(days=20)) for p in points[32:]]
    assert realized_volatility(gap) is None


def test_all_range_formulas_share_score_but_scale_to_each_horizon():
    snapshot = demo_snapshot()
    analysis = analyze(snapshot)
    assert analysis.realized_volatility is not None
    for item in analysis.ranges:
        drift = 0.16 * analysis.score * item.months / 6
        shock = analysis.realized_volatility * math.sqrt(item.months / 12)
        assert item.low == pytest.approx(snapshot.price * math.exp(drift - shock))
        assert item.high == pytest.approx(snapshot.price * math.exp(drift + shock))
        assert item.log_drift == pytest.approx(drift)
        assert item.log_half_width == pytest.approx(shock)
    assert analysis.ranges[0].log_half_width < analysis.ranges[1].log_half_width < analysis.ranges[2].log_half_width


def test_missing_adjusted_prices_withhold_ranges_and_history_without_guessing():
    snapshot = demo_snapshot()
    snapshot.prices = [replace(point, adjusted_close=None) for point in snapshot.prices]
    analysis = analyze(snapshot)
    assert analysis.realized_volatility is None
    assert analysis.ranges == []
    assert analysis.backtest is None
    assert next(f.score for f in analysis.factors if f.key == "momentum") is None


def valuation(snapshot):
    return next(f for f in analyze(snapshot).factors if f.key == "valuation")


def test_forward_pe_uses_same_industry_peer_median_and_excludes_bad_members():
    snapshot = demo_snapshot()
    industry = snapshot.info["industry"]
    snapshot.info["forwardPE"] = 20
    members = (
        PeerValuation("PEER1", "One", industry, 10),
        PeerValuation("PEER2", "Two", industry, 20),
        PeerValuation("PEER3", "Three", industry, 30),
        PeerValuation("peer3", "Duplicate", industry, 1000),
        PeerValuation(snapshot.ticker, "Issuer", industry, 1000),
        PeerValuation("NEG", "Negative earnings", industry, -50),
    )
    snapshot.peers = PeerGroup("sample", industry, members, snapshot.fetched_at)
    result = valuation(snapshot)
    assert result.score == 0.5
    assert "20.0x median across 3" in result.evidence
    snapshot.peers = replace(snapshot.peers, members=members[:2])
    assert valuation(snapshot).score is None
    snapshot.peers = replace(snapshot.peers, members=members, industry="Unrelated")
    assert valuation(snapshot).score is None
    snapshot.peers = replace(snapshot.peers, industry=industry)
    snapshot.info["forwardPE"] = 0
    assert valuation(snapshot).score is None
    snapshot.info["forwardPE"] = 20
    snapshot.info["sector"] = "Real Estate"
    assert valuation(snapshot).score is None


def test_peer_provider_verifies_industry_equity_positive_pe_and_caps_candidates(monkeypatch):
    info = {"industry": "Software - Infrastructure", "industryKey": "software-infrastructure", "sector": "Technology"}
    data = {
        "A": {"quoteType": "EQUITY", "industry": info["industry"], "forwardPE": 10},
        "B": {"quoteType": "EQUITY", "industryKey": info["industryKey"], "forwardPE": 20},
        "C": {"quoteType": "EQUITY", "industry": info["industry"], "forwardPE": 30},
        "D": {"quoteType": "EQUITY", "industry": "Other", "industryKey": "other", "forwardPE": 5},
        "E": {"quoteType": "ETF", "industry": info["industry"], "forwardPE": 12},
        "F": {"quoteType": "EQUITY", "industry": info["industry"], "forwardPE": -5},
        "G": {"quoteType": "EQUITY", "industry": info["industry"], "forwardPE": None},
        "H": {"quoteType": "EQUITY", "industry": info["industry"], "forwardPE": 40},
        "I": {"quoteType": "EQUITY", "industry": info["industry"], "forwardPE": 50},
    }
    symbols = ["ISSUER", "A", "B", "C", "D", "E", "F", "G", "H", "I"]
    monkeypatch.setattr(peers.yf, "Industry", lambda key: SimpleNamespace(top_companies=pd.DataFrame({"marketCap": [1] * len(symbols)}, index=symbols)))
    monkeypatch.setattr(peers.yf, "Ticker", lambda symbol: SimpleNamespace(get_info=lambda: data[symbol]))
    group, warnings = peers.fetch_peers("ISSUER", info)
    assert [p.ticker for p in group.members] == ["A", "B", "C", "H"]
    assert not warnings
    assert group.retrieved_at.tzinfo is not None
    missing, warnings = peers.fetch_peers("ISSUER", {"sector": "Technology"})
    assert missing is None and "unavailable" in warnings[0]
