# Stock Crawler

Stock Crawler turns a ticker into a structured, sourced **10–30 page PDF research report**. It connects company fundamentals, customers, management, market positioning, headline tone, US macroeconomic and election context, and optional SEC filing excerpts into a ticker-specific investment narrative, an evidence-weighted conclusion and opposing cases. When the necessary inputs are available, it shows **1-, 3- and 6-month realized-volatility-based price ranges**, rather than a single target.

> **Important:** This is general research software, not personalized financial advice. Its transparent model is an **uncalibrated heuristic**, not a proven forecasting system. Ranges are illustrative, not confidence intervals or guarantees. Prices can fall and losses can be substantial. Check the underlying sources and consult a qualified professional as appropriate.

## What the report contains

The PDF has **23 numbered sections**, organized as a connected research memo rather than a dump of facts:

1. **Sections 1–2 — investment decision:** Stock Crawler's own bullish, bearish, mixed/neutral or insufficient-evidence conclusion, strongest supporting and opposing signals, last close and all three illustrative ranges when permitted.
2. **Sections 3–4 — business and people:** company profile, available customer and issuer-disclosed revenue-mix evidence, recent operating disclosures, management names and stewardship questions. An identity-checked Wikidata profile can add product or subsidiary leads, explicitly marked as potentially stale.
3. **Sections 5–8 — micro fundamentals and expectations:** price and valuation; matched quarterly and annual growth versus margins; cash conversion, stock compensation and diluted shares when available; peer growth and margins; cash/debt, momentum and analyst recommendations. Insights explain why a company-specific observation matters without assuming its cause.
4. **Sections 9–10 — market behavior and sentiment:** trading-volume and adjusted-price trends, short interest, one options-chain snapshot, eligible headline tone, independent news leads, recent SEC 8-K events and optional indexed-web leads. These are partial proxies, not a complete measure of investor sentiment.
5. **Sections 11–12 — macro:** ten dated US observations, plus conditional explanations of how interest rates, inflation, employment, oil and the dollar could reach the particular business.
6. **Sections 13–15 — elected officials, policy and historical elections:** current US executive and congressional leaders, headquarters-state senators when available, the next scheduled federal general election, conditional policy channels and the ticker's adjusted-price windows around previous presidential and midterm elections, with aligned SPY comparisons when available.
7. **Sections 16–17 — outlook and historical evidence:** 1-, 3- and 6-month ranges, the retrospective subset hit rate and any matured, locally recorded full-scorecard verdicts.
8. **Sections 18–20 — competing cases:** bull and bear cases and a monitoring checklist, tied back to the company's evidence and macro channels.
9. **Sections 21–23 — audit trail:** factor scorecard, explicit model rules, clickable sources, observation/retrieval dates and data gaps.

Each section starts on a new page; some continue onto additional pages. Generation checks that the finished PDF is **10–30 pages**. Named customers, officers, officials, headlines, financial statements and excerpts appear only when the sources supply them. Missing information is disclosed rather than invented. Election-window returns are **correlations, not proof that an election or politician caused a stock move**; no party or politician receives an arbitrary score in the scorecard.

## Quick start: run it on your computer

### 1. Requirements

- Python **3.10 or newer** and `pip`.
- A modern browser and an internet connection for live reports.
- No API key is required for the core Yahoo Finance, FRED, GDELT or Wikidata sources. For substantially richer US-company research, configure the SEC contact string below. Brave indexed-web search is a separate optional, potentially paid add-on.

From a terminal, go to the directory containing this README:

```bash
cd Stock-Crawler
```

### 2. Install from the lockfile

The checked-in `uv.lock` resolves transitive dependencies for supported Python versions. These commands install `uv` **0.13.6** only as a bootstrap tool and create a reproducible project environment. `--inexact` keeps that bootstrap tool in the same environment; the application packages still come from the lockfile.

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install uv==0.13.6
uv sync --locked --inexact
```

**Windows PowerShell**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install uv==0.13.6
.\.venv\Scripts\uv.exe sync --locked --inexact
```

The Windows examples below use the virtual environment's Python directly, so changing the PowerShell execution policy is not necessary. On macOS/Linux, activate the environment as shown above in each new terminal, or use `./.venv/bin/python` in place of `python`. If a previously installed `uv` is already on your PATH, `uv sync --locked` is also sufficient. `requirements.txt` and `requirements-dev.txt` are legacy ranged-install alternatives and **do not** provide the same locked reproducibility.

### 3. Optional but recommended: enable SEC filings

For eligible US SEC registrants, this enables the latest available annual filing and, when newer, its 10-Q; recent 8-K metadata; bounded customer, operating, policy and risk excerpts; and SEC CompanyFacts financial history. When the filing's inline XBRL supplies suitable contexts, the app also tries to reconcile product, segment or geographic revenue to the consolidated total. Availability varies greatly. The SEC requires an identifying User-Agent. Use **your real name or organization and a real contact email**; do not use the example address literally.

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

### 3b. Optional: add broader indexed-web leads with Brave Search

