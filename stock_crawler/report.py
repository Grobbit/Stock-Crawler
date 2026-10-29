"""Generate a structured, sourced research PDF with policy and sentiment context."""
from __future__ import annotations

import html
import os
import re
from pathlib import Path
from urllib.parse import quote

from dateutil.relativedelta import relativedelta
import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from stock_crawler.analysis import EXPOSURES, SECTOR_CHANNELS
from stock_crawler.models import Analysis, Factor, Snapshot
from stock_crawler.sources.fred import SERIES
from stock_crawler.utils import MINOR_UNIT_CURRENCIES, compact, date_from_timestamp, number, pct, price, text

FONT_DIR = os.path.join(reportlab.__path__[0], "fonts")
pdfmetrics.registerFont(TTFont("Crawler", os.path.join(FONT_DIR, "Vera.ttf")))
pdfmetrics.registerFont(TTFont("Crawler-Bold", os.path.join(FONT_DIR, "VeraBd.ttf")))
pdfmetrics.registerFont(TTFont("Crawler-Italic", os.path.join(FONT_DIR, "VeraIt.ttf")))
pdfmetrics.registerFontFamily("Crawler", normal="Crawler", bold="Crawler-Bold", italic="Crawler-Italic", boldItalic="Crawler-Bold")

INK = colors.HexColor("#172b2b")
GREEN = colors.HexColor("#116b56")
MUTED = colors.HexColor("#60726e")
PALE = colors.HexColor("#edf4f0")
PAPER = colors.HexColor("#f6f7f4")
BORDER = colors.HexColor("#dbe4df")
AMBER = colors.HexColor("#a76b19")
RED = colors.HexColor("#a64e45")

STYLES = {
    "kicker": ParagraphStyle("kicker", fontName="Crawler-Bold", fontSize=8, leading=11, textColor=GREEN, spaceAfter=7),
    "title": ParagraphStyle("title", fontName="Crawler-Bold", fontSize=24, leading=29, textColor=INK, spaceAfter=7),
    "cover": ParagraphStyle("cover", fontName="Crawler-Bold", fontSize=28, leading=34, textColor=INK, spaceAfter=8),
    "subtitle": ParagraphStyle("subtitle", fontName="Crawler", fontSize=10, leading=15, textColor=MUTED, spaceAfter=10),
    "body": ParagraphStyle("body", fontName="Crawler", fontSize=9, leading=13.7, textColor=INK, spaceAfter=7),
    "small": ParagraphStyle("small", fontName="Crawler", fontSize=8, leading=12, textColor=INK, spaceAfter=4),
    "muted": ParagraphStyle("muted", fontName="Crawler", fontSize=8, leading=12, textColor=MUTED, spaceAfter=4),
    "section": ParagraphStyle("section", fontName="Crawler-Bold", fontSize=10, leading=14, textColor=INK, spaceBefore=7, spaceAfter=5),
    "cell": ParagraphStyle("cell", fontName="Crawler", fontSize=8, leading=11.4, textColor=INK),
    "cellbold": ParagraphStyle("cellbold", fontName="Crawler-Bold", fontSize=8, leading=11.4, textColor=INK),
    "cellsmall": ParagraphStyle("cellsmall", fontName="Crawler", fontSize=7.5, leading=10.4, textColor=INK),
    "metriclabel": ParagraphStyle("metriclabel", fontName="Crawler-Bold", fontSize=7, leading=10, textColor=MUTED, spaceAfter=4),
    "metric": ParagraphStyle("metric", fontName="Crawler-Bold", fontSize=15, leading=19, textColor=INK),
}


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _p(value: object, style: str = "body") -> Paragraph:
    return Paragraph(_esc(value), STYLES[style])


def _rich(value: str, style: str = "body") -> Paragraph:
    return Paragraph(value, STYLES[style])


def _ref(snapshot: Snapshot, source: str) -> str:
    return "[D]" if snapshot.demo else f"[{source}]"


def _demo_refs(snapshot: Snapshot, value: str) -> str:
    return re.sub(r"\[(?:M\d+|Q|H|A|F|S|N|P|E|B|O|V|R)\]", "[D]", value) if snapshot.demo else value


def _factor_evidence(snapshot: Snapshot, factor: Factor) -> str:
    evidence = _demo_refs(snapshot, factor.evidence)
    if factor.source != "M":
        evidence += " " + _ref(snapshot, factor.source)
    return evidence


def _note(message: str, color: colors.Color = GREEN) -> Table:
    table = Table([[_p(message, "small")]], colWidths=[510])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("LINEBEFORE", (0, 0), (0, -1), 2, color),
        ("LEFTPADDING", (0, 0), (-1, -1), 11), ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def _table(headers: list[str], rows: list[list[object]], widths: list[float], *, small: bool = False) -> Table:
    style = "cellsmall" if small else "cell"
    data = [[_p(value, "cellbold") for value in headers]]
    data += [[_p(value, style) for value in row] for row in rows]
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), PALE),
        ("TEXTCOLOR", (0, 0), (-1, 0), GREEN),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for row in range(1, len(data)):
        commands.append(("LINEBELOW", (0, row), (-1, row), 0.35, BORDER))
    table.setStyle(TableStyle(commands))
    return table


def _metrics(items: list[tuple[str, str]]) -> Table:
    width = 510 / len(items)
    cells = [[_p(label.upper(), "metriclabel"), _p(value, "metric")] for label, value in items]
    table = Table([cells], colWidths=[width] * len(items))
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PAPER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    return table


