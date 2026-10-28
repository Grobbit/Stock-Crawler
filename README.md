# Stock Crawler

Stock Crawler turns a Yahoo Finance ticker into a structured, sourced **10–30 page PDF research report**. It combines company fundamentals, market positioning, headline tone, US macroeconomic and election context, and optional SEC annual-filing excerpts into a business overview, an evidence-weighted conclusion, bull/base/bear cases, and—when there is enough current evidence—an explicit **six-month price target**.

> **Important:** This is general research software, not personalized financial advice. Its model is a transparent, **uncalibrated heuristic**, not a proven forecasting system. Targets and scenario probabilities are illustrative; they can be wrong. Prices can fall and losses can be substantial. Check the underlying sources and consult a qualified professional as appropriate.

## What the report contains

The PDF has **22 numbered sections**, organized as a connected research memo rather than a dump of facts:

1. **Sections 1–2 — investment decision:** Stock Crawler's own bullish, bearish, mixed/neutral or insufficient-evidence conclusion, strongest supporting and opposing signals, last close and six-month target when permitted.
2. **Sections 3–4 — business and people:** company profile, available customer/concentration disclosures, management names and stewardship questions.
3. **Sections 5–8 — micro fundamentals and expectations:** price and valuation, growth and margins, up to four annual income and cash-flow observations, cash/debt, momentum and analyst recommendations over time when available.
4. **Sections 9–10 — market behavior and sentiment:** trading-volume and adjusted-price trends, short interest, one options-chain open-interest snapshot, eligible headline tone and a recent-versus-earlier headline comparison. These are partial proxies, not a complete measure of investor sentiment.
5. **Sections 11–12 — macro:** ten dated US observations, plus conditional explanations of how interest rates, inflation, employment, oil and the dollar could reach the particular business.
6. **Sections 13–15 — elected officials, policy and historical elections:** current US executive and congressional leaders, headquarters-state senators when available, the next scheduled federal general election, conditional policy channels and the ticker's adjusted-price windows around previous presidential and midterm elections, with aligned SPY comparisons when available.
7. **Sections 16–19 — outlook:** bull/base/bear scenarios, a six-month target when evidence supports it, bull and bear cases, and a monitoring checklist.
8. **Sections 20–22 — audit trail:** factor scorecard, explicit model rules, clickable sources, observation/retrieval dates and data gaps.

Each section starts on a new page; some continue onto additional pages. Generation checks that the finished PDF is **10–30 pages**. Named customers, officers, officials, headlines, financial statements and excerpts appear only when the sources supply them. Missing information is disclosed rather than invented. Election-window returns are **correlations, not proof that an election or politician caused a stock move**; no party or politician receives an arbitrary score in the target.

## Quick start: run it on your computer

### 1. Requirements

- Python **3.10 or newer** and `pip`.
- A modern browser and an internet connection for live reports.
- No API key is required for the core Yahoo Finance or FRED sources. SEC filing lookup is optional and needs an identifying contact string, explained below.

From a terminal, go to the directory containing this README:

```bash
cd Stock-Crawler
```

### 2. Install

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

**Windows PowerShell**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The Windows examples below use the virtual environment's Python directly, so changing the PowerShell execution policy is not necessary. On macOS/Linux, activate the environment as shown above in each new terminal, or use `./.venv/bin/python` in place of `python`.

### 3. Optional but recommended: enable SEC filings

For eligible US SEC registrants, this adds excerpts from the latest available 10-K, 20-F, or 40-F, including potentially useful customer-concentration, policy and risk disclosures. The SEC requires an identifying User-Agent. Use **your real name or organization and a real contact email**; do not use the example address literally.

Set the variable in the **same terminal** before starting the app:

```bash
# macOS / Linux
export SEC_USER_AGENT="Your Name your.real.email@example.com"
```

```powershell
# Windows PowerShell
$env:SEC_USER_AGENT = "Your Name your.real.email@example.com"
```

Replace the name and email with your actual contact details. The value must include both a name/organization and a valid-looking email address. `.env.example` is documentation only; the app does **not** automatically load it. Without this variable, the app still works but skips SEC lookup and explains the gap in the report. Not every ticker is an SEC registrant, and even a retrieved filing may not name individual customers. Filing excerpts are short search results; read the linked original for full context.

### 4. Start the application

```bash
# macOS / Linux, with the virtual environment active
python -m stock_crawler serve
```

```powershell
# Windows PowerShell
.\.venv\Scripts\python.exe -m stock_crawler serve
```

Open **http://127.0.0.1:8000** on the same computer. Keep the terminal open while using the app. To stop it, press **Ctrl+C** in that terminal. To use a different port, add `--port 8080` and open the corresponding address.

