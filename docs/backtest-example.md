# Published historical example: AAPL momentum subset

This is a **real historical, retrospective example of only the momentum factor**, not a backtest of the full Stock Crawler scorecard. It uses a third-party snapshot of AAPL daily `Adj Close` observations through **2024-08-02**. The source repository describes its dataset as collected from Alpha Vantage; we have not independently verified the original feed or its adjustment methodology. The example is not a forecast, recommendation, or statistically significant validation. It was calculated after the data were available, for one surviving, user-selected company.

| Horizon | Directional calls correct / total | Hit rate | Always-up on the same dates | Partial bounds: adjusted-return coverage |
| --- | ---: | ---: | ---: | ---: |
| 1 month | 43 / 76 | **56.6%** | 61.8% | 58 / 93 (62.4%) |
| 3 months | 18 / 31 | **58.1%** | 64.5% | 25 / 38 (65.8%) |
| 6 months | 9 / 15 | **60.0%** | 66.7% | 13 / 19 (68.4%) |

The simple always-up baseline did better than the tested subset at all three horizons in this sample. Directional anchors run 2014-08-29 through 2024-01-31 for 1 and 3 months, and 2014-08-29 through 2023-11-30 for 6 months. Bullish/bearish calls were 58/18, 23/8 and 12/3, respectively. The adjusted-return coverage denominators differ from directional-call denominators because range coverage includes eligible neutral-score windows; neither percentage is a probability forecast.

## Reproduce

Install the locked environment described in the [README](../README.md). The dataset is **not** bundled or relicensed by this project. Download the exact third-party file on your own machine, respecting the original provider's data terms:

```bash
curl -L 'https://github.com/simonMakumi/APPLE-stock-price-prediction/raw/3c53c433b54add0579c054199162c19a37460f2c/data/apple_stock_and_interest_rates.csv' -o aapl-history.csv
sha256sum aapl-history.csv
# Expected: 522978d76511ac136b55898fdc3e23e00739f5e8db26c78fb31ca452115daf1f
uv run --locked python -m stock_crawler backtest AAPL --prices aapl-history.csv --sector Technology
```

Source: [`simonMakumi/APPLE-stock-price-prediction`](https://github.com/simonMakumi/APPLE-stock-price-prediction/tree/3c53c433b54add0579c054199162c19a37460f2c), file [`data/apple_stock_and_interest_rates.csv`](https://github.com/simonMakumi/APPLE-stock-price-prediction/blob/3c53c433b54add0579c054199162c19a37460f2c/data/apple_stock_and_interest_rates.csv), Git blob `2962660a800450c0d914c60b2f4199cdb8d3ca45`. The upstream repository declares MIT licensing, but underlying market-data rights and completeness remain the responsibility of the original providers and users. The additional `Interest_Rate` column is **not used**. No FRED CSVs are supplied, so this test is momentum-only even though a sector is specified.

The code takes the last ten years of available data, generates month-end signals from the six-month adjusted-close return using the live momentum thresholds, and evaluates non-overlapping subsequent 1-, 3- and 6-calendar-month windows. It excludes neutral signals and exactly flat outcomes from the directional hit rate, uses the same eligible dates for the always-up baseline, and applies the same 63-return volatility formula with the **partial** score for historical adjusted-return coverage. This does not directly validate price-only full-score ranges; adjusted returns can reflect distributions and splits. It does not include costs, taxes, delisted securities or the portfolio effects of trading. Adjusted returns, the historical-volatility ranges and the future close are based on the supplied provider data; no independent reconciliation is performed.

Historical financial statements, contemporaneous peer sets, analyst opinions and news are not reconstructed. When optional current-vintage FRED data are supplied for other tests, assumed release delays do **not** correct for revised observations, and current sector labels may introduce hindsight. See the README for these limitations and for the separate, locally recorded full-scorecard evaluation that begins only when genuinely timestamped live verdicts have matured.