The default app already checks The GDELT Project's independent news index and identity-matched Wikidata where possible. For additional **search leads**, create a Search API key in the [Brave Search API dashboard](https://api-dashboard.search.brave.com/) and check [current pricing and terms](https://brave.com/search/api/) before use. This is optional: the app works without it. A live report sends up to **two searches** containing the company name, ticker and research topics to Brave. Search results are indexed titles/snippets and links, not verified facts; the app does not automatically visit arbitrary result pages. Brave's index is not the entire internet.

```bash
# macOS / Linux: use your actual key, in the same terminal before starting
export BRAVE_SEARCH_API_KEY="your-private-brave-key"
```

```powershell
# Windows PowerShell
$env:BRAVE_SEARCH_API_KEY = "your-private-brave-key"
```

Treat the key as a secret: do not commit it or put it in a public issue. Your Brave account may incur usage charges; configure an account budget/limit if offered. A public deployment lets visitors trigger searches on **your** account, so enable the shared password and/or tighten the app's report limits before adding a billable key. Remove the variable and restart to disable Brave. Failed search requests produce a report warning and do not prevent a PDF.

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

By default the server listens only on your computer. For a container or a development preview that needs a network interface, use `python -m stock_crawler serve --host 0.0.0.0 --port 8000`. The port defaults to the `PORT` environment variable when present, otherwise `8000`. The app is **public by default** when exposed to the internet; an optional shared password is described in the Render section below.

## Using the web app, step by step

1. Open the research desk at `http://127.0.0.1:8000`.
2. To test the complete workflow without a network connection, click **Explore a sample** in the top-right corner. This creates a report for the entirely fictional `DEMO` company. Its company, people, politicians, election outcomes, financial figures, prices, analyst views, options, news, filing excerpts and macro data are synthetic—not a real investment recommendation. Federal election dates still follow the real calendar rule.
3. For a live report, type a Yahoo Finance symbol in **Ticker symbol**. For example, enter `AAPL`, `MSFT`, or `BRK-B`. The example chips fill the field; you still need to click **Generate research report** (or press Enter).
4. The status panel shows the collection, analysis and PDF stages. Leave the page open. Time varies with external providers and their rate limits; a report is not a streaming live quote.
5. When the report is ready, review the conclusion, 1-, 3- and 6-month ranges, the clearly labeled subset hit rate, closing-price date and factor coverage. Expand **Data notes & limitations** to see missing sources and cautions.
6. Click **Open research report** to view the PDF in a new tab, or the download icon to save it. In the PDF, read the investment decision first, then the revenue/issuer-evidence and financial-trajectory pages in sections 3 and 6, independent leads in section 10, bull and bear cases, and the clickable source list in section 23. Verify search leads and filing excerpts in their original context. Use **Research another ticker** to start over.
7. For web jobs, a copy is also saved as `reports/<job-id>.pdf` in the project directory. Your browser download uses a descriptive ticker/date filename. `reports/` is intentionally ignored by Git. Set `STOCK_CRAWLER_REPORT_DIR` before startup to change the server's output directory.

Each report is a point-in-time snapshot. Run it again after earnings, major news or meaningful macro changes. Jobs and their PDF links are stored in `reports/report-jobs.sqlite3` and `reports/` for seven days by default. When the browser supports session storage, a refresh in the same tab restores the latest report or progress. Recent unfinished jobs are retried from the beginning after a server restart, so their source data may differ from the interrupted attempt. Links and retries survive a restart **only if the report directory itself survives**; Render's Free plan clears it. The local default runs up to two reports at once and accepts up to 12 queued or running jobs.

### Which ticker should I enter?

Use the symbol **as Yahoo Finance spells it**, including exchange suffixes where required:

| Instrument | Example | What to expect |
| --- | --- | --- |
| US stock | `AAPL`, `MSFT`, `BRK-B` | Company research when the source has sufficient data. |
| International stock | `VOD.L`, `7203.T` | Coverage and reporting currency vary. US macro is only a partial proxy for local conditions. |
| Fund | `SPY` | A report can include price and available holdings, but the single-company verdict and ranges are withheld. |
| Index / cryptocurrency / currency pair | `^GSPC`, `BTC-USD`, `EURUSD=X` | The provider may return price history, but company-specific fundamentals, verdict and ranges are generally not applicable. |

Yahoo Finance does not cover every security or exchange, and an otherwise valid symbol may temporarily be unavailable or rate-limited. This tool cannot guarantee data for literally every ticker. Search Yahoo Finance for the exact listing if a symbol fails. The last accepted **daily close**—not an intraday quote—is the model anchor; range end dates are one, three and six calendar months later. To avoid treating an in-progress session as a final close, live Yahoo and Stooq bars dated on or after the current UTC date are discarded, including already-finished sessions that day. This conservative cutoff is not a substitute for checking the exchange calendar. The ranges describe prices and exclude future dividends, while momentum and historical hit tests use provider-adjusted closes when available.

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

## Deploy to Render

