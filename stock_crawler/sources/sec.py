"""Issuer filings and structured facts from SEC EDGAR.

A real identifying contact is required by the SEC. All retrievals are bounded,
sequentially paced per process, and best effort; missing primary sources are
reported, never filled with assumed facts.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import replace
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from html.parser import HTMLParser
from typing import Any

import requests

from stock_crawler.models import Filing, FilingEvent
from stock_crawler.sources.sec_facts import parse_companyfacts
from stock_crawler.sources.xbrl import extract_revenue_breakdowns
from stock_crawler.utils import text

MAX_FILING_BYTES = 10_000_000
MAX_JSON_BYTES = 20_000_000
_SEC_LOCK = threading.Lock()
_LAST_REQUEST = 0.0


def _valid_agent(agent: str) -> bool:
    # SEC asks for a declared organization/name and a contact email address.
    return bool(re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", agent) and len(agent.split()) >= 2)


def _get(url: str, agent: str, *, timeout: int = 20):
    global _LAST_REQUEST
    # Keep this process well below the SEC's published aggregate limit. The
    # deployment is single-process; other apps sharing an IP must also comply.
    with _SEC_LOCK:
        wait = 0.15 - (time.monotonic() - _LAST_REQUEST)
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST = time.monotonic()
    return requests.get(url, headers={"User-Agent": agent, "Accept-Encoding": "gzip, deflate"},
                        timeout=(5, timeout), stream=True)


def _read_bounded(response, limit: int) -> tuple[bytes, bool]:
    chunks, size, truncated = [], 0, False
    try:
        response.raise_for_status()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            remaining = limit - size
            if len(chunk) > remaining:
                chunks.append(chunk[:remaining])
                truncated = True
                break
            chunks.append(chunk)
            size += len(chunk)
    finally:
        response.close()
    return b"".join(chunks), truncated


def _get_json(url: str, agent: str) -> Any:
    raw, truncated = _read_bounded(_get(url, agent), MAX_JSON_BYTES)
    if truncated:
        raise ValueError("SEC JSON exceeds the safety limit")
    return json.loads(raw)


class _VisibleText(HTMLParser):
    """Avoid building a huge DOM and exclude scripts and the hidden XBRL header."""
    IGNORE = {"script", "style", "noscript", "svg", "ix:header"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.IGNORE:
            self.ignored.append(tag.lower())

    def handle_endtag(self, tag):
        if self.ignored and self.ignored[-1] == tag.lower():
            self.ignored.pop()

    def handle_data(self, data):
        if not self.ignored and data.strip():
            self.parts.append(data)


def _filing_text(content: bytes) -> str:
    parser = _VisibleText()
    parser.feed(content.decode("utf-8", errors="replace"))
    parser.close()
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def _extract_disclosures(content: bytes):
    full = _filing_text(content)

    def find(pattern: str, secondary: str, limit: int) -> tuple[str, ...]:
        candidates: list[tuple[int, str]] = []
        for match in re.finditer(pattern, full, re.I):
            window_start = max(0, match.start() - 420)
            end = min(len(full), match.end() + 320)
            window = full[window_start:end]
            if not re.search(secondary, window, re.I):
                continue
            # Dots in common abbreviations are not sentence boundaries.
            boundaries = [item for item in re.finditer(r"\.\s+", window)
                          if not re.search(r"\b(?:U\.S|U\.K|e\.g|i\.e)$", window[:item.start()], re.I)]
            preceding = [item for item in boundaries if item.end() <= match.start() - window_start]
            following = [item for item in boundaries if item.start() >= match.end() - window_start]
            start = window_start + preceding[-1].end() if preceding else window_start
            if following:
                end = window_start + following[0].start() + 1
            partial_start = not preceding and window_start > 0
            # Avoid including fragments of financial tables before a narrative
            # sentence. This preserves words verbatim but may begin mid-sentence.
            prefix = full[start:match.start()]
            if len(re.findall(r"\d", prefix)) > 6:
                clean = re.search(r"[A-Za-z][A-Za-z\s&,'’\-]{3,75}$", prefix)
                start = match.start() - len(clean.group()) if clean else match.start()
            if start > 0 and full[start - 1].isalnum() and full[start].isalnum():
                next_space = full.find(" ", start, match.start())
                start = next_space + 1 if next_space >= 0 else match.start()
            excerpt = text(full[start:end], 420)
            if len(re.findall(r"\d", excerpt[:120])) > 12:
                narrative = re.search(r"[A-Za-z][A-Za-z\s&,'’\-]{0,60}(?:net sales|revenue|gross margin)\s+(?:increased|decreased|grew|declined)", excerpt, re.I)
                if narrative:
                    excerpt = excerpt[narrative.start():]
            duplicate_heading = re.match(r"^(.{3,75}?)\s+\1\s+", excerpt, re.I)
            if duplicate_heading:
                excerpt = excerpt[len(duplicate_heading.group(1)) + 1:]
            if partial_start and not excerpt.startswith("…"):
                excerpt = "…" + excerpt
            if len(excerpt) < 55 or len(excerpt.split()) < 9 or not re.search(secondary, excerpt, re.I):
                continue
            if re.search(r"forward-looking statements|under the heading [“\"]?Risk Factors|"
                         r"assumes no obligation to revise|table of contents", excerpt, re.I):
                continue
            rank = 2 if re.search(r"\b\d{1,3}(?:\.\d+)?\s*(?:%|percent)", excerpt, re.I) else 0
            if re.search(r"accounted for|concentrat|net (?:sales|revenue)", excerpt, re.I):
                rank += 1
            if re.search(r"due primarily to|primarily attributable|driven by", excerpt, re.I):
                rank += 3
            if re.search(r"supply chain|competitive|competition|cybersecurity|depend", excerpt, re.I):
                rank += 1
            candidates.append((rank, excerpt))
            if len(candidates) >= 500:
                break
        candidates.sort(key=lambda item: item[0], reverse=True)
        unique: list[str] = []
        for _rank, excerpt in candidates:
            if any(SequenceMatcher(None, excerpt.casefold(), prior.casefold()).ratio() > 0.72
                   or excerpt.casefold() in prior.casefold() or prior.casefold() in excerpt.casefold()
                   for prior in unique):
                continue
            unique.append(excerpt)
            if len(unique) == limit:
                break
        return tuple(unique)


    customers = find(r"\bcustomers?\b", r"accounted for|represented|concentrat|largest customer|major customers?|10\s*%|ten percent", 3)
    risks = find(r"\b(?:competition|cybersecurity|supply chain|regulat\w*|risk factors?)\b", r"may|could|risk|advers|affect|depend", 3)
    policies = find(r"\b(?:tariffs?|export controls?|government contracts?|reimbursement|federal funding|sanctions|tax credits?)\b",
                    r"revenue|sales|business|cost|demand|operations|risk|could|may|regulat|government", 2)
    operations = find(r"\b(?:backlog|bookings|remaining performance obligations?|subscriptions?|net sales|gross margin|revenue|orders?)\b",
                      r"increase\w*|decrease\w*|grew|growth|declin\w*|percent|million|billion|%", 3)
    return customers, risks, policies, operations


def extract_excerpts(content: bytes) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Backwards-compatible customer, risk and policy snippets."""
    customers, risks, policies, _operations = _extract_disclosures(content)
    return customers, risks, policies


