from dataclasses import replace
from datetime import timedelta

import pytest

from stock_crawler.analysis import WEIGHTS, analyze
from stock_crawler.demo import demo_snapshot
from stock_crawler.models import PricePoint
from stock_crawler.utils import normalize_ticker


def test_demo_has_consistent_bullish_conclusion_and_target():
    snapshot = demo_snapshot()
    analysis = analyze(snapshot)
    assert snapshot.demo
    assert analysis.verdict == "Bullish"
    assert analysis.coverage == pytest.approx(1.0)
    expected_score = sum(f.weight * f.score for f in analysis.factors if f.score is not None) / analysis.coverage
    assert analysis.score == pytest.approx(expected_score)
    assert sum(s.probability for s in analysis.scenarios) == pytest.approx(1)
    assert analysis.target == pytest.approx(sum(s.probability * s.price for s in analysis.scenarios))
    assert analysis.expected_return == pytest.approx(0.16 * analysis.score)
    assert analysis.scenarios[0].price > analysis.scenarios[1].price > analysis.scenarios[2].price
    assert analysis.target > snapshot.price


def test_bearish_data_produces_bearish_conclusion_not_perpetual_hedging():
    snapshot = demo_snapshot()
    snapshot.info.update({"revenueGrowth": -0.25, "operatingMargins": -0.2, "totalDebt": 20e9,
                          "totalCash": 1e9, "forwardPE": 90, "recommendationMean": 4.8})
    snapshot.prices = [PricePoint(point.date, 200 - index * 0.04, 200 - index * 0.04, point.volume)
                       for index, point in enumerate(snapshot.prices)]
    for code in ("DGS10", "UNRATE", "CPIAUCSL"):
        snapshot.macro[code] = replace(snapshot.macro[code], change_3m=1.0)
    analysis = analyze(snapshot)
    assert analysis.verdict == "Bearish"
    assert analysis.score <= -0.2
    assert analysis.target < snapshot.price
    assert analysis.scenarios[0].price > analysis.scenarios[-1].price


def test_missing_macro_or_stale_price_withholds_target():
    snapshot = demo_snapshot()
    snapshot.macro = {}
    analysis = analyze(snapshot)
    assert analysis.verdict == "Insufficient evidence"
    assert analysis.target is None
    assert any("macro" in note.lower() for note in analysis.limitations)

    snapshot = demo_snapshot()
    snapshot.prices = [replace(point, date=point.date - timedelta(days=30)) for point in snapshot.prices]
    analysis = analyze(snapshot)
    assert analysis.data_stale
    assert analysis.verdict == "Insufficient evidence"
    assert analysis.target is None


def test_old_macro_series_and_missing_fundamentals_are_not_imputed():
    snapshot = demo_snapshot()
    snapshot.macro = {key: replace(point, as_of=point.as_of - timedelta(days=100)) for key, point in snapshot.macro.items()}
    analysis = analyze(snapshot)
    assert next(f for f in analysis.factors if f.key == "macro").score is None
    assert analysis.target is None

    snapshot = demo_snapshot()
    for key in ("revenueGrowth", "operatingMargins", "totalDebt", "totalCash", "forwardPE"):
        snapshot.info[key] = None
    analysis = analyze(snapshot)
    assert analysis.verdict == "Insufficient evidence"
    assert analysis.target is None
    assert analysis.coverage == pytest.approx(WEIGHTS["momentum"] + WEIGHTS["analysts"] + WEIGHTS["headlines"] + WEIGHTS["macro"])


def test_macro_inputs_actually_change_model_and_target():
    snapshot = demo_snapshot()
    stressed = analyze(snapshot)
    snapshot.macro["DGS10"] = replace(snapshot.macro["DGS10"], change_3m=-0.5)
    snapshot.macro["UNRATE"] = replace(snapshot.macro["UNRATE"], change_3m=-0.3)
    eased = analyze(snapshot)
    assert next(f.score for f in eased.factors if f.key == "macro") > next(f.score for f in stressed.factors if f.key == "macro")
    assert eased.target > stressed.target


def test_quote_currency_units_are_never_silently_mixed():
    snapshot = demo_snapshot()
    snapshot.info["currency"] = "GBp"  # pence
    snapshot.info["financialCurrency"] = "GBP"  # pounds
    analysis = analyze(snapshot)
    balance = next(f for f in analysis.factors if f.key == "balance")
    assert balance.score is None
    assert any("currenc" in note.lower() for note in analysis.limitations)


def test_funds_do_not_receive_an_equity_model_conclusion():
    snapshot = demo_snapshot()
    snapshot.info["quoteType"] = "ETF"
    analysis = analyze(snapshot)
    assert analysis.verdict == "Insufficient evidence"
    assert analysis.target is None
    assert any("funds" in note.lower() for note in analysis.limitations)


@pytest.mark.parametrize("raw,expected", [(" aapl ", "AAPL"), ("brk-b", "BRK-B"), ("vod.l", "VOD.L"),
                                           ("^gspc", "^GSPC"), ("btc-usd", "BTC-USD"), ("eurusd=x", "EURUSD=X")])
def test_yahoo_symbol_formats(raw, expected):
    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize("raw", ["", "AAPL/../../x", "<script>", "AAPL MSFT", "A" * 26, "-AAPL"])
def test_invalid_symbols_rejected(raw):
    with pytest.raises(ValueError):
        normalize_ticker(raw)


def test_minor_unit_quotes_do_not_make_an_ambiguous_balance_ratio_even_if_labels_match():
    snapshot = demo_snapshot()
    snapshot.info["currency"] = "GBp"
    snapshot.info["financialCurrency"] = "GBp"
    balance = next(f for f in analyze(snapshot).factors if f.key == "balance")
    assert balance.score is None