class PriceChart(Flowable):
    def __init__(self, snapshot: Snapshot, width: float = 510, height: float = 150):
        super().__init__()
        self.snapshot, self.width, self.height = snapshot, width, height

    def draw(self) -> None:
        canvas = self.canv
        cutoff = self.snapshot.price_date - relativedelta(years=1)
        points = [point for point in self.snapshot.prices if point.date >= cutoff]
        if not points:
            return
        left, right, bottom, top = 8, self.width - 8, 24, self.height - 17
        values = [point.close for point in points]
        low, high = min(values), max(values)
        span = max(high - low, abs(high) * 0.01, 0.01)
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        for i in range(3):
            y = bottom + (top - bottom) * i / 2
            canvas.line(left, y, right, y)
        canvas.setStrokeColor(GREEN)
        canvas.setLineWidth(1.6)
        path = canvas.beginPath()
        for i, point in enumerate(points):
            x = left + (right - left) * (i / max(1, len(points) - 1))
            y = bottom + (top - bottom) * (point.close - low) / span
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        canvas.drawPath(path)
        last_y = bottom + (top - bottom) * (points[-1].close - low) / span
        canvas.setFillColor(GREEN)
        canvas.circle(right, last_y, 2.6, stroke=0, fill=1)
        canvas.setFont("Crawler", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(left, 6, points[0].date.isoformat())
        canvas.drawRightString(right, 6, points[-1].date.isoformat())
        canvas.drawString(left, self.height - 9, f"High {price(high, self.snapshot.currency)}")
        canvas.drawRightString(right, self.height - 9, f"Low {price(low, self.snapshot.currency)}")


def _page(canvas, doc, snapshot: Snapshot) -> None:
    canvas.saveState()
    width, height = letter
    canvas.setFillColor(GREEN)
    canvas.circle(51, height - 31, 3.2, stroke=0, fill=1)
    canvas.setFont("Crawler-Bold", 8)
    canvas.setFillColor(INK)
    canvas.drawString(61, height - 34, "STOCK CRAWLER  /  RESEARCH")
    canvas.setFont("Crawler", 7.5)
    canvas.setFillColor(MUTED)
    label = "SYNTHETIC DEMO  /  NOT REAL DATA" if snapshot.demo else f"{snapshot.ticker}  /  MULTI-HORIZON OUTLOOK"
    canvas.drawRightString(width - 51, height - 34, label)
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(51, height - 45, width - 51, height - 45)
    canvas.line(51, 42, width - 51, 42)
    canvas.setFont("Crawler", 6.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(51, 29, "RESEARCH SCENARIOS, NOT PERSONALIZED INVESTMENT ADVICE")
    canvas.drawRightString(width - 51, 29, f"{doc.page:02d}")
    canvas.restoreState()


def _heading(story: list, number_: int, title: str, subtitle: str = "") -> None:
    if story:
        story.append(PageBreak())
    story.append(_p(f"RESEARCH NOTE  /  {number_:02d}", "kicker"))
    story.append(_p(title, "title"))
    if subtitle:
        story.append(_p(subtitle, "subtitle"))
    story.append(Spacer(1, 5))


def _bullet(story: list, label: str, detail: str) -> None:
    story.append(_rich(f'<font color="#116b56"><b>{_esc(label)}</b></font>  {_esc(detail)}', "body"))


def _value(info: dict, key: str, formatter, fallback: str = "Not available") -> str:
    value = number(info.get(key))
    return formatter(value) if value is not None else fallback


def _short_factor_score(score: float | None) -> str:
    return "Missing" if score is None else f"{score:+.2f}"


def _macro_value(value: float, unit: str) -> str:
    if unit == "%":
        return f"{value:.2f}%"
    if unit == "pp":
        return f"{value:+.2f} pp"
    if unit == "USD/barrel":
        return f"USD {value:.2f}/bbl"
    return f"{value:.2f}"


def _macro_change(point) -> str:
    if point.change_3m is None:
        return "Not available"
    if point.change_kind == "percent":
        return pct(point.change_3m, signed=True)
    return f"{point.change_3m:+.2f} pp"


def _source_link(title: str, url: str) -> str:
    return f'<link href="{_esc(url)}" color="#116b56">{_esc(title)}</link>' if url else _esc(title)


def _range_text(item, currency: str) -> str:
    return f"{currency} {item.low:,.2f}–{item.high:,.2f}" if item else "Withheld"


def _positioning_page(story: list, snapshot: Snapshot, analysis: Analysis) -> None:
    _heading(story, 9, "Market positioning & risk", "Sentiment is more than a headline: compare trading activity, short interest and option positioning.")
    info, pos = snapshot.info, analysis.positioning
    interest_day = date_from_timestamp(info.get("dateShortInterest"))
    short_float = number(info.get("shortPercentOfFloat"))
    if short_float is not None and not 0 <= short_float <= 1:
        short_float = None
    institutional = number(info.get("heldPercentInstitutions"))
    if institutional is not None and not 0 <= institutional <= 1:
        institutional = None
    rows = [
        ["20-day vs prior 60-day volume", f"{pos['volume_ratio']:.2f}x" if pos.get("volume_ratio") is not None else "Not available"],
        ["Adjusted close vs 50-day average", pct(pos.get("vs_ma50"), signed=True)],
        ["Adjusted close vs 200-day average", pct(pos.get("vs_ma200"), signed=True)],
        ["63-day realized volatility, annualized", pct(pos.get("volatility_63d"))],
        ["Shares sold short / float", pct(short_float) + (f" (as of {interest_day})" if interest_day else " (date not supplied)" if short_float is not None else "")],
        ["Shares short / previous observation", f"{compact(number(info.get('sharesShort')))} / {compact(number(info.get('sharesShortPriorMonth')))}"],
        ["Days to cover, provider-reported", _value(info, "shortRatio", lambda v: f"{v:.2f} days")],
        ["Institutional ownership", pct(institutional)],
    ]
    story.append(_table(["Positioning measure", "Observation"], rows, [285, 225], small=True))
    story.append(Spacer(1, 9))
    options = snapshot.options
    if options:
        ratio = f"{pos['put_call_oi']:.2f}x" if pos.get("put_call_oi") is not None else "Unavailable: incomplete or zero call open interest"
        story.append(_p("Options open interest " + _ref(snapshot, "O"), "section"))
        story.append(_p(f"Selected expiration: {options.expiration}. Known call open interest: {options.call_open_interest:,} across {options.call_known}/{options.call_total} contracts; known put open interest: {options.put_open_interest:,} across {options.put_known}/{options.put_total}. Put/call open-interest ratio: {ratio}. Retrieved {options.retrieved_at.strftime('%Y-%m-%d %H:%M UTC')}; provider values may be delayed.", "small"))
    else:
        story.append(_p("Options positioning for a suitable expiration was unavailable; no put/call ratio was invented.", "small"))
    refs = " ".join(dict.fromkeys((_ref(snapshot, "H"), _ref(snapshot, "Q"))))
    story.append(_note("Volume is a trading-activity proxy, not buy-versus-sell flow. Short interest is a delayed snapshot; options open interest may reflect hedges or spreads, not directional bets. A ratio is withheld unless all contracts in both selected sides have valid open interest. These measures do not identify who is bullish or bearish. " + refs))


def _sentiment_page(story: list, snapshot: Snapshot, analysis: Analysis) -> None:
    _heading(story, 10, "News tone & sentiment trends", "A measurable—but narrow—view of the language in provider-linked headlines.")
    sentiment = analysis.sentiment
    if sentiment and sentiment.headlines:
        overall = f"{sentiment.average:+.2f}" if sentiment.average is not None else "Insufficient sample"
        story.append(_metrics([("30-day headlines", str(len(sentiment.headlines))), ("Average tone", overall),
                               ("Positive / neutral / negative", f"{sentiment.positive_count} / {sentiment.neutral_count} / {sentiment.negative_count}")]))
        story.append(Spacer(1, 11))
        if sentiment.recent_average is not None and sentiment.prior_average is not None:
            trend = (f"Days 0–7: average {sentiment.recent_average:+.2f} from {sentiment.recent_count} headlines; "
                     f"days 8–30: {sentiment.prior_average:+.2f} from {sentiment.prior_count}. "
                     "This compares two small, potentially different samples, not a measured shift in all investors' views.")
        else:
            trend = (f"Recent window: {sentiment.recent_count} headlines; earlier window: {sentiment.prior_count}. "
                     "At least three in each window are required to compare tone over time.")
        story.append(_p(trend, "body"))
        story.append(_p("Eligible, issuer-matched headlines " + _ref(snapshot, "N"), "section"))
        for headline in sentiment.headlines:
            item = headline.item
            link = _source_link(text(item.title, 160), item.url)
            story.append(_rich(f"{link} <font color='#60726e'>— {_esc(item.publisher)}, {headline.published_date}, {_esc(headline.tone.lower())} ({headline.compound:+.2f})</font>", "small"))
    else:
        story.append(_note("No eligible, issuer-matched dated headlines from the past 30 days were available. A news-tone score and trend are not invented."))
        story.append(Spacer(1, 8))
    story.append(Spacer(1, 5))
    story.append(_p(_factor_evidence(snapshot, next(f for f in analysis.factors if f.key == "headlines")), "small"))
    story.append(_note("Tone uses English-language VADER with a small disclosed finance-word override. Headlines must match a provider ticker tag or company name/ticker, but this imperfect filter and the model can misread context, sarcasm or unknown-language text. Five matched headlines are needed for the 8% factor and three per time bucket for a trend. This is not a social-media poll or market-wide sentiment. " + _ref(snapshot, "V")))


def _politics_page(story: list, snapshot: Snapshot, analysis: Analysis) -> None:
    _heading(story, 13, "Elections & elected officials", "A nonpartisan snapshot of US policymakers and the next scheduled federal general election.")
    political = snapshot.politics
    if political and (political.executives or political.leaders or political.headquarters_senators):
        rows = [[text(item.role, 45), text(item.name, 60), text(item.party, 35), item.start.isoformat()]
                for item in (political.executives[:2] + political.leaders[:5])]
        if rows:
            story.append(_table(["Office / leadership role", "Officeholder", "Party", "Role since"], rows, [175, 145, 100, 90], small=True))
            story.append(Spacer(1, 6))
        else:
            story.append(_p("Current executive and congressional leadership records were unavailable.", "small"))
        retrieved = political.retrieved_at.strftime("%Y-%m-%d %H:%M UTC") if political.retrieved_at else "date not provided"
        if snapshot.demo:
            source_note = f"These officials and terms are fictional demo data generated {retrieved}. {_ref(snapshot, 'P')}"
        else:
            source_note = (f"The oldest available political dataset was fetched {retrieved} and may be cached for six hours. "
                           f"This community source can lag vacancies or changes; verify official records. {_ref(snapshot, 'P')}")
        story.append(_p(source_note, "muted"))
        if political.headquarters_state:
            story.append(_p(f"Headquarters-state senators: {political.headquarters_state}", "section"))
            if political.headquarters_senators:
                rows = [[item.name, item.party, item.start.isoformat()] for item in political.headquarters_senators[:2]]
                story.append(_table(["US senator", "Party", "Current term began"], rows, [210, 150, 150], small=True))
            else:
                story.append(_p("The source did not identify current senators for the reported headquarters state.", "small"))
            story.append(_p("Headquarters location does not establish a politician's relationship to, support for, or influence over the company; customers and operations may be elsewhere.", "muted"))
    else:
        story.append(_note("Current elected-officeholder data were unavailable. Names and party control are not guessed."))
        story.append(Spacer(1, 8))
    if analysis.next_election:
        kind = "presidential" if analysis.next_election.year % 4 == 0 else "congressional midterm"
        story.append(_p("Next scheduled federal general election", "section"))
        story.append(_p(f"{analysis.next_election.isoformat()} ({kind}) under the standard US federal calendar: the Tuesday after the first Monday in November. This is not a forecast of candidates or results; primaries and special elections differ. {_ref(snapshot, 'E')}", "body"))
    story.append(_note("Political affiliation alone does not establish how an issuer will perform. Policy, courts, Congress, central-bank independence and company-specific exposure all matter. The event study on the following pages reports outcomes without asserting causation."))


def _policy_page(story: list, snapshot: Snapshot, analysis: Analysis) -> None:
    _heading(story, 14, "Policy exposure & the company", "How political decisions can reach this business—conditional on its actual operations and customers.")
    for label, detail in analysis.policy_channels:
        story.append(_p(label.upper(), "kicker"))
        story.append(_p(text(detail, 360), "small"))
    if snapshot.filing and snapshot.filing.policy_excerpts:
        story.append(_p("Issuer disclosure to verify " + _ref(snapshot, "F"), "section"))
        story.append(_p('“' + text(snapshot.filing.policy_excerpts[0], 350) + '”', "small"))
        story.append(_p("This is a selected annual-filing excerpt, not a complete policy-risk review; read the full filing.", "muted"))
    else:
        story.append(_p("The available filing search did not establish an issuer-specific policy exposure. Review the company's filings and contracts; an absence of excerpts is not proof of no exposure.", "small"))
    story.append(_note("These are potential mechanisms, not claims that a particular law will pass or that an elected official favors the company. Party labels and sparse event-window returns are not assigned an arbitrary political score in the six-month model."))


def _election_page(story: list, snapshot: Snapshot, analysis: Analysis) -> None:
    _heading(story, 15, "Stock reactions around elections", "Historical event windows for this ticker, with a broad-market comparison where available.")
    if analysis.election_reactions:
        rows = []
        for event in analysis.election_reactions[:6]:
            label = text(f"{event.election_type}: {event.outcome}", 58)
            rows.append([event.election_date.isoformat(), label, event.anchor_date.isoformat(),
                         pct(event.return_10d, signed=True), pct(event.return_63d, signed=True),
                         pct(event.return_126d, signed=True), pct(event.benchmark_63d, signed=True)])
        story.append(_table(["Election", "Type / recorded winner", "Prior close", "+10 days", "+63 days", "+126 days", "SPY +63"],
                            rows, [64, 120, 64, 65, 65, 65, 67], small=True))
        story.append(Spacer(1, 10))
        paired = [event for event in analysis.election_reactions if event.return_63d is not None and event.benchmark_63d is not None]
        if paired:
            latest = paired[0]
            difference = (latest.return_63d - latest.benchmark_63d) * 100
            story.append(_p(f"For the latest complete matched window (the {latest.anchor_date} close before the {latest.election_date} election through {latest.end_63d}), the ticker's 63-session adjusted-close return was {pct(latest.return_63d, signed=True)} versus {pct(latest.benchmark_63d, signed=True)} for SPY: a {difference:+.1f} percentage-point difference. This is not a causal or beta-adjusted abnormal return.", "body"))
        else:
            story.append(_p("A matched SPY comparison was unavailable or not applicable; no benchmark return is assumed.", "body"))
    else:
        story.append(_note("No complete or usable election windows were found in the available adjusted-price history. This may reflect a recent listing, missing adjusted closes or unavailable historical data."))
        story.append(Spacer(1, 8))
    story.append(_p("How the comparison works", "section"))
    refs = [_ref(snapshot, 'H'), _ref(snapshot, 'E')]
    if snapshot.benchmark_prices:
        refs.append(_ref(snapshot, 'B'))
    if snapshot.politics:
        refs.append(_ref(snapshot, 'P'))
    refs = list(dict.fromkeys(refs))
    benchmark_note = ("The demo's series labeled SPY is entirely synthetic." if snapshot.demo else
                      "SPY is a US-dollar ETF proxy, not the index itself, and is compared only when dates match.")
    story.append(_p(f"The anchor is the last available close before election day; +10, +63 and +126 are subsequent trading sessions (roughly two weeks, three months and six months), not calendar days. Returns use provider-adjusted closes, which account for distributions/splits subject to provider accuracy. {benchmark_note} {' '.join(refs)}", "small"))
    story.append(_note("Elections coincide with earnings, wars, interest rates, market regimes and many other events. A handful of observations cannot isolate a politician's effect or reliably predict the next election; international listings also have currency and trading-hours differences. These descriptive returns are not used as a political coefficient in the price ranges."))

def _investment_narrative(story: list, snapshot: Snapshot, analysis: Analysis) -> None:
    """Connect issuer evidence to valuation, macro transmission and risks.

    This is a deterministic synthesis of available observations, not an LLM;
    missing facts and causal links are never filled in by conjecture.
    """
    info = snapshot.info
    factors = {factor.key: factor for factor in analysis.factors}
    financial_currency = text(info.get("financialCurrency"), 12) or "reporting currency"
    story.append(_p("The business and the operating engine", "section"))
    overview = text(info.get("longBusinessSummary"), 280)
    if overview:
        story.append(_p(overview + " " + _ref(snapshot, "Q"), "small"))
    else:
        story.append(_p("The available profile does not establish how this issuer earns revenue. Review its filings before drawing a business thesis.", "small"))
    operating = []
    growth, margin, fcf = (number(info.get(key)) for key in ("revenueGrowth", "operatingMargins", "freeCashflow"))
    if growth is not None:
        operating.append(f"revenue growth {pct(growth, signed=True)}")
    if margin is not None:
        operating.append(f"operating margin {pct(margin)}")
    if fcf is not None:
        operating.append(f"free cash flow {compact(fcf, financial_currency)}")
    if operating:
        story.append(_p("Provider-reported operating evidence: " + "; ".join(operating) + ". These fields may cover different periods. " + _ref(snapshot, "Q"), "small"))
    if snapshot.filing and snapshot.filing.customer_excerpts:
        story.append(_p("Customer evidence to verify in context: “" + text(snapshot.filing.customer_excerpts[0], 180) + "” " + _ref(snapshot, "F"), "small"))
    else:
        story.append(_p("Named customers or concentration are not established by the available source excerpts.", "small"))

    story.append(_p("What the price and peers imply", "section"))
    story.append(_p(_factor_evidence(snapshot, factors["valuation"]) + " " +
                    _factor_evidence(snapshot, factors["momentum"]), "small"))
    story.append(_p("The peer multiple and past return are context, not proof that the market is mispricing this business. Sections 5–10 unpack the financials, expectations and sentiment.", "muted"))
    expectations = [factors[key] for key in ("analysts", "headlines") if factors[key].score is not None]
    if expectations:
        story.append(_p("Expectations and tone: " + " ".join(_factor_evidence(snapshot, factor) for factor in expectations) +
                        " These are incomplete external signals, not proof that the business will meet expectations.", "small"))
    else:
        story.append(_p("Analyst or headline sentiment is insufficient to add a scored expectation signal.", "small"))

    story.append(_p("How the backdrop can reach this company", "section"))
    rate = snapshot.macro.get("DGS10")
    rate_text = (f"The US 10-year yield changed {_macro_change(rate)} over roughly three months (observation {rate.as_of}). "
                 + _ref(snapshot, "M1") + " ") if rate and rate.change_3m is not None else "The US yield change is unavailable. "
    story.append(_p(rate_text + text(analysis.macro_channels[0][1], 330) + " " + _ref(snapshot, "Q"), "small"))
    story.append(_p("This is a conditional transmission channel, not evidence that the yield move caused the stock's return. See sections 11–15 for other macro and policy exposures.", "muted"))
    if analysis.policy_channels:
        story.append(_p("Unscored policy watch: " + text(analysis.policy_channels[0][1], 220), "small"))
    recent_event = next((item for item in analysis.election_reactions if item.return_63d is not None), None)
    if recent_event:
        story.append(_p(f"After the {recent_event.election_date} election, the ticker's 63-session adjusted return was {pct(recent_event.return_63d, signed=True)}. Other events coincided; this does not establish political causation. {_ref(snapshot, 'H')} {_ref(snapshot, 'E')}", "small"))

    story.append(_p("What could change the thesis", "section"))
    if snapshot.filing and snapshot.filing.risk_excerpts:
        risk = "The issuer disclosed: “" + text(snapshot.filing.risk_excerpts[0], 200) + "” " + _ref(snapshot, "F")
    else:
        risk = "The available filing search did not establish a specific issuer risk; verify customer demand, funding and competitive pressures."
    story.append(_p(risk + " Watch whether revenue growth, margins, cash generation and financing conditions move together or diverge.", "small"))
    six = next((item for item in analysis.ranges if item.months == 6), None)
    outlook = (f"Illustrative six-month range: {_range_text(six, snapshot.currency)}. " if six else "Price ranges are withheld until the evidence and adjusted-volatility checks pass. ")
    story.append(_p(outlook + "Section 16 shows all three horizons; section 17 tests only historically observable factors, not the complete verdict.", "small"))


def create_report(snapshot: Snapshot, analysis: Analysis, output: str | Path) -> int:
    """Write the report and return its page count. All external text is escaped."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output), pagesize=letter, leftMargin=51, rightMargin=51, topMargin=63, bottomMargin=55,
                            title=f"{snapshot.ticker} | Stock Crawler research", author="Stock Crawler",
                            subject="Sourced research scenarios; not investment advice")
    story: list = []
    info = snapshot.info
    currency = snapshot.currency
    # Provider aggregate values can be denominated differently from a price
    # quoted in a minor unit (for example GBp versus GBP); do not guess.
    cap_currency = "provider units; verify currency" if currency in MINOR_UNIT_CURRENCIES else currency
    financial_currency = text(info.get("financialCurrency"), 12) or "reporting currency"
    sector = text(info.get("sector"), 80) or "Not available"
    industry = text(info.get("industry"), 90) or "Not available"
    six_month_range = next((item for item in analysis.ranges if item.months == 6), None)
    range_display = _range_text(six_month_range, currency)
    six_month_date = snapshot.price_date + relativedelta(months=6)
    as_of = snapshot.fetched_at.strftime("%Y-%m-%d %H:%M UTC")
    factors = {factor.key: factor for factor in analysis.factors}

    # 01 / Cover
    _heading(story, 1, "Equity research" if snapshot.quote_type == "EQUITY" else "Instrument research",
             "A connected view of the available evidence, risks, and the next six months.")
    story.append(Spacer(1, 13))
    story.append(_p(text(snapshot.name, 105), "cover"))
    story.append(_p(f"{snapshot.ticker}  /  {sector}  /  {industry}", "subtitle"))
    story.append(Spacer(1, 8))
    story.append(_metrics([
        ("Model conclusion", analysis.verdict),
        ("Last close", price(snapshot.price, currency)),
        ("6-month range", range_display),
    ]))
    story.append(Spacer(1, 16))
    story.append(_p("THE PRICE IN CONTEXT", "kicker"))
    story.append(PriceChart(snapshot, height=145))
    story.append(Spacer(1, 12))
    cover_note = (f"Anchor: close on {snapshot.price_date.isoformat()}. Range horizons: 1, 3 and 6 calendar months. "
                  f"Data retrieved {as_of}. Ranges are illustrative, not confidence intervals. {_ref(snapshot, 'H')}")
    story.append(_note(cover_note))
    story.append(Spacer(1, 8))
    story.append(_p("DEMO: all figures, people, company details and macro observations are fictional." if snapshot.demo else
                    "An evidence-weighted model conclusion, not a guarantee or a substitute for your own diligence.", "muted"))

    # 02 / Executive conclusion
    _heading(story, 2, "The investment decision", "A direct conclusion, with the opposing evidence kept in view.")
    if analysis.score is not None:
        verdict_text = (f"Stock Crawler's conclusion is {analysis.verdict.upper()}. The available inputs score {analysis.score:+.2f} "
                        f"on a -1 to +1 scale, with {analysis.coverage:.0%} of the model's factor weight available. "
                        "This is our rules-based synthesis, not a claim about Wall Street consensus.")
    else:
        verdict_text = "The available evidence is insufficient to calculate a meaningful overall score or price ranges."
    story.append(_note(verdict_text, GREEN if analysis.verdict == "Bullish" else RED if analysis.verdict == "Bearish" else AMBER))
    story.append(Spacer(1, 10))
    positive = sorted((f for f in analysis.factors if f.score is not None and f.score > 0), key=lambda f: f.weight * float(f.score), reverse=True)
    negative = sorted((f for f in analysis.factors if f.score is not None and f.score < 0), key=lambda f: f.weight * float(f.score))
    _investment_narrative(story, snapshot, analysis)

    # 03 / Business and customer exposure
    _heading(story, 3, "The business & its customers", "What the issuer does, who pays it, and what the sources actually disclose.")
    description = text(info.get("longBusinessSummary"), 1150)
    if description:
        story.append(_p("COMPANY PROFILE EXCERPT " + _ref(snapshot, "Q"), "kicker"))
        story.append(_p(description, "body"))
    else:
        story.append(_p("A business description was not supplied by the market-data provider. Review the issuer's investor-relations materials before relying on this report.", "body"))
    story.append(_p("Customer and concentration disclosures", "section"))
    if snapshot.filing and snapshot.filing.customer_excerpts:
        story.append(_p(f"Selected excerpts from {snapshot.filing.form}, filed {snapshot.filing.filing_date.isoformat()}. These snippets are not a complete customer list; read the original context. {_ref(snapshot, 'F')}", "muted"))
        for excerpt in snapshot.filing.customer_excerpts[:2]:
            story.append(_p('“' + text(excerpt, 360) + '”', "body"))
    else:
        story.append(_p("The available sources do not establish named customers or concentration. This does not mean they do not exist or that concentration is low. Enable SEC filing retrieval where applicable and review the latest annual filing.", "body"))
    if snapshot.holdings:
        story.append(_p("Fund holdings supplied by the provider", "section"))
        story.append(_table(["Symbol", "Holding", "Weight"], [[x, text(n, 55), pct(w) if w is not None else "Not available"] for x, n, w in snapshot.holdings[:5]], [95, 300, 115], small=True))
    story.append(Spacer(1, 8))
    story.append(_note("Investor question: which end markets, renewal cycles and large customers drive revenue, and how much bargaining power do they have? Verify any answer in the issuer's filings; a product list alone is not a customer list."))

    # 04 / People
    _heading(story, 4, "Management & stewardship", "Known leadership, operating context and the questions that remain open.")
    officers = info.get("companyOfficers") if isinstance(info.get("companyOfficers"), list) else []
    officer_rows = []
    for officer in officers[:7]:
        if isinstance(officer, dict):
            officer_rows.append([text(officer.get("name"), 65) or "Not available", text(officer.get("title"), 100) or "Title not supplied"])
    if officer_rows:
        story.append(_table(["Name", "Provider-reported role"], officer_rows, [195, 315]))
        story.append(Spacer(1, 6))
        story.append(_p(f"Leadership is a provider snapshot retrieved {as_of}; appointments may have changed. {_ref(snapshot, 'Q')}", "muted"))
    else:
        story.append(_note("The market-data provider did not supply officer names and titles. This report does not infer a management team."))
    story.append(_p("Company context", "section"))
    employees = number(info.get("fullTimeEmployees"))
    location = ", ".join(text(info.get(key), 50) for key in ("city", "state", "country") if info.get(key)) or "Not available"
    story.append(_table(["Field", "Reported value"], [
        ["Sector / industry", f"{sector} / {industry}"],
        ["Headquarters", location],
        ["Full-time employees", f"{employees:,.0f}" if employees is not None else "Not available"],
        ["Investor website", text(info.get("website"), 110) or "Not available"],
    ], [165, 345]))
    story.append(Spacer(1, 8))
    story.append(_p("Governance to verify: leadership tenure and changes, board independence, compensation incentives, capital allocation and ownership. Names and titles alone are not evidence of management quality. " + _ref(snapshot, "Q"), "body"))

    # 05 / Market and valuation
    _heading(story, 5, "Market value & valuation", "Price history and valuation measures are observations, not forecasts.")
    story.append(PriceChart(snapshot, height=155))
    story.append(Spacer(1, 7))
    market_rows = [
        ["Last daily close", f"{price(snapshot.price, currency)} on {snapshot.price_date}"],
        ["Market capitalization", _value(info, "marketCap", lambda v: compact(v, cap_currency))],
        ["Enterprise value", _value(info, "enterpriseValue", lambda v: compact(v, cap_currency))],
        ["Trailing P/E", _value(info, "trailingPE", lambda v: f"{v:.2f}x")],
        ["Forward P/E", _value(info, "forwardPE", lambda v: f"{v:.2f}x")],
        ["52-week range", f"{price(number(info.get('fiftyTwoWeekLow')), currency)} to {price(number(info.get('fiftyTwoWeekHigh')), currency)}" if number(info.get("fiftyTwoWeekLow")) is not None and number(info.get("fiftyTwoWeekHigh")) is not None else "Not available"],
    ]
    story.append(_table(["Measure", "Provider-reported observation"], market_rows, [210, 300]))
    story.append(Spacer(1, 8))
    story.append(_p(_factor_evidence(snapshot, factors["valuation"]) + " A low multiple may reflect genuine business risk; a high multiple may reflect durable growth. " + _ref(snapshot, "H"), "small"))
    if snapshot.peers and snapshot.peers.members:
        peers = "; ".join(f"{item.ticker} ({text(item.name, 32)}) {item.forward_pe:.1f}x" for item in snapshot.peers.members)
        fetched = snapshot.peers.retrieved_at.strftime("%Y-%m-%d %H:%M UTC")
        story.append(_p(f"Same-industry peer sample, retrieved {fetched}: {peers}. {_ref(snapshot, 'R')}", "small"))
        story.append(_p("Positive forward P/Es only; the issuer is excluded. Provider industry membership and earnings estimates can change, and the small sample is not a complete peer universe.", "muted"))
    else:
        story.append(_p("Comparable peer multiples were unavailable; no fixed sector P/E has been substituted.", "muted"))

    # 06 / Operations
    _heading(story, 6, "Growth & financial quality", "Connect revenue growth, profitability and cash generation rather than reading any one number alone.")
    financial_rows = [
        ["Revenue, provider-reported", _value(info, "totalRevenue", lambda v: compact(v, financial_currency))],
        ["Revenue growth", _value(info, "revenueGrowth", lambda v: pct(v, signed=True))],
        ["Earnings growth", _value(info, "earningsGrowth", lambda v: pct(v, signed=True))],
        ["Gross margin", _value(info, "grossMargins", pct)],
        ["Operating margin", _value(info, "operatingMargins", pct)],
        ["Net profit margin", _value(info, "profitMargins", pct)],
        ["Free cash flow", _value(info, "freeCashflow", lambda v: compact(v, financial_currency))],
        ["Return on equity", _value(info, "returnOnEquity", pct)],
    ]
    story.append(_table(["Indicator", "Observation"], financial_rows, [250, 260]))
    quarter_end = date_from_timestamp(info.get("mostRecentQuarter"))
    if quarter_end:
        story.append(Spacer(1, 4))
        story.append(_p(f"Provider's most recent reported quarter ends {quarter_end}; individual metrics may use different periods. {_ref(snapshot, 'Q')}", "muted"))
    if snapshot.annuals:
        story.append(_p("Annual income statement history " + _ref(snapshot, "S"), "section"))
        annual_rows = [[item.period_end.isoformat(), compact(item.revenue, financial_currency), compact(item.operating_income, financial_currency), compact(item.net_income, financial_currency)] for item in snapshot.annuals[:3]]
        story.append(_table(["Period end", "Revenue", "Operating income", "Net income"], annual_rows, [105, 135, 135, 135], small=True))
    else:
        story.append(_p("Annual income statement history was not available; verify multi-year trends in the issuer's filings.", "muted"))
    story.append(Spacer(1, 6))
    _bullet(story, "Growth signal.", _factor_evidence(snapshot, factors["growth"]))
    _bullet(story, "Profitability signal.", _factor_evidence(snapshot, factors["profitability"]))
    story.append(_note("Provider metrics may use different reporting periods and definitions. Growth and margins are not peer-normalized; banks, funds and early-stage businesses require special interpretation. Check the financial statements for period, non-recurring items and cash-flow quality."))

    # 07 / Balance sheet
    _heading(story, 7, "Balance sheet & cash", "Liquidity and funding flexibility can determine whether a good business survives a bad cycle.")
    cash, debt, cap, fcf = (number(info.get(key)) for key in ("totalCash", "totalDebt", "marketCap", "freeCashflow"))
    # GBp (pence) and GBP (pounds), for example, are not the same unit.
    same = bool(info.get("financialCurrency") and info.get("currency") and str(info["financialCurrency"]) == str(info["currency"])
                and str(info["currency"]) not in MINOR_UNIT_CURRENCIES)
    net_debt = debt - cash if debt is not None and cash is not None and sector != "Financial Services" else None
    yield_value = fcf / cap if same and fcf is not None and cap is not None and cap > 0 and sector != "Financial Services" else None
    rows = [
        ["Cash and equivalents", compact(cash, financial_currency)],
        ["Total debt", compact(debt, financial_currency)],
        ["Net debt (debt less cash)", compact(net_debt, financial_currency) if net_debt is not None else "Not calculated"],
        ["Current ratio", _value(info, "currentRatio", lambda v: f"{v:.2f}x")],
        ["Free cash flow", compact(fcf, financial_currency)],
        ["Free cash flow / market value", pct(yield_value, signed=True) if yield_value is not None else "Not calculated"],
        ["Shares outstanding", _value(info, "sharesOutstanding", lambda v: compact(v))],
    ]
    story.append(_table(["Measure", "Observation"], rows, [250, 260]))
    cash_rows = [[item.period_end.isoformat(), compact(item.operating_cash_flow, financial_currency),
                  compact(item.capital_expenditure, financial_currency), compact(item.free_cash_flow, financial_currency)]
                 for item in snapshot.annuals[:3] if any(v is not None for v in (item.operating_cash_flow, item.capital_expenditure, item.free_cash_flow))]
    if cash_rows:
        story.append(_p("Annual cash-flow history " + _ref(snapshot, "S"), "section"))
        story.append(_table(["Period end", "Operating cash flow", "Capital expenditure", "Free cash flow"], cash_rows, [100, 140, 135, 135], small=True))
        story.append(_p("Capital expenditure is shown with the provider's reported sign; missing values are not estimated.", "muted"))
    story.append(Spacer(1, 8))
    story.append(_p(_factor_evidence(snapshot, factors["balance"]), "body"))
    story.append(_p("What changes the thesis", "section"))
    story.append(_p("Positive free cash flow can support investment, debt reduction or distributions; negative free cash flow can require funding. Neither establishes future cash generation. Higher borrowing costs matter most when debt is floating-rate or comes due; maturities and covenants are not provided by this snapshot.", "body"))
    story.append(_note("Cash, debt and free cash flow use the reporting currency. Market-value units can be ambiguous for minor-unit quotes. Cross-currency or ambiguous-unit ratios are withheld rather than converted with an unstated FX rate. Net debt is not used for financial institutions. " + _ref(snapshot, "Q")))

    # 08 / Expectations
    _heading(story, 8, "Price action & expectations", "Separate backwards-looking market behavior from analyst opinion and our six-month model.")
    analyst_mean = number(info.get("recommendationMean"))
    analyst_count = number(info.get("numberOfAnalystOpinions"))
    analyst_target = number(info.get("targetMeanPrice"))
    expectation_rows = [
        ["1-month adjusted return", pct(analysis.returns["1m"], signed=True)],
        ["3-month adjusted return", pct(analysis.returns["3m"], signed=True)],
        ["6-month adjusted return", pct(analysis.returns["6m"], signed=True)],
        ["Provider analyst recommendation", f"{analyst_mean:.2f}/5" if analyst_mean is not None else "Not available"],
        ["Analysts represented", f"{analyst_count:.0f}" if analyst_count is not None else "Not available"],
        ["Provider mean analyst target", price(analyst_target, currency)],
        ["Stock Crawler 6-month range", range_display],
    ]
    story.append(_table(["Measure", "Observation"], expectation_rows, [260, 250]))
    story.append(Spacer(1, 10))
    story.append(_p(_factor_evidence(snapshot, factors["momentum"]), "body"))
    story.append(_p(_factor_evidence(snapshot, factors["analysts"]), "body"))
    if snapshot.analyst_trend:
        story.append(_p("Analyst recommendation snapshots " + _ref(snapshot, "A"), "section"))
        analyst_rows = [[row.period, f"{row.strong_buy} / {row.buy}", str(row.hold), f"{row.sell} / {row.strong_sell}",
                         pct((row.strong_buy + row.buy) / row.count)] for row in snapshot.analyst_trend[:4]]
        story.append(_table(["Period", "Strong buy / buy", "Hold", "Sell / strong sell", "Buy share"], analyst_rows, [65, 120, 65, 135, 125], small=True))
        story.append(_p("0m is the provider's current-month snapshot; -1m, -2m and -3m are earlier snapshots. Coverage may change between periods, so shifts are not necessarily upgrades by the same analysts.", "muted"))
    story.append(_note("The provider's analyst target is a separate outside consensus, typically associated with a longer horizon; verify its date and horizon with the provider. It is not Stock Crawler's volatility-based range. Averages can hide disagreement, stale estimates and very small samples. " + _ref(snapshot, "A")))
    story.append(Spacer(1, 7))
    story.append(_p("Historical returns use provider-adjusted closes on or before the calendar lookback date, accounting for provider-reported distributions and splits. No benchmark outperformance is implied. " + _ref(snapshot, "H"), "small"))

    _positioning_page(story, snapshot, analysis)
    _sentiment_page(story, snapshot, analysis)

    # 11 / Macro snapshot
    _heading(story, 11, "The macro backdrop", "US indicators are observed independently; the transmission to this company is assessed next.")
    macro_rows = []
    for code, label, unit, kind, source_id in SERIES:
        point = snapshot.macro.get(code)
        macro_rows.append([
            label + " " + _ref(snapshot, source_id),
            _macro_value(point.value, point.unit) if point else "Unavailable",
            _macro_change(point) if point else "Unavailable",
            point.as_of.isoformat() if point else "—",
        ])
    story.append(_table(["Indicator", "Latest", "~3m change", "As of"], macro_rows, [220, 95, 105, 90], small=True))
    story.append(Spacer(1, 12))
    story.append(_p("How to read the changes", "section"))
    story.append(_p("Rates, yield/credit spreads, unemployment, CPI inflation and real GDP growth changes are in percentage points (pp); oil, the dollar index and VIX changes are percentages. The comparison is the nearest available observation at or before three calendar months earlier. CPI and real GDP growth are calculated versus the same calendar month/quarter a year earlier. Each series has its own publication lag.", "body"))
    story.append(_p("The US is a global financial reference point, but these indicators are not a complete picture of local conditions or an issuer's geographic revenue mix. An observed macro change is not proof that it caused a stock move.", "body"))
    story.append(_note(_demo_refs(snapshot, factors["macro"].evidence)))

    # 10 / Macro channels
    _heading(story, 12, "How macro reaches this stock", "Transmission mechanisms are conditional; business mix and management actions can change the outcome.")
    for label, detail in analysis.macro_channels:
        story.append(_p(label.upper(), "kicker"))
        story.append(_p(text(detail, 430), "body"))
    story.append(Spacer(1, 4))
    story.append(_note("The scored macro overlay uses recent yield, unemployment and inflation changes; oil is also scored only for selected upstream energy or airline industries. The dollar is context only. Sector signs are assumptions, not company-specific statistical estimates. See the model rubric."))

    _politics_page(story, snapshot, analysis)
    _policy_page(story, snapshot, analysis)
    _election_page(story, snapshot, analysis)

    # 16 / Volatility-based price ranges
    _heading(story, 16, "Price ranges across three horizons", "A common thesis, expressed as 1-, 3- and 6-month ranges rather than a point target.")
    if analysis.ranges:
        rows = [[f"{item.months} month{'s' if item.months != 1 else ''}", item.end_date.isoformat(),
                 price(item.low, currency), price(item.high, currency)] for item in analysis.ranges]
        story.append(_table(["Horizon", "End date", "Lower bound", "Upper bound"], rows, [110, 120, 140, 140]))
        story.append(Spacer(1, 12))
        story.append(_p(f"From the {snapshot.price_date} close, the last 63 consecutive adjusted-close daily log returns imply an annualized realized volatility of {pct(analysis.realized_volatility)}. The same normalized evidence score ({analysis.score:+.3f}) shapes the drift across the three horizons. {_ref(snapshot, 'H')}", "body"))
        story.append(_p("For each horizon m in months, assumed log drift = 0.16 × score × m/6; the half-width = realized volatility × √(m/12). Bounds equal the last close × exp(drift ± half-width). This is one historical-volatility shock, not a calibrated probability or confidence interval.", "body"))
        story.append(_note("Past volatility may understate jumps, regime changes, liquidity and future risk. Drift and scaling are judgmental; no probability is assigned to the bounds. Ranges are price-only, exclude future dividends and costs, and can be exceeded."))
    else:
        story.append(_note("No 1-, 3- or 6-month price ranges are issued. They require the equity, freshness, factor coverage, fundamental and macro checks, plus 64 consecutive usable adjusted closes and positive plausible realized volatility."))
        story.append(Spacer(1, 10))
        story.append(_p("A range is withheld rather than substituting beta or inventing missing price history. The qualitative bull and bear cases remain conditional, and the scorecard explains the data gaps.", "body"))
    story.append(Spacer(1, 8))
    story.append(_p("The historical test on the next page evaluates only the scorecard factors that can be reconstructed from past data; it cannot establish the accuracy of today's complete thesis.", "small"))

    # 17 / Historical evidence
    _heading(story, 17, "Historical scorecard test", "A rolling, non-overlapping test for this ticker—not a claim of overall model accuracy.")
    backtest = analysis.backtest
    if backtest:
        story.append(_p(f"Tested subset: {backtest.method}. Historical company fundamentals, contemporaneous peer medians, analyst views and headline tone are not reconstructed and are never borrowed from today's snapshot.", "body"))
        rows = []
        for item in backtest.horizons:
            hit = f"{item.hit_rate:.1%}" if item.hit_rate is not None else "Unavailable"
            baseline = f"{item.always_up_rate:.1%}" if item.always_up_rate is not None else "Unavailable"
            within = f"{item.range_hits}/{item.range_observations} ({item.range_hits / item.range_observations:.1%})" if item.range_observations else "Unavailable"
            rows.append([f"{item.months} month{'s' if item.months != 1 else ''}", f"{item.correct_calls}/{item.directional_calls}", hit, baseline, within])
        story.append(_table(["Horizon", "Correct / calls", "Hit rate", "Always-up baseline", "Adj-return coverage"], rows, [85, 105, 75, 115, 130], small=True))
        story.append(Spacer(1, 8))
        for item in backtest.horizons:
            dates = f"{item.first_anchor}–{item.last_anchor}" if item.first_anchor else "no directional calls"
            story.append(_p(f"{item.months}m: {item.bullish_calls} bullish and {item.bearish_calls} bearish calls; {item.flat_outcomes} flat outcomes excluded; directional anchors {dates}.", "small"))
        story.append(_p("A hit means the sign of the non-neutral subset score matched the subsequent adjusted-close return. The always-up baseline uses the same eligible dates. Coverage tests adjusted total returns against partial-score bounds; it does not test today's price-only, complete-score ranges.", "small"))
        for note in backtest.notes:
            story.append(_p("• " + note, "small"))
        refs = [_ref(snapshot, "H")]
        if "macro" in backtest.factors:
            refs.extend(_ref(snapshot, key) for key in ("M1", "M3", "M4"))
        story.append(_p(" ".join(dict.fromkeys(refs)), "muted"))
    else:
        story.append(_note("No historical hit rate is available: the issuer needs sufficient dated adjusted-close history to reconstruct and evaluate past signals. A result is not invented."))
    story.append(Spacer(1, 8))
    recorded = analysis.recorded_backtest
    matured = recorded and any(item.directional_calls for item in recorded.horizons)
    if matured:
        story.append(_rich("<b>Separate prospective full-scorecard archive.</b> Previously recorded verdicts, not reconstructed fundamentals, are evaluated from the first close after each report date. Only this installation and model revision are represented.", "small"))
        archived_rows = []
        for item in recorded.horizons:
            hit = f"{item.hit_rate:.1%}" if item.hit_rate is not None else "Unavailable"
            baseline = f"{item.always_up_rate:.1%}" if item.always_up_rate is not None else "Unavailable"
            archived_rows.append([f"{item.months}m", f"{item.correct_calls}/{item.directional_calls}", hit, baseline])
        story.append(_table(["Horizon", "Correct / calls", "Hit rate", "Always-up baseline"], archived_rows, [100, 130, 130, 150], small=True))
        story.append(_p("Non-overlapping windows; neutral and flat outcomes are excluded. This locally selected sample is not representative.", "small"))
    else:
        story.append(_rich("<b>Full scorecard:</b> No locally archived directional verdicts have matured yet. Sufficient-data live verdicts are recorded for future evaluation unless local storage fails; fictional demo runs are never recorded.", "small"))
    story.append(_note("Small samples and a single surviving ticker can mislead. Hit rate does not measure returns, risk, statistical significance or future performance; the full scorecard is not independently validated."))

    # 18 / Bull case
    _heading(story, 18, "The bull case", "What has to go right, and which observed facts currently support that path.")
    if six_month_range:
        story.append(_note(f"Illustrative upper end of the six-month range: {price(six_month_range.high, currency)} by {six_month_date}. This is a volatility-based scenario bound, not an assigned probability."))
        story.append(Spacer(1, 10))
    for factor in positive[:4]:
        _bullet(story, factor.label + ".", _factor_evidence(snapshot, factor))
    if not positive:
        story.append(_p(analysis.positives[0], "body"))
    story.append(_p("What needs to happen", "section"))
    story.append(_p(f"{snapshot.name} would need to sustain or improve its provider-reported revenue growth and operating margin, while retaining customers and funding its operations. Easier or stable financial conditions could help through {_sector_channel_for_report(sector)}; none of those outcomes is assumed to be certain.", "body"))
    story.append(_p("What would invalidate this case", "section"))
    story.append(_p("Watch for a material slowdown in revenue, deteriorating operating margins, lost or concentrated customers, or a rise in financing costs. Favorable current metrics can already be reflected in the price.", "body"))
    story.append(_p("The bull case is a conditional alternative, not a recommendation to buy. Review the opposite case before acting.", "muted"))

    # 13 / Bear case
    _heading(story, 19, "The bear case", "What can go wrong even when the overall score is positive.")
    if six_month_range:
        story.append(_note(f"Illustrative lower end of the six-month range: {price(six_month_range.low, currency)} by {six_month_date}. The downside can exceed this bound; it is not a stop or guarantee.", RED))
        story.append(Spacer(1, 10))
    for factor in negative[:3]:
        _bullet(story, factor.label + ".", _factor_evidence(snapshot, factor))
    if not negative:
        story.append(_p(analysis.negatives[0], "body"))
    if snapshot.filing and snapshot.filing.risk_excerpts:
        story.append(_p("Issuer disclosure to examine", "section"))
        story.append(_p('“' + text(snapshot.filing.risk_excerpts[0], 360) + '” ' + _ref(snapshot, "F"), "body"))
        story.append(_p("This is a selected excerpt, not a complete risk-factor analysis; read the filing in full.", "muted"))
    story.append(_p("Downside transmission", "section"))
    story.append(_p(f"Weak customer demand can slow growth; inflation can pressure margins; and higher yields or funding costs can challenge valuation and liquidity. For the {industry} industry, the relevant channel is {_sector_channel_for_report(sector)}. Actual exposure depends on the company's contracts, geography and capital structure.", "body"))
    story.append(_p("The downside case is not exhaustive. Litigation, dilution, accounting changes, disruption and geopolitical events may matter even if they are not captured by the numerical model.", "muted"))

    # 14 / Monitoring plan
    _heading(story, 20, "Catalysts & what to monitor", "A practical checklist for the next six months; no event dates are invented.")
    growth = number(info.get("revenueGrowth"))
    margin = number(info.get("operatingMargins"))
    rate = snapshot.macro.get("DGS10")
    unemp = snapshot.macro.get("UNRATE")
    watch_rows = [
        ["Next results / filing", "Date not established here", "Verify the actual release date; compare revenue, margins, cash flow and guidance."],
        ["Revenue growth", pct(growth, signed=True), "Check whether growth improves, decelerates or turns negative; investigate customer drivers."],
        ["Operating margin", pct(margin), "Look for pricing power or cost pressure and whether changes are recurring."],
        ["Cash and debt", f"Cash {compact(cash, financial_currency)}; debt {compact(debt, financial_currency)}", "Check maturities, cash generation, refinancing, dividends and dilution."],
        ["US 10-year yield", _macro_value(rate.value, rate.unit) if rate else "Unavailable", "Compare future yield changes with the rate and funding channels in section 12."],
        ["US unemployment", _macro_value(unemp.value, unemp.unit) if unemp else "Unavailable", "Watch for changing demand and credit conditions; check the issuer's actual customer mix."],
    ]
    if analysis.next_election and snapshot.price_date <= analysis.next_election <= six_month_date:
        watch_rows.append(["US general election", analysis.next_election.isoformat(), "Review the relevant policy channels and avoid assuming an election outcome or price reaction."])
    story.append(_table(["Watch item", "Current reference", "Why it matters"], watch_rows, [115, 150, 245], small=True))
    story.append(Spacer(1, 10))
    story.append(_p(f"Horizon: from the {snapshot.price_date} closing price to {six_month_date}. Refresh the source data after each material earnings release or macro surprise; this PDF is a point-in-time snapshot and does not update itself.", "body"))
    story.append(_note("Thresholds in the scorecard are model rules, not trading stops. The absence of an event date, customer name or risk in this report does not establish that none exists."))
    story.append(_p("Monitor analyst revisions, headline tone, short interest and options positioning as new observations arrive; see sections 8–10 for today's baselines and their limits.", "small"))

    # 20 / Scorecard
    _heading(story, 21, "Evidence scorecard", "Every contribution is visible. Missing data are excluded, not treated as neutral.")
    score_rows = []
    for factor in analysis.factors:
        score_rows.append([factor.label, pct(factor.weight), _short_factor_score(factor.score), text(_factor_evidence(snapshot, factor), 210)])
    story.append(_table(["Factor", "Weight", "Signal", "Evidence / rule"], score_rows, [115, 53, 53, 289], small=True))
    story.append(Spacer(1, 9))
    score_text = f"{analysis.score:+.3f}" if analysis.score is not None else "Not available"
    story.append(_note(f"Available weight: {analysis.coverage:.0%}. Normalized score: {score_text}. Sum each available factor's weight × signal, then divide by available weight. Signals range from -1 to +1. A partial score alone is not sufficient to issue a verdict."))
    story.append(Spacer(1, 8))
    story.append(_p("Verdict rules: bullish at +0.20 or above; bearish at -0.20 or below; otherwise mixed/neutral. The quality gates described in section 22 must also pass. These thresholds are explicit judgment calls, not proof of predictive accuracy.", "small"))

    # 16 / Reproducibility
    _heading(story, 22, "Model rules & limitations", "A reproducible heuristic, not a black-box price prediction.")
    rules = [
        ["Growth", "Revenue growth: ≥15%, ≥5%, ≥-5%, ≥-15%, otherwise map to +1, +0.5, 0, -0.5, -1."],
        ["Profitability", "Operating margin: ≥20%, ≥10%, ≥0%, ≥-10%, otherwise map to +1, +0.5, 0, -0.5, -1."],
        ["Balance sheet", "Use negative (debt minus cash) / market cap: ≥10%, ≥0%, ≥-30%, ≥-75%, otherwise map to +1 through -1. Same currency required; financial institutions excluded."],
        ["Valuation", "Forward P/E divided by the median for ≥3 provider-listed same-industry peers with positive P/E; ≤0.75, ≤1.0, ≤1.25, ≤1.75, otherwise map to +1 through -1. Real estate excluded."],
        ["Momentum", "Six-month adjusted-close return: ≥20%, ≥5%, ≥-5%, ≥-20%, otherwise map to +1 through -1. Provider adjustments can include distributions/splits."],
        ["Analysts", "At least three opinions; apply the growth tier pattern to 3 minus recommendation mean using thresholds 1, 0.5, -0.5, -1 (1 = strong buy; 5 = sell)."],
        ["Headline tone", "With ≥5 dated, issuer-matched headlines from the last 30 days, multiply mean VADER compound tone by 2, capped at ±1. General-language tone is a noisy, unverified sample—not overall investor sentiment."],
        ["Macro", "Directional sector assumptions applied to ~3-month changes; normalized by 0.5 pp yields, 0.4 pp unemployment, 0.8 pp CPI YoY, and 20% oil (where relevant). Cap each at ±1 and weight by exposure magnitude. At least two recent inputs."],
    ]
    story.append(_table(["Factor", "Calculation"], rules, [105, 405], small=True))
    story.append(Spacer(1, 8))
    story.append(_p("VADER finance-word lexicon overrides: beat/beats +1.4; upgrade/upgrades +1.6; downgrade/downgrades -1.6; miss/misses -1.2; bankruptcy -2.5; layoffs -1.7; surge +1.2; plunge -1.7.", "small"))
    story.append(_p("A verdict requires an equity, a close at most 14 calendar days old, ≥65% available weight, at least two of growth/profitability/balance/valuation, and a macro signal. Ranges also require 64 consecutive adjusted closes with usable realized volatility. Series over 90 days old are not scored. The drift multiplier and volatility range are judgmental and uncalibrated; see section 16.", "small"))
    exposures = EXPOSURES.get(sector)
    if exposures:
        story.append(_p(f"For the {sector} sector the assumed signed sensitivities are {exposures[0]:+.2f} for yields, {exposures[1]:+.2f} for unemployment and {exposures[2]:+.2f} for CPI. Upstream energy and airlines may additionally use oil at +1 or -1 respectively. These are assumptions, not measured correlations.", "small"))
    story.append(_p("Provider financial fields may be stale, incomplete, revised or based on differing periods. No filing, analyst recommendation, customer list, macro correlation or financial value is fabricated when missing.", "muted"))

    # 17 / Sources and limitations
    _heading(story, 23, "Sources & data gaps", "Source dates, audit trail and important boundaries for this point-in-time report.")
    story.append(_p(f"Retrieved: {as_of}. Price anchor: {snapshot.price_date}. Links below open the underlying source pages; data may have changed since retrieval.", "small"))
    if snapshot.demo:
        story.append(_p("[D] Synthetic local demo dataset. The company, people, elected officials, election outcomes, customer disclosures, prices, financial figures, analyst opinions, options, headlines, filing excerpts and macro data are entirely fictional; no external sources were queried.", "body"))
    else:
        ticker_url = quote(snapshot.ticker, safe="")
        sources = [
            ("Q", "Yahoo Finance company profile", f"https://finance.yahoo.com/quote/{ticker_url}/profile/"),
            ("Q", "Yahoo Finance quote and key statistics", f"https://finance.yahoo.com/quote/{ticker_url}/key-statistics/"),
            ("H", "Stooq daily prices (limited US-symbol fallback)" if snapshot.price_source == "Stooq" else "Yahoo Finance historical prices",
             f"https://stooq.com/q/?s={quote(snapshot.ticker.lower() + '.us', safe='')}" if snapshot.price_source == "Stooq" else f"https://finance.yahoo.com/quote/{ticker_url}/history/"),
            ("A", "Yahoo Finance analyst estimates and recommendations", f"https://finance.yahoo.com/quote/{ticker_url}/analysis/"),
            ("N", "Yahoo Finance ticker news; eligible individual headlines, if any, are linked in section 10", f"https://finance.yahoo.com/quote/{ticker_url}/news/"),
        ]
        sources.append(("R", "Yahoo Finance issuer profile / industry classification", f"https://finance.yahoo.com/quote/{ticker_url}/profile/"))
        if snapshot.peers:
            for peer in snapshot.peers.members:
                peer_url = quote(peer.ticker, safe="")
                sources.append(("R", f"Peer {peer.ticker}: provider key statistics / forward P/E", f"https://finance.yahoo.com/quote/{peer_url}/key-statistics/"))
        if snapshot.annuals:
            sources.append(("S", "Yahoo Finance annual income statements", f"https://finance.yahoo.com/quote/{ticker_url}/financials/"))
            sources.append(("S", "Yahoo Finance annual cash-flow statements", f"https://finance.yahoo.com/quote/{ticker_url}/cash-flow/"))
        if snapshot.benchmark_prices:
            sources.append(("B", "Yahoo Finance SPY adjusted historical prices", "https://finance.yahoo.com/quote/SPY/history/"))
        if snapshot.options:
            sources.append(("O", "Yahoo Finance options chain", f"https://finance.yahoo.com/quote/{ticker_url}/options/"))
        if snapshot.politics:
            sources.append(("P", "United States Congress Legislators: executive and congressional terms", snapshot.politics.source_url))
        sources.extend([
            ("E", "USA.gov presidential election calendar", "https://www.usa.gov/presidential-election-process"),
            ("E", "USA.gov congressional and midterm elections", "https://www.usa.gov/midterm-elections"),
            ("V", "VADER sentiment methodology and thresholds", "https://github.com/cjhutto/vaderSentiment"),
        ])
        if snapshot.filing:
            sources.append(("F", f"SEC {snapshot.filing.form}, filed {snapshot.filing.filing_date}", snapshot.filing.url))
        for code, label, _unit, _kind, source_id in SERIES:
            point = snapshot.macro.get(code)
            observed = f"observed {point.as_of}" if point else "no usable observation retrieved"
            url = point.source_url if point else f"https://fred.stlouisfed.org/series/{code}"
            sources.append((source_id, f"FRED {code}: {label}, {observed}", url))
        for source_id, label, url in sources:
            story.append(_rich(f"<b>[{_esc(source_id)}]</b> {_source_link(label, url)}", "small"))
    story.append(_p("Known data gaps & cautions", "section"))
    for limitation in analysis.limitations[:5]:
        story.append(_p("• " + text(limitation, 245), "small"))
    if len(analysis.limitations) > 5:
        story.append(_p(f"{len(analysis.limitations) - 5} additional data-quality notices are available in the application/CLI output. Review missing fields throughout this report.", "muted"))
    story.append(_p("Financial data are provided on a best-effort basis and may be delayed or incorrect. This document is general research, not personalized financial advice, and does not consider your objectives, portfolio, tax situation or risk tolerance. Prices can fall and losses can be substantial.", "small"))

    doc.build(story, onFirstPage=lambda canvas, document: _page(canvas, document, snapshot),
              onLaterPages=lambda canvas, document: _page(canvas, document, snapshot))
    if not 10 <= doc.page <= 30:
        output.unlink(missing_ok=True)
        raise RuntimeError(f"The report did not fit the supported 10–30 page range ({doc.page} pages).")
    return doc.page


def _sector_channel_for_report(sector: str) -> str:
    return SECTOR_CHANNELS.get(sector, "customer demand, costs and financing")