def _filing_metadata(recent: dict, index: int, cik: int) -> FilingEvent | None:
    try:
        form = str(recent["form"][index])
        filed = date.fromisoformat(recent["filingDate"][index])
        raw_date = recent.get("reportDate", [""] * len(recent["form"]))[index]
        report_date = date.fromisoformat(raw_date) if raw_date else None
        accession = str(recent["accessionNumber"][index])
        document = str(recent["primaryDocument"][index])
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) or not re.fullmatch(r"[A-Za-z0-9._-]+", document):
            return None
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{document}"
        raw_items = recent.get("items", [""] * len(recent["form"]))[index]
        items = tuple(code for code in re.findall(r"\b\d\.\d{2}\b", str(raw_items)))
        return FilingEvent(form, filed, report_date, url, tuple(dict.fromkeys(items)))
    except (KeyError, ValueError, IndexError, TypeError):
        return None


def _document(event: FilingEvent, cik: int, agent: str) -> tuple[Filing, list[str]]:
    warnings: list[str] = []
    base = Filing(event.form, event.filing_date, event.report_date, event.url)
    try:
        content, truncated = _read_bounded(_get(event.url, agent, timeout=20), MAX_FILING_BYTES)
        customers, risks, policies, operations = _extract_disclosures(content)
        breakdown = extract_revenue_breakdowns(content, event.report_date, cik) if event.form in {"10-K", "20-F", "40-F"} else ()
        if truncated:
            warnings.append(f"Only the first 10 MB of the SEC {event.form} was searched; review the complete filing for context.")
        return replace(base, customer_excerpts=customers, risk_excerpts=risks, policy_excerpts=policies,
                       operating_excerpts=operations, revenue_breakdowns=breakdown, truncated=truncated), warnings
    except (requests.RequestException, ValueError, TypeError, OSError, RecursionError):
        return base, [f"The SEC {event.form} document could not be retrieved or parsed; its filing link is provided for review."]