By default the server listens only on your computer. For a container or a development preview that needs a network interface, use `python -m stock_crawler serve --host 0.0.0.0 --port 8000`. **The application has no login or access control; do not expose it directly to the public internet.**

## Using the web app, step by step

1. Open the research desk at `http://127.0.0.1:8000`.
2. To test the complete workflow without a network connection, click **Explore a sample** in the top-right corner. This creates a report for the entirely fictional `DEMO` company. Its company, people, politicians, election outcomes, financial figures, prices, analyst views, options, news, filing excerpts and macro data are synthetic—not a real investment recommendation. Federal election dates still follow the real calendar rule.
3. For a live report, type a Yahoo Finance symbol in **Ticker symbol**. For example, enter `AAPL`, `MSFT`, or `BRK-B`. The example chips fill the field; you still need to click **Generate research report** (or press Enter).
4. The status panel shows the collection, analysis and PDF stages. Leave the page open. Time varies with external providers and their rate limits; a report is not a streaming live quote.
5. When the report is ready, review the displayed conclusion, target, closing-price date and factor coverage. Expand **Data notes & limitations** to see missing sources and cautions.
6. Click **Open research report** to view the PDF in a new tab, or the download icon to save it. Use **Research another ticker** to start over.
7. For web jobs, a copy is also saved as `reports/<job-id>.pdf` in the project directory. Your browser download uses a descriptive ticker/date filename. `reports/` is intentionally ignored by Git. Set `STOCK_CRAWLER_REPORT_DIR` before startup to change the server's output directory.

Each report is a point-in-time snapshot. Run it again after earnings, major news or meaningful macro changes. The application keeps job status in memory for up to 24 hours; restarting the server loses the status/download link, although the already-created PDF remains in the output directory. The local queue runs up to two reports at once and accepts up to six queued or running jobs.

### Which ticker should I enter?

Use the symbol **as Yahoo Finance spells it**, including exchange suffixes where required:

| Instrument | Example | What to expect |
| --- | --- | --- |
| US stock | `AAPL`, `MSFT`, `BRK-B` | Company research when the source has sufficient data. |
| International stock | `VOD.L`, `7203.T` | Coverage and reporting currency vary. US macro is only a partial proxy for local conditions. |
| Fund | `SPY` | A report can include price and available holdings, but the single-company verdict and target are withheld. |
| Index / cryptocurrency / currency pair | `^GSPC`, `BTC-USD`, `EURUSD=X` | The provider may return price history, but company-specific fundamentals, verdict and target are generally not applicable. |

Yahoo Finance does not cover every security or exchange, and an otherwise valid symbol may temporarily be unavailable or rate-limited. This tool cannot guarantee data for literally every ticker. Search Yahoo Finance for the exact listing if a symbol fails. The last **daily close**—not an intraday quote—is the model anchor, and the target date is six calendar months after that close. Price returns and targets exclude dividends.

## Generate a PDF from the command line

From the project directory with dependencies installed:

```bash
# Live research; writes reports/AAPL-research.pdf by default
python -m stock_crawler report AAPL

# Choose the destination
python -m stock_crawler report BRK-B --output reports/berkshire.pdf

# Entirely fictional, offline example
python -m stock_crawler report --demo --output reports/sample.pdf
```

On Windows, replace `python` with `.\.venv\Scripts\python.exe` if you did not activate the virtual environment. The CLI prints the saved path and conclusion, and prints data warnings to standard error. It exits nonzero if the symbol, market data, or PDF generation fails. Set `SEC_USER_AGENT` in the terminal first if you want SEC excerpts.

## Sources, freshness and coverage

Live research requires outbound access to the following public providers. The offline demo requires none of them.

