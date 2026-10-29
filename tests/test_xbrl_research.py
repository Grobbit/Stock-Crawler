from datetime import date

from stock_crawler.sources.xbrl import extract_revenue_breakdowns


def context(identifier, member="", axis="srt:ProductOrServiceAxis", entity="123", start="2024-01-01", end="2024-12-31", extra=""):
    dimension = f'<xbrldi:explicitMember dimension="{axis}">{member}</xbrldi:explicitMember>' if member else ""
    return (f'<xbrli:context id="{identifier}"><xbrli:entity><xbrli:identifier>{entity}</xbrli:identifier>'
            f'<xbrli:segment>{dimension}{extra}</xbrli:segment></xbrli:entity>'
            f'<xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate>'
            '</xbrli:period></xbrli:context>')


def fact(context_id, value, *, unit="usd", scale="6", name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", extra=""):
    return (f'<ix:nonFraction name="{name}" contextRef="{context_id}" unitRef="{unit}" scale="{scale}" '
            f'format="ixt:num-dot-decimal" {extra}>{value}</ix:nonFraction>')


def document(contexts, facts):
    return ('<html><ix:header>' + ''.join(contexts) + '<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
            '<xbrli:unit id="shares"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>'
            '</ix:header><body>' + ''.join(facts) + '</body></html>').encode()


def test_reconciles_detailed_mix_avoiding_overlapping_product_subtotal():
    contexts = [context("total"), context("products", "us-gaap:ProductMember"),
                context("phone", "test:IPhoneMember"), context("tablet", "test:TabletMember"),
                context("service", "us-gaap:ServiceMember")]
    facts = [fact("total", "1,000"), fact("products", "800"), fact("phone", "500"),
             fact("tablet", "300"), fact("service", "200")]
    groups = extract_revenue_breakdowns(document(contexts, facts), date(2024, 12, 31), 123)
    assert len(groups) == 1 and groups[0].currency == "USD"
    assert groups[0].total == 1_000_000_000
    assert [(item.label, item.value) for item in groups[0].components] == [
        ("iPhone", 500_000_000), ("Tablet", 300_000_000), ("Service", 200_000_000)]


def test_matched_reconciled_prior_period_adds_business_line_growth():
    contexts = [context("total"), context("a", "test:AlphaMember"), context("b", "test:BetaMember"),
                context("prior_total", start="2023-01-01", end="2023-12-31"),
                context("prior_a", "test:AlphaMember", start="2023-01-01", end="2023-12-31"),
                context("prior_b", "test:BetaMember", start="2023-01-01", end="2023-12-31")]
    facts = [fact("total", "1000"), fact("a", "600"), fact("b", "400"),
             fact("prior_total", "800"), fact("prior_a", "500"), fact("prior_b", "300")]
    group = extract_revenue_breakdowns(document(contexts, facts), date(2024, 12, 31), 123)[0]
    assert group.prior_end == date(2023, 12, 31) and group.prior_total == 800_000_000
    assert [x.prior_value for x in group.components] == [500_000_000, 300_000_000]
    # Conflicting prior values must not erase the current-year mix or guess growth.
    group = extract_revenue_breakdowns(document(contexts, facts + [fact("prior_a", "501")]), date(2024, 12, 31), 123)[0]
    assert group.prior_end is None and all(x.prior_value is None for x in group.components)


def test_prior_mix_is_withheld_when_categories_or_durations_change():
    contexts = [context("total"), context("a", "test:AlphaMember"), context("b", "test:BetaMember"),
                context("prior_total", start="2023-01-01", end="2023-12-31"),
                context("prior_a", "test:AlphaMember", start="2023-01-01", end="2023-12-31"),
                context("prior_c", "test:DifferentMember", start="2023-01-01", end="2023-12-31")]
    facts = [fact("total", "1000"), fact("a", "600"), fact("b", "400"),
             fact("prior_total", "800"), fact("prior_a", "500"), fact("prior_c", "300")]
    group = extract_revenue_breakdowns(document(contexts, facts), date(2024, 12, 31), 123)[0]
    assert group.prior_end is None and all(x.prior_value is None for x in group.components)


def test_withholds_mix_if_same_size_subsets_are_ambiguous():
    contexts = [context("total")] + [context(str(i), f"test:Business{i}Member") for i in range(4)]
    facts = [fact("total", "1,000")] + [fact(str(i), str(value)) for i, value in enumerate([600, 400, 700, 300])]
    assert extract_revenue_breakdowns(document(contexts, facts), date(2024, 12, 31), 123) == ()


def test_rejects_conflicts_negative_values_wrong_entity_units_and_period():
    contexts = [context("total"), context("a", "test:AlphaMember"), context("b", "test:BetaMember")]
    base = [fact("total", "1000"), fact("a", "600"), fact("b", "400")]
    assert extract_revenue_breakdowns(document(contexts, base + [fact("a", "601")]), date(2024, 12, 31), 123) == ()
    assert extract_revenue_breakdowns(document(contexts, base[:2] + [fact("b", "400", extra='sign="-"')]), date(2024, 12, 31), 123) == ()
    assert extract_revenue_breakdowns(document(contexts, base), date(2023, 12, 31), 123) == ()
    assert extract_revenue_breakdowns(document(contexts, base), date(2024, 12, 31), 999) == ()
    assert extract_revenue_breakdowns(document(contexts, [fact("total", "1000", unit="shares"), *base[1:]]), date(2024, 12, 31), 123) == ()


def test_rejects_extra_dimensions_and_different_concepts():
    extra = '<xbrldi:explicitMember dimension="test:CustomerAxis">test:BigCustomerMember</xbrldi:explicitMember>'
    contexts = [context("total"), context("a", "test:AlphaMember", extra=extra), context("b", "test:BetaMember")]
    facts = [fact("total", "1000"), fact("a", "600"), fact("b", "400")]
    assert extract_revenue_breakdowns(document(contexts, facts), date(2024, 12, 31), 123) == ()
    contexts = [context("total"), context("a", "test:AlphaMember"), context("b", "test:BetaMember")]
    facts[2] = fact("b", "400", name="us-gaap:Revenues")
    assert extract_revenue_breakdowns(document(contexts, facts), date(2024, 12, 31), 123) == ()