def fetch_filing(ticker: str, agent: str) -> tuple[Filing | None, list[str]]:
    if not agent:
        return None, ["SEC filings and company facts were not fetched; set SEC_USER_AGENT to a real name and contact email to enable them."]
    if not _valid_agent(agent):
        return None, ["SEC_USER_AGENT must contain a name/organization and a valid contact email; SEC filing lookup was skipped."]
    try:
        tickers = _get_json("https://www.sec.gov/files/company_tickers.json", agent)
        normalized = ticker.replace(".", "-").upper()
        record = next((v for v in tickers.values() if str(v.get("ticker", "")).replace(".", "-").upper() == normalized), None)
        if not record:
            return None, ["No matching US SEC registrant was found for this symbol; company filing detail may be unavailable."]
        cik = int(record["cik_str"])
        submissions = _get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", agent)
        recent = submissions["filings"]["recent"]
        all_filings = [_filing_metadata(recent, i, cik) for i in range(len(recent.get("form", [])))]
        today = datetime.now(timezone.utc).date()
        all_filings = sorted((item for item in all_filings if item and item.filing_date <= today),
                             key=lambda item: item.filing_date, reverse=True)
        annual = next((item for item in all_filings if item.form in {"10-K", "20-F", "40-F"}), None)
        quarter = next((item for item in all_filings if item.form == "10-Q"), None)
        if not annual and not quarter:
            return None, ["No recent 10-K, 20-F, 40-F or 10-Q was listed in SEC submissions for this symbol."]
        events = tuple(item for item in all_filings if item.form == "8-K" and item.items)[:6]
        primary = annual or quarter
        filing, warnings = _document(primary, cik, agent)
        quarterly_filing = None
        if annual and quarter and (not annual.report_date or not quarter.report_date or quarter.report_date > annual.report_date):
            quarterly_filing, extra = _document(quarter, cik, agent)
            warnings.extend(extra)
        facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
        try:
            facts = _get_json(facts_url, agent)
            annuals, quarters = parse_companyfacts(facts, cik)
            if not annuals and not quarters:
                warnings.append("No comparable entity-wide US-GAAP SEC company facts were available; other financial sources may still be shown.")
        except (requests.RequestException, ValueError, KeyError, TypeError, OSError):
            annuals, quarters = [], []
            warnings.append("SEC structured company facts could not be retrieved or parsed; other financial sources may still be shown.")
        return replace(filing, recent_events=events, latest_quarter=quarterly_filing,
                       sec_annuals=tuple(annuals), sec_quarters=tuple(quarters), companyfacts_url=facts_url), warnings
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, AttributeError, OSError):
        return None, ["The SEC registrant or filing list could not be retrieved or parsed. Review the issuer's investor-relations filings directly."]