| Source | Used for | Caveats |
| --- | --- | --- |
| [Yahoo Finance](https://finance.yahoo.com/) via the unofficial `yfinance` library | Profile, officers, financial metrics, annual income and cash-flow statements, analyst snapshots, fund holdings, up to 10 years of daily close/adjusted close/volume, SPY history, short-interest/ownership fields, one options chain, and up to 20 linked headlines | Coverage, periods and freshness vary. Values may be delayed, revised, incomplete or rate-limited; provider terms and availability apply. Price history falls back to one year if 10 years cannot be fetched. Headline relevance and claims are not independently verified. |
| [FRED](https://fred.stlouisfed.org/) public CSV series | 10-year Treasury yield (`DGS10`), fed funds (`DFF`), CPI (`CPIAUCSL`), unemployment (`UNRATE`), WTI oil (`DCOILWTICO`), dollar index (`DTWEXBGS`), real GDP (`GDPC1`), 10-year minus 2-year yield spread (`T10Y2Y`), high-yield credit spread (`BAMLH0A0HYM2`) and VIX (`VIXCLS`) | Each series has its own observation date and publication lag. CPI and real GDP are year-over-year growth versus the same calendar month/quarter a year earlier. Changes compare against the nearest observation at or before three calendar months earlier. These US indicators are not a complete local/global picture. |
| [unitedstates/congress-legislators](https://github.com/unitedstates/congress-legislators) public CC0 dataset, retrieved via GitHub's API | US president and vice president, congressional leadership, recognized US headquarters-state senators and historical presidential terms | Community-maintained, not an official live feed. Recorded dates and party labels can lag vacancies or changes. Data are cached in process for six hours; the PDF shows the oldest included dataset's actual fetch time. GitHub access, rate limits and retrieval errors can leave this section incomplete. Verify current officeholders with official sources. |
| [USA.gov election calendar](https://www.usa.gov/presidential-election-process) and [midterm guide](https://www.usa.gov/midterm-elections) | Standard US federal general-election dates | Scheduled dates are not predictions of candidates or results; primaries and special elections are outside this calculation. |
| [VADER](https://github.com/cjhutto/vaderSentiment) | English-language headline-tone scoring | A general-language dictionary model with a small explicit finance-word override; it can misread financial context, sarcasm and headlines whose language is unknown. |
| [SEC EDGAR](https://www.sec.gov/edgar), optional | Latest available 10-K / 20-F / 40-F and bounded customer, risk and policy excerpts | Requires `SEC_USER_AGENT`, an exact registrant match and SEC access. The PDF links the original filing. Only the first 10 MB is searched if larger, with a warning; snippets are not a complete analysis. |

The PDF uses source markers `[Q]` (profile/statistics), `[H]` (price history), `[A]` (analysts), `[S]` (annual statements), `[F]` (SEC filing), `[M1]`–`[M10]` (FRED), `[N]` (headlines), `[O]` (options), `[B]` (SPY), `[P]` (political dataset), `[E]` (election calendar) and `[V]` (VADER). The fictional sample uses `[D]` instead. The final section lists clickable source links and dates. Providers receive the requested ticker or data requests; if enabled, the SEC also receives your configured User-Agent.

### How to read the political and election analysis

- The official list is a **dated snapshot**, not an assertion that a politician supports, owns or directly affects the company. A headquarters-state senator is shown because of the provider-reported headquarters location; operations and customers may be elsewhere. For foreign or unrecognized headquarters, no state senator is inferred. Presidential election winners are identified only when the source records an election-based January presidential term that has already started; missing or not-yet-established outcomes are labeled as such.
- Federal general elections are calculated as the Tuesday after the first Monday in November in even-numbered years; presidential elections occur every four years and other even years are midterms. The report names the next scheduled general election and adds it to the monitoring checklist if it falls within the six-month horizon.
- For each available historical election, the anchor is the **last adjusted close before election day** (no more than seven calendar days earlier). The table shows returns after 10, 63 and 126 subsequent observed trading sessions where data exist. For USD-denominated equities and ETFs, the 63-session SPY comparison is shown **only if the same anchor and end dates exist** in both histories. Adjusted prices account for provider-reported splits/distributions; provider corrections, currencies and international trading calendars can affect comparability. A recent listing or missing adjusted prices can leave no usable windows.
- These windows overlap with earnings, recessions, wars, interest-rate changes and other events. They do **not** identify the causal effect of an election, politician, party or policy, and are not a political coefficient in the target. Sector policy channels are conditional possibilities to verify against the company's actual filings, contracts and geographic exposures—not predictions that a proposal will pass.

### How sentiment and positioning are measured

The app scores at most 20 provider-linked headlines. To enter the 30-day sample, a headline must have a parseable date in the past 30 calendar days, not be a duplicate, not be explicitly tagged as non-English, and match the ticker/company name or a provider-supplied related ticker. This heuristic can miss relevant stories or include unrelated ones; unknown-language text can still be misread. All eligible headlines used are listed in section 10 with individual tone and links. VADER compound scores of `≥0.05` are positive, `≤-0.05` negative and between them neutral. A mean and the 8%-weight factor require **at least five** eligible headlines. A time comparison requires **at least three** in each window: days 0–7 and days 8–30. Samples can differ across windows, so a difference is not proof that all investors' sentiment changed.

The finance lexicon overrides are: `beat/beats` +1.4, `upgrade/upgrades` +1.6, `downgrade/downgrades` -1.6, `miss/misses` -1.2, `bankruptcy` -2.5, `layoffs` -1.7, `surge` +1.2 and `plunge` -1.7. This is not FinBERT, social-media sentiment, article verification or comprehensive news coverage. No article text or paid sentiment feed is analyzed.

Positioning is descriptive rather than an additional model factor: the latest 20 trading sessions' average volume is compared with the previous 60, adjusted prices are compared with 50- and 200-session averages, and 63 daily log returns are annualized for realized volatility. The report shows provider-reported short interest and institutional ownership when available. For options, it selects the available expiration **7–90 days away closest to 45 days**, and reports known put and call open interest. The put/call ratio is withheld unless both sides have complete valid open-interest data and call open interest is positive. Open interest can reflect hedges or spreads; volume is not buy/sell flow and neither identifies trader intent. These figures can be stale or incomplete.

## How the conclusion and six-month target are calculated

This is a deterministic rule-based model, **not** an LLM and **not** a measured consensus of all investors. The separately displayed provider analyst recommendation is an outside analyst average; it is not the Stock Crawler verdict. The complete scorecard and current inputs appear in each report.

### 1. Score the available evidence

Each signal lies between **-1 and +1**. Missing data are excluded, not treated as zero. The overall score is `sum(weight × available signal) / sum(available weights)`, and coverage is the sum of the available weights.

| Factor | Weight | Rule |
| --- | ---: | --- |
| Provider revenue growth | 17% | `≥15%, ≥5%, ≥-5%, ≥-15%, otherwise` map to `+1, +0.5, 0, -0.5, -1`. |
| Operating margin | 14% | `≥20%, ≥10%, ≥0%, ≥-10%, otherwise` map to the same five scores. |
| Balance sheet | 10% | Apply `≥10%, ≥0%, ≥-30%, ≥-75%, otherwise` to **negative** `(debt - cash) / market capitalization`. Excluded for financial institutions or when required values or matching currency units are absent. |
| Forward P/E | 10% | Divide forward P/E by a fixed sector heuristic anchor. A ratio `≤0.75, ≤1, ≤1.25, ≤1.75, otherwise` maps to `+1, +0.5, 0, -0.5, -1`. The anchor is an assumption, **not** an observed peer average. Unknown sectors and REITs are not scored on P/E. |
| Six-month price trend | 12% | Close-to-close price return `≥20%, ≥5%, ≥-5%, ≥-20%, otherwise` maps to `+1, +0.5, 0, -0.5, -1`. Past performance is not a forecast. |
| Analyst sentiment | 9% | With at least three opinions, score `3 - recommendation mean` at thresholds `≥1, ≥0.5, ≥-0.5, ≥-1, otherwise`. Provider scale: 1 = strong buy, 5 = sell. |
| Headline tone | 8% | With at least five eligible recent headlines, `mean VADER compound × 2`, capped to `-1…+1`; see the sampling and language caveats above. |
| Macro overlay | 20% | Directional sector assumptions applied to recent changes in yields, unemployment and CPI; oil also enters for selected upstream-energy or airline industries. Details below. |

The fixed P/E anchors are: Technology 25, Communication Services 20, Consumer Cyclical 23, Consumer Defensive 20, Healthcare 20, Financial Services 12, Industrials 20, Basic Materials 15, Energy 12 and Utilities 18. These deliberately simple reference values do not account for each company's growth, accounting, peers or capital structure.

**Macro calculation:** For each relevant series, divide its roughly three-month change by a normalizing move: 0.5 percentage points for the 10-year yield, 0.4 points for unemployment, 0.8 points for CPI year-over-year inflation, or 20% for oil. Cap each normalized move at `-1…+1`. Multiply it by the assumed signed sector sensitivity and divide the sum by the sum of the absolute included sensitivities. At least two relevant series no more than 90 days old are required. A higher yield/unemployment/inflation generally receives a negative assumed sensitivity; for financial services the rate sensitivity is zero because its effect is ambiguous. Oil is `+1` for selected upstream energy industries and `-1` for airlines. The report shows the sector's actual sensitivities. These are **subjective transmission assumptions, not estimated stock correlations**; fed funds, the dollar, GDP growth, the yield curve, credit spread and VIX are shown as context but do not enter the score.

A **verdict and target are withheld** unless all of the following are true:

- The instrument is an equity, and its last close is at most 14 calendar days old.
- At least **65%** of the total factor weight is available.
- At least **two** of revenue growth, profitability, balance sheet and valuation are available.
- The macro overlay has at least two recent, relevant inputs.

When these checks pass: score `≥ +0.20` is **bullish**; `≤ -0.20` is **bearish**; values in between are **mixed/neutral**. Otherwise the conclusion is **insufficient evidence**. Coverage measures input availability, not statistical confidence.

### 2. Translate the score into scenarios

- Base six-month **price** return = `0.16 × normalized score`.
- The bull and bear returns add/subtract a scenario half-width. With a usable provider beta `(0 < beta ≤ 5)`, the half-width is `20% × beta`, capped between 12 and 35 percentage points. Otherwise it is 20 percentage points. Beta is a historical market-sensitivity proxy, not a volatility estimate.
- Assumed weights are **25% bull / 50% base / 25% bear**. Each scenario price is `last close × (1 + scenario return)`; the target is the probability-weighted average of those three prices. Because the weights and spread are symmetric, that target equals the base scenario price before rounding.
- The multipliers, weights, cutoffs and scenario width are judgmental, uncalibrated assumptions—not empirically estimated probabilities, a confidence interval, or a guarantee. Dividends, taxes and trading costs are not included.

For example, a hypothetical $100 close, score of `+0.30` and beta of `1.0` produce a base return of `+4.8%`, a bull return of `+24.8%` and a bear return of `-15.2%`. The illustrative 25/50/25 weighted target is **$104.80**. The macro inputs affect that target through their 20% share of the evidence score when the quality gates pass.

Financial-statement and quote currencies are kept distinct. Ratios combining them are withheld if their units differ, are unknown, or the quote uses a potentially ambiguous minor unit—for example, `GBp` pence is not silently treated as `GBP` pounds. For known minor-unit quotes, market capitalization and enterprise value are displayed in provider-reported units rather than assuming a denomination. The model does not do currency conversion, peer normalization, discounted cash-flow valuation, earnings-date prediction, portfolio sizing, or personalized risk assessment.

## Troubleshooting

- **No usable price history / ticker not found:** Check the Yahoo Finance symbol and exchange suffix. Confirm that your machine can reach Yahoo Finance, then retry later; the unofficial source may rate-limit requests. Some valid securities simply are not covered.
- **“Insufficient evidence” or no target:** Open **Data notes & limitations** and the report's scorecard. Missing or stale macro data, fewer than two company fundamentals, less than 65% coverage, an old close, or a non-equity instrument intentionally prevent a target. Missing data are not replaced with guesses.
- **No customer names or SEC excerpts:** Set `SEC_USER_AGENT` before starting the server, use a matching US SEC registrant symbol, and check network access to SEC EDGAR. Many issuers do not disclose named customers. The latest filing may not be available or an excerpt search may miss relevant context.
- **No macro values:** Check access to `fred.stlouisfed.org`; corporate networks and firewalls can block it. The app shows the gap and withholds the target if it cannot build a usable macro overlay.
- **No officials or election winners:** Check access to `api.github.com` and GitHub rate limits. The community dataset may be unavailable, stale or missing a record; the report does not guess names or future outcomes. Historical price windows can still be shown when available.
- **No election windows or SPY comparison:** The ticker may be recently listed, lack adjusted prices or have a different calendar; SPY comparisons require an eligible USD-denominated instrument and exact matching dates.
- **No headline score or trend:** Fewer than five eligible, dated, issuer-matched headlines in the last 30 days leaves the factor unscored; a trend needs three in each time bucket. Check the listed headlines rather than treating missing news as neutral.
- **No options ratio:** No suitable expiration, a missing contract field, an incomplete chain or zero call open interest prevents a reliable ratio.
- **Wrong currency or unfamiliar units:** Check the quote and reporting currency in the source. International listings can use a minor unit such as `GBp`. The app does not apply an implicit FX conversion.
- **Page says queue full:** Wait for an existing report to finish and try again. Restarting the server clears the in-memory queue and job links.
- **Port already in use:** Start with `--port 8080` and visit `http://127.0.0.1:8080` instead.
- **An old PDF doesn't update:** Reports are snapshots. Generate a new one to fetch the latest available data.

## Development and tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m stock_crawler report --demo --output reports/sample.pdf
```

The test suite uses synthetic fixtures and mocked providers, so it does not need live market access. The app exposes an interactive API reference at `/docs` while the server is running. The main endpoints are `POST /api/reports` (`{"ticker":"AAPL","demo":false}`), `GET /api/reports/{id}` for progress and `GET /api/reports/{id}/pdf` for the completed document. The server is a local single-process tool, not a production multi-user deployment.

The UI bundles DM Sans and DM Serif Display under the SIL Open Font License; their license files are in `stock_crawler/static/fonts/`.