The checked-in `render.yaml` provides a **free, single-instance web service** with the frontend, API and PDF generator together. It starts with the dependency lockfile, binds to Render's `PORT`, and exposes `/api/health` for readiness. The Blueprint deploys a **public** site by default; don't submit private information, and see the optional password below. It creates no paid database or disk. Render's available plans and terms can change; review them in the dashboard before creating a service.

### 1. Create the service

1. Push the Render changes to GitHub and sign in to [Render](https://render.com/). Deploy a branch containing `render.yaml`; merge the pull request first if you want to deploy `main`.
2. In the Render dashboard, choose **New → Blueprint**, connect the GitHub repository, and select that branch. Render reads the root `render.yaml`. Confirm the `stock-crawler` web service and **Free** plan, then create the Blueprint.
3. Watch the first build and deploy in Render. When it is live, open the `onrender.com` URL and click **Explore a sample** to confirm the fictional report works. Then try a real ticker and inspect **Data notes & limitations**; external providers may block or rate-limit cloud-server IPs.
4. Optional: in the service's **Environment** settings add `SEC_USER_AGENT` with your real name or organization and contact email to enable eligible SEC filing excerpts. Without it, filing lookup is skipped. Never put a real secret or personal contact into a committed file.
5. Subsequent pushes to the configured branch can trigger automatic redeploys. Remember that the default Free service loses local data at redeploy, restart and idle spin-down.

For manual service creation instead of a Blueprint, use **Python 3**, build command `uv sync --locked`, start command `uv run --locked uvicorn stock_crawler.app:app --host 0.0.0.0 --port $PORT --workers 1`, health check path `/api/health`, and environment variables `PYTHON_VERSION=3.12.12`, `UV_VERSION=0.13.6`, `WEB_CONCURRENCY=1`, `STOCK_CRAWLER_REPORT_WORKERS=1`. Render provides `uv` when the root `uv.lock` is present. Use exactly **one web instance and one web process**: the SQLite-backed queue is designed for a single process, not distributed workers.

### 2. Understand storage and free-tier limits

- **Free Render:** The filesystem is ephemeral. Reports, job statuses and the prospective full-scorecard archive disappear on restart, redeploy or spin-down; a resumed browser may need to start a new report. Free web services normally spin down after 15 minutes idle and may take time to wake. Download any PDF you want to keep immediately. The full-scorecard archive needs persistent storage to accumulate meaningful history.
- **Optional paid disk:** Upgrade the web service to a plan that supports a persistent disk, attach one at `/var/data`, and set `STOCK_CRAWLER_REPORT_DIR=/var/data/reports` in the service environment. The app creates the directory and stores `report-jobs.sqlite3`, PDFs, and `scorecard-history.sqlite3` inside it. If you override `STOCK_CRAWLER_HISTORY_DB`, that path must also be under the disk mount. Persistent disks add cost, are limited to one service instance, and disable zero-downtime deploys. Back up important data; a disk is not a backup.
- With persistent storage, **completed** job status and PDF links survive a restart for the configured retention period. **Queued or running** jobs are retried from scratch after startup; they may fetch different live data. If storage disappears, recovery is impossible. Expired job records and PDFs are removed on a later lookup, submission or restart; the separate scorecard archive is not removed by job cleanup.
- This remains a small **single-instance** app. It is not a highly available, horizontally scalable job system. Multiple Uvicorn workers or instances would compete to restart and process the same jobs. A larger deployment needs a shared durable queue, database and object storage.

### 3. Access and generous limits

The Blueprint is open to anyone who knows its URL. The default admission limit is **240 accepted report requests per hour across the entire service**, with up to **12** queued/running jobs and **one** report generated at a time on the Free Blueprint. This is intentionally permissive for light use; it is a global, single-instance safeguard, **not** a per-user limit or DDoS protection. Progress polling, PDF downloads and health checks are not counted. A full queue or exhausted hourly limit returns HTTP 429 with `Retry-After`; invalid or rejected submissions don't count. Once accepted, a job counts even if its research later fails.

Add these environment variables in Render's **Environment** settings and choose **Save and deploy** to override the defaults. The exception is `STOCK_CRAWLER_REPORT_WORKERS`, which is explicitly managed by the Blueprint: change its value in `render.yaml` and push, or remove its entry from the Blueprint before setting it in the dashboard. Blueprint sync can overwrite values it declares, but preserves environment variables omitted from the file.

| Variable | Default | Purpose |
| --- | --- | --- |
| `STOCK_CRAWLER_REPORTS_PER_HOUR` | `240` | Accepted reports in a rolling hour across the service; `0` disables the cap. |
| `STOCK_CRAWLER_MAX_ACTIVE_REPORTS` | `12` | Maximum queued plus running jobs. |
| `STOCK_CRAWLER_REPORT_WORKERS` | `1` in the Blueprint; `2` locally | Concurrent report-generation threads, **not** Uvicorn processes. |
| `STOCK_CRAWLER_JOB_RETENTION_HOURS` | `168` | Retain finished job status and PDF for seven days; minimum one hour. |

For a private/shared installation, set `STOCK_CRAWLER_AUTH_PASSWORD` to a long, random password in Render's environment settings; optionally set `STOCK_CRAWLER_AUTH_USER` (default `researcher`). The browser prompts for that shared login and protects the website, API, documents and static files; `/api/health` remains public for Render. Set the values only in Render, not Git. Basic authentication must be used over HTTPS, as provided by Render. Remove the password variable to make the service public again. This is a **single shared password**, not individual user accounts, authorization or a complete security system; avoid sensitive data and add stronger access controls for a broader production deployment.

**For an existing Render service:** merge the research update into the branch Render deploys (or choose **Manual Deploy → Deploy latest commit** after updating that branch). In the service's **Environment** page, add `SEC_USER_AGENT` with your real name/organization and contact email, and optionally add `BRAVE_SEARCH_API_KEY` as a secret. Choose **Save and deploy** so the new values take effect. The Blueprint does not declare these optional variables, so dashboard values are preserved on sync. To avoid unexpected Brave charges on a public site, enable the shared password or stricter job limits first; see above. Generate a **new** real-ticker PDF and inspect section 23/data notes—old reports will not be enriched. On Free, redeployment deletes local reports and scorecard history, so download anything you need beforehand.

Providers receive requested tickers and may impose rate limits, restrictions or licensing terms; verify that your intended public use is permitted. The app's limits cannot guarantee provider availability. Confirm a real ticker from the deployed instance—the fictional sample and mocked tests do not prove Yahoo, Stooq, FRED, SEC, GDELT, Wikidata or Brave access from Render.

## Sources, freshness and coverage

Live research requires outbound access to the following public providers. The offline demo requires none of them.

| Source | Used for | Caveats |
| --- | --- | --- |
| [Yahoo Finance](https://finance.yahoo.com/) via the unofficial `yfinance` library | Profile, officers, financial metrics, annual income/cash-flow/balance-sheet history and quarterly income statements, industry peers, analyst snapshots, fund holdings, up to 10 years of daily prices, SPY, positioning, options and up to 20 linked headlines | Coverage, periods and freshness vary. Values may be delayed, revised, incomplete or rate-limited; provider terms and availability apply. Price history falls back to one year if 10 years cannot be fetched. Headline relevance and claims are not independently verified. |
| [Stooq](https://stooq.com/) unofficial daily CSV | Limited price-history fallback if Yahoo history fails, only for simple 1–5-letter uppercase US-style symbols | Best effort only; verify symbol identity, listing and currency. No profile, fundamentals or separately verified adjusted closes are supplied. As a result, adjusted-price momentum, volatility ranges and adjusted-return backtests are withheld. Non-USD Yahoo profile matches and incompatible known instrument types are rejected. |
| [FRED](https://fred.stlouisfed.org/) public CSV series | 10-year Treasury yield (`DGS10`), fed funds (`DFF`), CPI (`CPIAUCSL`), unemployment (`UNRATE`), WTI oil (`DCOILWTICO`), dollar index (`DTWEXBGS`), real GDP (`GDPC1`), 10-year minus 2-year yield spread (`T10Y2Y`), high-yield credit spread (`BAMLH0A0HYM2`) and VIX (`VIXCLS`) | Each series has its own observation date and publication lag. CPI and real GDP are year-over-year growth versus the same calendar month/quarter a year earlier. Changes compare against the nearest observation at or before three calendar months earlier. These US indicators are not a complete local/global picture. |
| [unitedstates/congress-legislators](https://github.com/unitedstates/congress-legislators) public CC0 dataset, retrieved via GitHub's API | US president and vice president, congressional leadership, recognized US headquarters-state senators and historical presidential terms | Community-maintained, not an official live feed. Recorded dates and party labels can lag vacancies or changes. Data are cached in process for six hours; the PDF shows the oldest included dataset's actual fetch time. GitHub access, rate limits and retrieval errors can leave this section incomplete. Verify current officeholders with official sources. |
| [USA.gov election calendar](https://www.usa.gov/presidential-election-process) and [midterm guide](https://www.usa.gov/midterm-elections) | Standard US federal general-election dates | Scheduled dates are not predictions of candidates or results; primaries and special elections are outside this calculation. |
| [VADER](https://github.com/cjhutto/vaderSentiment) | English-language headline-tone scoring | A general-language dictionary model with a small explicit finance-word override; it can misread financial context, sarcasm and headlines whose language is unknown. |
| [SEC EDGAR](https://www.sec.gov/edgar), optional | Latest listed 10-K / 20-F / 40-F, newer 10-Q, up to six recent 8-K item lists, issuer excerpts, US-GAAP CompanyFacts and qualifying inline-XBRL revenue mix | Requires a real `SEC_USER_AGENT`, exact ticker/CIK match and SEC access. Facts and categories vary by issuer; IFRS/custom concepts and unusual filings may not be parsed. Only the first 10 MB of each filing is searched if larger; excerpts may omit context. Inline-XBRL mix components must numerically reconcile within 0.3% of a consolidated annual total, but this does not prove they are non-overlapping. Verify the original filing's tables and definitions. |
| [The GDELT Project](https://www.gdeltproject.org/) DOC 2.0 API | Recent independently sourced news leads in section 10 | No key. English-language search, up to 18 relevance/date-filtered results retained and a few displayed. GDELT's first-seen time may differ from publication; indexing and coverage are incomplete. Requests are spaced at least five seconds per process; shared IPs and other processes can still be rate-limited. Titles are unverified leads, not inputs to the Yahoo headline-tone factor. Article content belongs to publishers. |
| [Wikidata](https://www.wikidata.org/) | Additional product and subsidiary leads for an issuer matched by both name and ticker | No key. Community-maintained records can be incomplete, stale or lack end dates. Ended and deprecated claims are filtered when marked, but a listed product or subsidiary is not proof of current ownership, importance or revenue. Verify in current filings. |
| [Brave Search API](https://brave.com/search/api/), optional | Two indexed-web searches for customer/product and competition/risk leads; a few linked snippets in section 10 | Requires `BRAVE_SEARCH_API_KEY`; usage may incur charges. Results can be stale, incomplete, irrelevant or wrong. The app does not crawl their pages or independently validate snippets, and they do not enter the scorecard. |

The PDF uses source markers `[Q]` (profile/statistics), `[H]` (Yahoo or Stooq price history), `[R]` (industry/peer comparisons), `[A]` (analysts), `[S]` (Yahoo annual and quarterly statements), `[F]` (annual SEC filing), `[FQ]` (newer SEC 10-Q), `[X]` (SEC structured facts), `[G]` (The GDELT Project's news leads), `[W]` (Brave leads), `[K]` (Wikidata), `[M1]`–`[M10]` (FRED), `[N]` (Yahoo headlines), `[O]` (options), `[B]` (SPY), `[P]` (political dataset), `[E]` (election calendar) and `[V]` (VADER). The fictional sample uses `[D]` instead. The final section lists clickable source links and dates. Providers receive requested tickers or data requests; if enabled, the SEC also receives your configured User-Agent.

### How the deeper financial research works

The report prefers SEC entity-wide US-GAAP facts when they are at least as recent as Yahoo's corresponding annual or quarterly history; otherwise it uses Yahoo's history. It does not merge individual financial fields between those sources. SEC annual periods must span 330–400 days and quarterly periods 65–110 days; year-to-date totals are not treated as standalone quarters. When comparable periods, revenue concepts and currencies match, it shows year-over-year revenue growth alongside operating-margin movement. It also compares annual operating cash flow with positive net income, highlights stock-based compensation and the change in diluted weighted-average shares, and compares provider growth/margins with medians of at least three peers where available. Restatements, period definitions, noncash items and accounting differences still require investigation.

Revenue mix uses the issuer's inline-XBRL members only when a unique, bounded set of values numerically reconciles to the consolidated annual revenue figure. Year-over-year business-line changes appear only when the prior year independently reconciles with the same members, currency, concept and comparable duration. The largest absolute change is highlighted alongside total revenue growth; neither is a profit or causal explanation. Reconciliation is not a guarantee that every category is disjoint or that a tag-derived label matches the official table. Extracted filing sentences may be partial or out of context. Read the original linked disclosure, check the date and reporting currency, and never assume a named business line is a named customer or that correlation proves a cause. Search results and Wikidata are leads to verify, not audited company facts. **These added insights do not change the scorecard, ranges, backtest or archived model revision.**

### How to read the political and election analysis

- The official list is a **dated snapshot**, not an assertion that a politician supports, owns or directly affects the company. A headquarters-state senator is shown because of the provider-reported headquarters location; operations and customers may be elsewhere. For foreign or unrecognized headquarters, no state senator is inferred. Presidential election winners are identified only when the source records an election-based January presidential term that has already started; missing or not-yet-established outcomes are labeled as such.
- Federal general elections are calculated as the Tuesday after the first Monday in November in even-numbered years; presidential elections occur every four years and other even years are midterms. The report names the next scheduled general election and adds it to the monitoring checklist if it falls within the six-month horizon.
- For each available historical election, the anchor is the **last adjusted close before election day** (no more than seven calendar days earlier). The table shows returns after 10, 63 and 126 subsequent observed trading sessions where data exist. For USD-denominated equities and ETFs, the 63-session SPY comparison is shown **only if the same anchor and end dates exist** in both histories. Adjusted prices account for provider-reported splits/distributions; provider corrections, currencies and international trading calendars can affect comparability. A recent listing or missing adjusted prices can leave no usable windows.
- These windows overlap with earnings, recessions, wars, interest-rate changes and other events. They do **not** identify the causal effect of an election, politician, party or policy, and are not a political coefficient in the scorecard. Sector policy channels are conditional possibilities to verify against the company's actual filings, contracts and geographic exposures—not predictions that a proposal will pass.

### How sentiment and positioning are measured

The app scores at most 20 provider-linked headlines. To enter the 30-day sample, a headline must have a parseable date in the past 30 calendar days, not be a duplicate, not be explicitly tagged as non-English, and match the ticker/company name or a provider-supplied related ticker. This heuristic can miss relevant stories or include unrelated ones; unknown-language text can still be misread. All eligible headlines used are listed in section 10 with individual tone and links. VADER compound scores of `≥0.05` are positive, `≤-0.05` negative and between them neutral. A mean and the 8%-weight factor require **at least five** eligible headlines. A time comparison requires **at least three** in each window: days 0–7 and days 8–30. Samples can differ across windows, so a difference is not proof that all investors' sentiment changed.

The finance lexicon overrides are: `beat/beats` +1.4, `upgrade/upgrades` +1.6, `downgrade/downgrades` -1.6, `miss/misses` -1.2, `bankruptcy` -2.5, `layoffs` -1.7, `surge` +1.2 and `plunge` -1.7. This is not FinBERT, social-media sentiment, article verification or comprehensive news coverage. No article text or paid sentiment feed is analyzed.

Positioning is descriptive rather than an additional model factor: the latest 20 trading sessions' average volume is compared with the previous 60, adjusted prices are compared with 50- and 200-session averages, and 63 daily log returns are annualized for realized volatility. The report shows provider-reported short interest and institutional ownership when available. For options, it selects the available expiration **7–90 days away closest to 45 days**, and reports known put and call open interest. The put/call ratio is withheld unless both sides have complete valid open-interest data and call open interest is positive. Open interest can reflect hedges or spreads; volume is not buy/sell flow and neither identifies trader intent. These figures can be stale or incomplete.

## How the conclusion and price ranges are calculated

This is a deterministic rule-based model, **not** an LLM and **not** a measured consensus of all investors. The separately displayed provider analyst recommendation is an outside analyst average; it is not the Stock Crawler verdict. The complete scorecard and current inputs appear in each report.

### 1. Score the available evidence

Each signal lies between **-1 and +1**. Missing data are excluded, not treated as zero. The overall score is `sum(weight × available signal) / sum(available weights)`, and coverage is the sum of the available weights.

| Factor | Weight | Rule |
| --- | ---: | --- |
| Provider revenue growth | 17% | `≥15%, ≥5%, ≥-5%, ≥-15%, otherwise` map to `+1, +0.5, 0, -0.5, -1`. |
| Operating margin | 14% | `≥20%, ≥10%, ≥0%, ≥-10%, otherwise` map to the same five scores. |
| Balance sheet | 10% | Apply `≥10%, ≥0%, ≥-30%, ≥-75%, otherwise` to **negative** `(debt - cash) / market capitalization`. Excluded for financial institutions or when required values or matching currency units are absent. |
| Forward P/E | 10% | Divide the issuer's positive forward P/E by the median positive forward P/E of at least three verified same-industry peers. A ratio `≤0.75, ≤1, ≤1.25, ≤1.75, otherwise` maps to `+1, +0.5, 0, -0.5, -1`. Real estate is excluded. |
| Six-month price trend | 12% | Adjusted-close return `≥20%, ≥5%, ≥-5%, ≥-20%, otherwise` maps to `+1, +0.5, 0, -0.5, -1`. Past performance is not a forecast. |
| Analyst sentiment | 9% | With at least three opinions, score `3 - recommendation mean` at thresholds `≥1, ≥0.5, ≥-0.5, ≥-1, otherwise`. Provider scale: 1 = strong buy, 5 = sell. |
| Headline tone | 8% | With at least five eligible recent headlines, `mean VADER compound × 2`, capped to `-1…+1`; see the sampling and language caveats above. |
| Macro overlay | 20% | Directional sector assumptions applied to recent changes in yields, unemployment and CPI; oil also enters for selected upstream-energy or airline industries. Details below. |

**Peer selection:** Yahoo's industry listing supplies up to eight candidates, excluding the issuer. Each candidate must be an equity, match the issuer's industry name or industry key, and have a positive provider forward P/E. Duplicates are removed; a median requires at least three eligible peers. The PDF lists the members, multiples and retrieval date. If the industry list, peer statistics or issuer P/E are missing, valuation is unscored; there is no fixed-sector fallback. This small, changing, provider-selected sample is not a comprehensive peer universe or a fair-value estimate, and forecast-earnings definitions, growth, leverage, accounting and provider errors can make comparisons misleading. Real estate is excluded because P/E can be particularly unsuitable.

**Macro calculation:** For each relevant series, divide its roughly three-month change by a normalizing move: 0.5 percentage points for the 10-year yield, 0.4 points for unemployment, 0.8 points for CPI year-over-year inflation, or 20% for oil. Cap each normalized move at `-1…+1`. Multiply it by the assumed signed sector sensitivity and divide the sum by the sum of the absolute included sensitivities. At least two relevant series no more than 90 days old are required. A higher yield/unemployment/inflation generally receives a negative assumed sensitivity; for financial services the rate sensitivity is zero because its effect is ambiguous. Oil is `+1` for selected upstream energy industries and `-1` for airlines. The report shows the sector's actual sensitivities. These are **subjective transmission assumptions, not estimated stock correlations**; fed funds, the dollar, GDP growth, the yield curve, credit spread and VIX are shown as context but do not enter the score.

A **verdict is withheld** unless all of the following are true:

- The instrument is an equity, and its last close is at most 14 calendar days old.
- At least **65%** of the total factor weight is available.
- At least **two** of revenue growth, profitability, balance sheet and valuation are available.
- The macro overlay has at least two recent, relevant inputs.

When these checks pass: score `≥ +0.20` is **bullish**; `≤ -0.20` is **bearish**; values in between are **mixed/neutral**. Otherwise the conclusion is **insufficient evidence**. Coverage measures input availability, not statistical confidence.

### 2. Translate the score into price ranges

The 1-, 3- and 6-month ranges also require all verdict gates to pass and at least 64 consecutive usable, positive adjusted closes, with no gap longer than 10 calendar days. From the latest 63 daily **adjusted-close log returns**, compute sample standard deviation × `sqrt(252)` as annualized realized volatility `σ`. Zero, non-finite or implausibly high volatility above 300% is rejected. For each horizon `m` in months:

```text
log drift = 0.16 × score × m / 6
log half-width = σ × sqrt(m / 12)
lower, upper = last unadjusted close × exp(log drift ± log half-width)
```

For a hypothetical $100 close, score `+0.30`, annualized volatility `30%` and six months, the drift is `0.048`, the half-width is about `0.212`, and the price range is approximately **$84.86–$129.71**. The same score and volatility produce shorter-horizon ranges by the formula above; they are not separately calibrated predictions. Macro affects the ranges through its 20% scorecard weight when the gates pass.

These are **judgmental, uncalibrated price scenarios**, not confidence intervals, assigned probabilities or guarantees. One realized-volatility shock may understate jumps, shifts in volatility, liquidity and event risk. The score-to-drift multiplier and square-root-of-time scaling are assumptions. Bounds can be exceeded, and future dividends, taxes and trading costs are excluded. Financial-statement and quote currencies are kept distinct: ratios combining them are withheld if units differ, are unknown, or the quote uses an ambiguous minor unit such as `GBp`. No FX conversion, discounted cash-flow valuation, earnings-date prediction, portfolio sizing or personalized risk assessment is performed.

## Historical hit rate: what is and is not tested

The PDF and web result publish the ticker's **retrospective scorecard-subset** hit rate when enough adjusted history exists. [A fully reproducible real AAPL momentum-only example](docs/backtest-example.md) found **43/76 (56.6%)** correct at 1 month, **18/31 (58.1%)** at 3 months and **9/15 (60.0%)** at 6 months; an always-up baseline did better on the same dates. This is one selected stock, not an overall model success rate.

For each horizon, the retrospective test reconstructs six-month adjusted-price momentum and, when at least 12 historical origins have sufficient macro inputs, the macro factor using their live weights and thresholds; otherwise it tests momentum only. It uses completed month-end origins within the last ten years, non-overlapping calendar-month outcome windows, and the first available close on or after the end date (within ten days). Scores `≥+0.20` predict up and `≤−0.20` predict down; neutral scores and exactly flat outcomes are excluded from the hit-rate denominator. The table reports correct calls / directional calls, bullish/bearish counts, the same-date always-up baseline, and coverage of **adjusted total returns** against bounds calculated with the **partial score**, not coverage of today's price-only full-score ranges. The latter comparison can differ because adjusted returns include provider-reported distributions and splits. Coverage includes eligible neutral origins, so its denominator can differ. Costs, delistings, portfolio effects and transaction execution are not modeled.

Historical fundamentals, peer medians, analyst opinions, news and the full live quality gates are **not reconstructed**; today's values are never inserted into old dates. FRED's downloaded history is the current **revised vintage**, not ALFRED point-in-time vintages. The test assumes one-calendar-day publication delays for daily series and 60 days for monthly CPI/unemployment, but real release schedules can differ and later revisions can still introduce hindsight. The current sector/industry classification is also applied historically. Therefore this is neither a vintage-correct test nor validation of the complete scorecard, the ranges' probabilities or future performance.

### Separate prospective full-scorecard archive

A successful **live** report with a sufficient-data verdict saves its score, factor scores/weights, coverage, model revision, quote date and UTC timestamp in `reports/scorecard-history.sqlite3` (or the configured report directory). The first report per ticker, model revision and UTC day is retained; demo and insufficient-evidence reports are never recorded. Subsequent reports load the same local archive. Once a directional verdict has matured, section 17 reports its separate hit rate and always-up baseline using the **first available adjusted close strictly after the report's UTC date** and the first close on or after each horizon. Windows are non-overlapping; mixed/neutral calls and flat outcomes are excluded. Only the current model revision is compared. Maintainers must increment `MODEL_REVISION` in `stock_crawler/archive.py` when changing scorecard rules so incompatible results are not mixed.

This archive starts when you run the application; it cannot manufacture earlier full-scorecard predictions. It is local and user-selected, so results can be sparse and biased, and should not be generalized. Back up the SQLite file if you want to retain this history; deleting it resets the prospective record. Set `STOCK_CRAWLER_HISTORY_DB` to use a different path. Storage errors are reported as warnings rather than blocking the PDF. The archive contains ticker, timestamps and scorecard outputs, not your SEC contact string; secure or delete it as you would other local research files.

### Run the retrospective test on your own CSV

Provide a daily UTF-8 CSV with `Date`, `Close` and **explicit** `Adj Close` columns; an optional `Volume` is accepted. Adjusted closes are not inferred from raw prices. Use data you have the right to access:

```bash
python -m stock_crawler backtest AAPL --prices path/to/aapl.csv --sector Technology
```

With no macro files this is a momentum-only subset. To include the macro subset, supply a current provider sector and a directory containing FRED-style `DGS10.csv`, `UNRATE.csv`, `CPIAUCSL.csv` and optionally `DCOILWTICO.csv` (headers `observation_date,<series code>` or `DATE,<series code>`):

```bash
python -m stock_crawler backtest AAPL --prices path/to/aapl.csv --sector Technology --macro-dir path/to/fred-csvs
```

For example, download a series from `https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10`, save it as `DGS10.csv`, and repeat with the other series codes. FRED release/vintage and sector-hindsight caveats still apply. If historical macro coverage is inadequate the command explicitly falls back to momentum-only; it never fills past fundamentals with today's snapshot.

## Troubleshooting

- **No usable price history / ticker not found:** Check the Yahoo Finance symbol and exchange suffix. Confirm that your machine can reach Yahoo Finance, then retry later; the unofficial source may rate-limit requests. Some valid securities simply are not covered.
- **“Insufficient evidence” or no ranges:** Open **Data notes & limitations** and the scorecard. Missing/stale macro, fewer than two fundamentals, less than 65% coverage, an old close or a non-equity instrument prevents a verdict. Missing adjusted closes or usable volatility also prevents ranges, even when the verdict is available. Missing data are not replaced with guesses.
- **No customer names, SEC excerpts or revenue mix:** Set `SEC_USER_AGENT` before starting the server (or in Render's environment and redeploy), use a matching SEC registrant symbol, and check network access to EDGAR. Many issuers do not disclose named customers; XBRL mixes are withheld when contexts, currency, periods or reconciliation are ambiguous. Some filings use IFRS or custom tags the extractor cannot handle. Read the original filing.
- **No independent news, Wikidata profile or web leads:** Check network access and the report's data notes. Independent providers can block or rate-limit requests; issuer matching and bounded search may return nothing. For Brave, confirm the optional `BRAVE_SEARCH_API_KEY`, account access, budget and current API plan, then restart/redeploy. GDELT and Wikidata do not require a key. No provider indexes the entire internet.
- **No macro values:** Check access to `fred.stlouisfed.org`; corporate networks and firewalls can block it. The app shows the gap and withholds the verdict and ranges if it cannot build a usable macro overlay.
- **No officials or election winners:** Check access to `api.github.com` and GitHub rate limits. The community dataset may be unavailable, stale or missing a record; the report does not guess names or future outcomes. Historical price windows can still be shown when available.
- **No election windows or SPY comparison:** The ticker may be recently listed, lack adjusted prices or have a different calendar; SPY comparisons require an eligible USD-denominated instrument and exact matching dates.
- **No headline score or trend:** Fewer than five eligible, dated, issuer-matched headlines in the last 30 days leaves the factor unscored; a trend needs three in each time bucket. Check the listed headlines rather than treating missing news as neutral.
- **No options ratio:** No suitable expiration, a missing contract field, an incomplete chain or zero call open interest prevents a reliable ratio.
- **Wrong currency or unfamiliar units:** Check the quote and reporting currency in the source. International listings can use a minor unit such as `GBp`. The app does not apply an implicit FX conversion.
- **Page says queue full or hourly limit reached:** Wait and retry. The generous limit and queue size are configurable as described in the Render section; status polls and downloads don't use report slots.
- **Port already in use:** Start with `--port 8080` and visit `http://127.0.0.1:8080` instead.
- **An old PDF doesn't update:** Reports are snapshots. Generate a new one to fetch the latest available data.

## Development and tests

```bash
uv sync --locked --extra dev --inexact
python -m pytest -q
python -m stock_crawler report --demo --output reports/sample.pdf
```

The test suite uses synthetic fixtures and mocked providers, so it does not need live market access. The app exposes an interactive API reference at `/docs` while the server is running. The main endpoints are `POST /api/reports` (`{"ticker":"AAPL","demo":false}`), `GET /api/reports/{id}` for progress and `GET /api/reports/{id}/pdf` for the completed document. The server is a single-process tool, not a horizontally scalable or fully isolated multi-user deployment.

The project is licensed under the [MIT License](LICENSE). The UI bundles DM Sans and DM Serif Display separately under the SIL Open Font License; their license files are in `stock_crawler/static/fonts/`.
