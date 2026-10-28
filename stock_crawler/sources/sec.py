"""Optional SEC EDGAR annual filing excerpts; a real contact User-Agent is required."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

import requests
from bs4 import BeautifulSoup

from stock_crawler.models import Filing
from stock_crawler.utils import text

MAX_FILING_BYTES = 10_000_000


def _valid_agent(agent: str) -> bool:
    # SEC asks for a declared organization/name and a contact email address.
    return bool(re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", agent) and len(agent.split()) >= 2)


def _get_json(url: str, agent: str) -> Any:
    response = requests.get(url, headers={"User-Agent": agent, "Accept-Encoding": "gzip, deflate"}, timeout=(5, 15))
    response.raise_for_status()
    return response.json()


def _filing_text(content: bytes) -> str:
    soup = BeautifulSoup(content, "html.parser")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def extract_excerpts(content: bytes) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return verbatim, bounded snippets, not inferred or invented customers.

    SEC HTML varies considerably. These are explicitly presented as excerpts and
    link to the filing so that the reader can inspect their full context.
    """
    full = _filing_text(content)

    def find(pattern: str, secondary: str, limit: int) -> tuple[str, ...]:
        candidates: list[tuple[int, str]] = []
        seen: set[str] = set()
        for match in re.finditer(pattern, full, re.I):
            window_start = max(0, match.start() - 200)
            start = window_start
            end = min(len(full), match.end() + 240)
            window = full[window_start:end]
            if not re.search(secondary, window, re.I):
                continue
            # Use a sentence boundary if one is nearby; otherwise it is a fragment.
            before = window.rfind(". ", 0, match.start() - window_start)
            after = window.find(". ", match.end() - window_start)
            if before >= 0:
                start = window_start + before + 2
            if after >= 0:
                end = window_start + after + 1
            excerpt = text(full[start:end], 420)
            if len(excerpt) < 55 or len(excerpt.split()) < 9:
                continue
            key = excerpt.lower()[:100]
            if key in seen:
                continue
            seen.add(key)
            rank = 2 if re.search(r"\b\d{1,3}(?:\.\d+)?\s*(?:%|percent)", excerpt, re.I) else 0
            if re.search(r"accounted for|concentrat|net (?:sales|revenue)", excerpt, re.I):
                rank += 1
            candidates.append((rank, excerpt))
            if len(candidates) >= 100:
                break
        candidates.sort(key=lambda item: item[0], reverse=True)
        return tuple(item[1] for item in candidates[:limit])

    customers = find(r"\bcustomers?\b", r"revenue|sales|accounted|concentrat|purchas|products?|services?", 2)
    risks = find(r"\b(?:competition|cybersecurity|supply chain|regulat\w*|risk factors?)\b", r"may|could|risk|advers|affect|depend", 2)
    return customers, risks


def fetch_filing(ticker: str, agent: str) -> tuple[Filing | None, list[str]]:
    if not agent:
        return None, ["SEC filing excerpts were not fetched; set SEC_USER_AGENT to a real name and contact email to enable them."]
    if not _valid_agent(agent):
        return None, ["SEC_USER_AGENT must contain a name/organization and a valid contact email; SEC filing lookup was skipped."]
    try:
        tickers = _get_json("https://www.sec.gov/files/company_tickers.json", agent)
        normalized = ticker.replace(".", "-").upper()
        record = next((v for v in tickers.values() if str(v.get("ticker", "")).replace(".", "-").upper() == normalized), None)
        if not record:
            return None, ["No matching US SEC registrant was found for this symbol; customer and risk disclosures may be unavailable."]
        cik = int(record["cik_str"])
        submissions = _get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", agent)
        recent = submissions["filings"]["recent"]
        selected = next((i for i, form in enumerate(recent.get("form", [])) if form in {"10-K", "20-F", "40-F"}), None)
        if selected is None:
            return None, ["No recent 10-K, 20-F or 40-F was listed in SEC submissions for this symbol."]
        form = recent["form"][selected]
        filing_date = date.fromisoformat(recent["filingDate"][selected])
        report_date_str = recent.get("reportDate", [""] * len(recent["form"]))[selected]
        report_date = date.fromisoformat(report_date_str) if report_date_str else None
        accession = recent["accessionNumber"][selected].replace("-", "")
        document = recent["primaryDocument"][selected]
        # Both accession and document come from the SEC submissions response.
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
        response = requests.get(url, headers={"User-Agent": agent, "Accept-Encoding": "gzip, deflate"}, timeout=(5, 20), stream=True)
        response.raise_for_status()
        chunks: list[bytes] = []
        size = 0
        truncated = False
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            remaining = MAX_FILING_BYTES - size
            if len(chunk) > remaining:
                chunks.append(chunk[:remaining])
                truncated = True
                break
            chunks.append(chunk)
            size += len(chunk)
        response.close()
        customers, risks = extract_excerpts(b"".join(chunks))
        warnings = ["Only the first 10 MB of the SEC filing was searched; review the complete filing for context."] if truncated else []
        return Filing(form, filing_date, report_date, url, customers, risks, truncated), warnings
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, OSError):
        return None, ["The SEC filing could not be retrieved or parsed. Review the issuer's investor-relations filings directly."]
