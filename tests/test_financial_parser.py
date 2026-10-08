"""Kandidaten aus drei synthetischen Statements; keine externen Geschäftsberichte."""

from dataclasses import replace
from datetime import date

import pytest

from pdf_samples import make_financial_pdf
from research_update_assistant.document_models import ExtractedDocument, ExtractedPage, ExtractedTable, ExtractedWord
from research_update_assistant.financial_parser import detect_currency_scale, extract_financial_metric_candidates
from research_update_assistant.metric_mapping import load_metric_config
from research_update_assistant.pdf_extractor import extract_pdf_document


def extract(*, ruled=False, split_values=False, reverse_years=False, include_capex=True):
    document = extract_pdf_document(make_financial_pdf(ruled=ruled, split_values=split_values, reverse_years=reverse_years, include_capex=include_capex), file_name="synthetic-financial.pdf")
    return document, extract_financial_metric_candidates(document, load_metric_config())


def values(candidate):
    return {item.period_label: item.normalized_value for item in candidate.values}


@pytest.mark.parametrize("ruled", [False, True])
def test_all_three_primary_statements_correct_values_and_provenance(ruled):
    document, candidates = extract(ruled=ruled)
    best = {candidate.canonical_metric: candidate for candidate in candidates}
    expected = {
        "revenue": (1100, 1000, 1), "ebitda": (210, 200, 1), "ebit": (143, 150, 1),
        "adjusted_ebit": (148, 155, 1), "net_income": (92, 100, 1),
        "cash": (90, 100, 2), "gross_debt": (360, 300, 2), "inventory": (190, 150, 2),
        "receivables": (150, 120, 2), "payables": (110, 100, 2),
        "total_assets": (1000, 900, 2), "equity": (550, 500, 2),
        "operating_cash_flow": (140, 160, 3), "capex": (-80, -60, 3),
        "reported_free_cash_flow": (60, 95, 3),
    }
    assert set(best) == set(expected)
    assert len(candidates) == len(expected)  # Table/layout duplicates grouped.
    for metric, (current, previous, page_number) in expected.items():
        candidate = best[metric]
        assert values(candidate) == {"FY2025": current, "FY2024": previous}
        assert candidate.page_number == page_number
        assert candidate.source_document == "synthetic-financial.pdf"
        assert candidate.reported_label
        assert candidate.source_snippet
        assert candidate.currency == "CHF"
        assert candidate.scale == "million"
        assert candidate.confidence == "high"
        assert all(item.period_months == 12 for item in candidate.values)
        assert all(item.period_end == date(int(item.period_label[-4:]), 12, 31) for item in candidate.values)
        assert candidate.bbox is not None
        assert candidate.source_priority == 1
    if ruled:
        assert document.total_tables == 3
        assert all(candidate.extraction_method == "pdfplumber_table" for candidate in candidates)
    else:
        assert document.total_tables == 0
        assert all(candidate.extraction_method == "pymupdf_layout" for candidate in candidates)
        assert all(item.bbox is not None for candidate in candidates for item in candidate.values)


def test_critical_swiss_cashflow_ebitda_definition_and_true_operating_cash_flow():
    _, candidates = extract()
    ebitda = next(item for item in candidates if item.canonical_metric == "ebitda")
    ocf = next(item for item in candidates if item.canonical_metric == "operating_cash_flow")
    assert ebitda.reported_label == "Operativer Cashflow (EBITDA) 4"
    assert ebitda.normalized_label == "operativer cashflow ebitda"
    assert values(ebitda)["FY2025"] == 210
    assert ocf.reported_label == "Nettomittelfluss aus/für (-) Geschäftstätigkeit 3"
    assert ocf.normalized_label == "nettomittelfluss aus für geschäftstätigkeit"
    assert values(ocf)["FY2025"] == 140


def test_layout_values_below_labels_are_reconstructed():
    document, candidates = extract(split_values=True)
    assert document.total_tables == 0
    revenue = next(item for item in candidates if item.canonical_metric == "revenue")
    assert revenue.reported_label == "Nettoumsatz 3"
    assert revenue.normalized_label == "nettoumsatz"
    assert values(revenue) == {"FY2025": 1100, "FY2024": 1000}
    assert revenue.confidence == "medium"
    assert "\n" in revenue.source_snippet
    assert {item.canonical_metric for item in candidates} >= {"revenue", "ebit", "inventory", "operating_cash_flow", "capex"}


@pytest.mark.parametrize("ruled", [False, True])
def test_periods_follow_column_positions_not_assumed_current_left(ruled):
    _, candidates = extract(ruled=ruled, reverse_years=True)
    revenue = next(item for item in candidates if item.canonical_metric == "revenue")
    assert [(item.period_label, item.normalized_value) for item in revenue.values] == [("FY2024", 1000), ("FY2025", 1100)]


def test_missing_capex_does_not_invent_candidate():
    _, candidates = extract(include_capex=False)
    assert "capex" not in [item.canonical_metric for item in candidates]


def test_generic_and_diluted_eps_in_same_table_stay_separate_with_original_labels():
    text = (
        "Konzernerfolgsrechnung\nCHF Mio\n2025 2024\n"
        "Nettoumsatz 1100 1000\nEBIT 143 150\nNettoergebnis 92 100\n"
        "Ergebnis je Aktie 4.10 4.25\nVerwässertes Ergebnis je Aktie 4.05 4.20"
    )
    table = ExtractedTable(1, 1, (
        ("Bezeichnung", "2025", "2024"),
        ("Nettoumsatz", "1100", "1000"),
        ("EBIT", "143", "150"),
        ("Nettoergebnis", "92", "100"),
        ("Ergebnis je Aktie", "4.10", "4.25"),
        ("Verwässertes Ergebnis je Aktie", "4.05", "4.20"),
    ))
    candidates = extract_financial_metric_candidates(
        page_document(ExtractedPage(1, text, tables=(table,))), load_metric_config(),
    )
    basic = next(item for item in candidates if item.canonical_metric == "basic_eps")
    diluted = next(item for item in candidates if item.canonical_metric == "diluted_eps")
    assert basic.reported_label == "Ergebnis je Aktie"
    assert diluted.reported_label == "Verwässertes Ergebnis je Aktie"
    assert values(basic) == {"FY2025": 4.10, "FY2024": 4.25}
    assert values(diluted) == {"FY2025": 4.05, "FY2024": 4.20}
    assert basic.scale == diluted.scale == "unit"


@pytest.mark.parametrize("text,currency,scale", [
    ("CHF Mio.", "CHF", "million"), ("in Mio. CHF", "CHF", "million"),
    ("MCHF", "CHF", "million"), ("CHF Millionen", "CHF", "million"),
    ("EUR Mio.", "EUR", "million"), ("MEUR", "EUR", "million"),
    ("USD Mio.", "USD", "million"), ("MUSD", "USD", "million"),
    ("CHF Tausend", "CHF", "thousand"), ("TCHF", "CHF", "thousand"),
    ("CHF '000", "CHF", "thousand"), ("CHF Milliarden", "CHF", "billion"),
    ("CHF Einheiten", "CHF", "unit"), ("CHF", "CHF", None),
    ("in Mio CHF\nNettoumsatz 1’000", "CHF", "million"),
    ("in Mio CHF und Mio EUR", None, "million"),
    ("in CHF Millionen und Tausend", "CHF", None), ("1'000", None, None),
])
def test_explicit_unit_detection(text, currency, scale):
    assert detect_currency_scale(text) == (currency, scale)


def word(text, x, y, width=30):
    return ExtractedWord(text, x, y, x + width, y + 10, 0, 0, 0)


def page_document(page):
    return ExtractedDocument("synthetic.pdf", 1, (page,), "good")


def test_missing_year_headers_keep_unknown_period_and_low_confidence():
    page = ExtractedPage(1, "Konzern-Erfolgsrechnung\nin Mio CHF\nNettoumsatz 1100 1000\nEBIT 143 150", words=(
        word("Konzern-Erfolgsrechnung", 30, 10, 200), word("CHF", 30, 35), word("Mio.", 70, 35),
        word("Nettoumsatz", 30, 70, 100), word("1100", 400, 70), word("1000", 520, 70),
        word("EBIT", 30, 100), word("143", 400, 100), word("150", 520, 100),
    ))
    candidates = extract_financial_metric_candidates(page_document(page), load_metric_config())
    assert {item.canonical_metric for item in candidates} == {"revenue", "ebit"}
    assert all(item.confidence == "low" for item in candidates)
    assert all(value.period_label is None for item in candidates for value in item.values)
    assert all(value.period_end is None for item in candidates for value in item.values)


def test_text_fallback_has_no_guessed_years():
    page = ExtractedPage(1, "Konzern-Erfolgsrechnung\nin Mio. CHF\n2025 2024\nNettoumsatz\n1100 1000\nEBIT\n143 150")
    candidates = extract_financial_metric_candidates(page_document(page), load_metric_config())
    assert {item.canonical_metric for item in candidates} == {"revenue", "ebit"}
    assert all(item.extraction_method == "text_fallback" for item in candidates)
    assert all(item.confidence == "low" for item in candidates)
    assert all(value.period_label is None for item in candidates for value in item.values)


def test_segment_lower_priority_and_differing_values_retained():
    document, _ = extract()
    primary = document.pages[0]
    highlights = ExtractedPage(4, "Highlights\nin Mio CHF\n2025 2024\nNettoumsatz 1110 1000\nEBIT 143 150", words=(
        word("Highlights", 30, 10, 100), word("CHF", 30, 35), word("Mio", 70, 35),
        word("2025", 400, 60), word("2024", 520, 60),
        word("Nettoumsatz", 30, 85, 100), word("1110", 400, 85), word("1000", 520, 85),
        word("EBIT", 30, 115), word("143", 400, 115), word("150", 520, 115),
    ))
    segment = ExtractedPage(5, "Segmentbericht\nin Mio CHF\n2025 2024\nNettoumsatz Europa 500 400", words=(
        word("Segmentbericht", 30, 10, 120), word("CHF", 30, 35), word("Mio", 70, 35),
        word("2025", 400, 60), word("2024", 520, 60),
        word("Nettoumsatz", 30, 85, 100), word("Europa", 135, 85, 40), word("500", 400, 85), word("400", 520, 85),
    ))
    candidates = extract_financial_metric_candidates(replace(document, pages=(primary, highlights, segment)), load_metric_config())
    revenue = [item for item in candidates if item.canonical_metric == "revenue"]
    assert len(revenue) == 3
    assert revenue[0].page_number == 1
    assert {values(item)["FY2025"] for item in revenue} == {1100, 1110, 500}
    assert revenue[-1].is_segment
    assert revenue[-1].confidence == "low"
    assert revenue[-1].source_priority == 7


def test_deduplication_keeps_differing_same_page_values():
    document, _ = extract(ruled=True)
    page = document.pages[0]
    table = page.tables[0]
    changed_rows = tuple(tuple("1’101" if cell == "1’100" else cell for cell in row) for row in table.rows)
    altered = replace(table, table_index=2, rows=changed_rows)
    page = replace(page, tables=page.tables + (altered,))
    candidates = extract_financial_metric_candidates(replace(document, pages=(page,)), load_metric_config())
    revenue = [item for item in candidates if item.canonical_metric == "revenue"]
    assert len(revenue) == 2
    assert {values(item)["FY2025"] for item in revenue} == {1100, 1101}


def test_candidate_ids_stable_and_financial_models_never_created():
    document, first = extract()
    second = extract_financial_metric_candidates(document, load_metric_config())
    assert first == second
    assert len({item.candidate_id for item in first}) == len(first)


def test_h1_context_bare_year_headers_and_balance_dates_match():
    document, _ = extract()
    pages = []
    for page in document.pages:
        text = "Halbjahresbericht\n" + page.text
        if page.page_number == 2:
            words = tuple(replace(word, text=word.text.replace("31.12.", "30.06.")) for word in page.words)
            text = text.replace("31.12.", "30.06.")
        else:
            words = page.words
        pages.append(replace(page, text=text, words=words))
    candidates = extract_financial_metric_candidates(replace(document, pages=tuple(pages)), load_metric_config())
    assert candidates
    assert all(value.period_label in ("H1 2025", "H1 2024") for candidate in candidates for value in candidate.values)
    assert all(value.period_months == 6 for candidate in candidates for value in candidate.values)
    assert all(value.period_end.month == 6 for candidate in candidates for value in candidate.values)


def test_line_wrapped_label_is_joined_before_mapping():
    page = ExtractedPage(1, "Konzernbilanz\nCHF Mio\n2025 2024\nForderungen aus Lieferungen und\nLeistungen 150 120\nVorräte 190 150", words=(
        word("Konzernbilanz", 30, 10, 130), word("CHF", 30, 35), word("Mio", 70, 35),
        word("2025", 400, 60), word("2024", 520, 60),
        word("Forderungen", 30, 85, 70), word("aus", 105, 85, 20), word("Lieferungen", 130, 85, 60), word("und", 195, 85, 20),
        word("Leistungen", 30, 99, 60), word("150", 400, 99), word("120", 520, 99),
        word("Vorräte", 30, 130, 50), word("190", 400, 130), word("150", 520, 130),
    ))
    candidates = extract_financial_metric_candidates(page_document(page), load_metric_config())
    receivables = next(item for item in candidates if item.canonical_metric == "receivables")
    assert receivables.reported_label == "Forderungen aus Lieferungen und Leistungen"
    assert values(receivables) == {"FY2025": 150, "FY2024": 120}


def test_words_extraction_has_original_positions_and_block_identifiers():
    document = extract_pdf_document(make_financial_pdf())
    assert all(page.words for page in document.pages)
    first = document.pages[0].words[0]
    assert first.text == "Konzern-Erfolgsrechnung"
    assert 0 <= first.x0 < first.x1 <= 650
    assert 0 <= first.y0 < first.y1 <= 840
    assert isinstance(first.block_number, int)
    assert isinstance(first.line_number, int)
    assert isinstance(first.word_number, int)


def test_words_failure_preserves_phase5a_text_and_tables(monkeypatch):
    import pymupdf

    original = pymupdf.Page.get_text

    def fail_words(self, option="text", *args, **kwargs):
        if option == "words":
            raise RuntimeError("synthetic word extraction failure")
        return original(self, option, *args, **kwargs)

    monkeypatch.setattr(pymupdf.Page, "get_text", fail_words)
    document = extract_pdf_document(make_financial_pdf(ruled=True))
    assert all(page.words == () for page in document.pages)
    assert all(page.has_text for page in document.pages)
    assert document.total_tables == 3
    assert any("Wortpositionen" in warning for warning in document.extraction_warnings)
    candidates = extract_financial_metric_candidates(document, load_metric_config())
    assert len(candidates) == 15
    assert all(item.extraction_method == "pdfplumber_table" for item in candidates)


def test_extract_candidates_never_constructs_financial_period(monkeypatch):
    from research_update_assistant.models import FinancialPeriod

    def forbidden(*args, **kwargs):
        raise AssertionError("Unbestätigte Kandidaten dürfen keine Perioden erzeugen.")

    monkeypatch.setattr(FinancialPeriod, "__post_init__", forbidden)
    _, candidates = extract()
    assert len(candidates) == 15


def test_segment_page_generic_label_is_also_segment_candidate():
    document, _ = extract()
    income = document.pages[0]
    segment = replace(income, page_number=4, text="Segmentbericht\n" + income.text,
                      words=(word("Segmentbericht", 30, 1, 120),) + income.words)
    candidates = extract_financial_metric_candidates(replace(document, pages=(income, segment)), load_metric_config())
    generic_revenue = [item for item in candidates if item.canonical_metric == "revenue"]
    assert len(generic_revenue) == 2
    assert generic_revenue[0].is_segment is False
    assert generic_revenue[1].reported_label == "Nettoumsatz 3"
    assert generic_revenue[1].normalized_label == "nettoumsatz"
    assert generic_revenue[1].is_segment is True
    assert generic_revenue[1].confidence == "low"
    assert generic_revenue[1].source_priority == 7


def test_text_fallback_inline_ebit_uses_own_values_not_next_metric():
    page = ExtractedPage(1, "Konzern-Erfolgsrechnung\nCHF Mio.\n2025 2024\nEBIT  143  150\nReingewinn  92  100")
    candidates = extract_financial_metric_candidates(page_document(page), load_metric_config())
    ebit = next(item for item in candidates if item.canonical_metric == "ebit")
    net_income = next(item for item in candidates if item.canonical_metric == "net_income")
    assert [item.normalized_value for item in ebit.values] == [143, 150]
    assert [item.normalized_value for item in net_income.values] == [92, 100]
    assert ebit.reported_label == "EBIT"


def test_local_unit_conflict_does_not_silently_inherit_header_unit():
    from research_update_assistant.financial_parser import _local_unit, _nearby_unit
    from research_update_assistant.layout_parser import LayoutRow

    assert _local_unit("CHF Millionen und Tausend", ("CHF", "million")) == ("CHF", None)
    assert _local_unit("CHF und EUR Mio.", ("CHF", "million")) == (None, "million")
    assert _local_unit("CHF", ("CHF", "million")) == ("CHF", "million")
    rows = (LayoutRow((word("CHF", 30, 10), word("Mio.", 70, 10))),
            LayoutRow((word("CHF", 30, 35), word("Millionen", 70, 35, 70), word("und", 145, 35), word("Tausend", 180, 35, 70))))
    assert _nearby_unit(rows, 1, ("CHF", "million")) == ("CHF", None)


def test_conflicting_table_unit_stays_unknown():
    table = ExtractedTable(1, 1, (("CHF Millionen und Tausend", None, None),
                                 ("Bezeichnung", "2025", "2024"),
                                 ("Nettoumsatz", "1100", "1000"),
                                 ("EBIT", "143", "150")))
    page = ExtractedPage(1, "Konzern-Erfolgsrechnung\nin Mio CHF\n2025 2024\nNettoumsatz 1100 1000\nEBIT 143 150", tables=(table,))
    candidates = extract_financial_metric_candidates(page_document(page), load_metric_config())
    assert candidates
    assert all(item.currency == "CHF" for item in candidates)
    assert all(item.scale is None for item in candidates)
    assert all(item.confidence != "high" for item in candidates)


def test_old_header_before_statement_title_cannot_assign_new_rows():
    page = ExtractedPage(1, "2023 2022\nKonzern-Erfolgsrechnung\nCHF Mio\nNettoumsatz 1100 1000\nEBIT 143 150\nReingewinn 92 100", words=(
        word("2023", 400, 10), word("2022", 520, 10),
        word("Konzern-Erfolgsrechnung", 30, 35, 200), word("CHF", 30, 60), word("Mio", 70, 60),
        word("Nettoumsatz", 30, 90, 100), word("1100", 400, 90), word("1000", 520, 90),
        word("EBIT", 30, 120), word("143", 400, 120), word("150", 520, 120),
        word("Reingewinn", 30, 150, 100), word("92", 400, 150), word("100", 520, 150),
    ))
    candidates = extract_financial_metric_candidates(page_document(page), load_metric_config())
    assert len(candidates) == 3
    assert all(value.period_label is None for item in candidates for value in item.values)
    assert all(item.confidence == "low" for item in candidates)


def test_text_fallback_ambiguous_spaces_keep_raw_text_without_fake_number():
    page = ExtractedPage(1, "Konzern-Erfolgsrechnung\nCHF Mio.\n2025 2024\nEBIT\n143 150")
    candidates = extract_financial_metric_candidates(page_document(page), load_metric_config())
    ebit = next(item for item in candidates if item.canonical_metric == "ebit")
    assert ebit.values[0].raw_value == "143 150"
    assert ebit.values[0].normalized_value is None
    assert any("Tausendergruppen" in reason for reason in ebit.confidence_reasons)


def test_explicit_fy_header_is_not_changed_by_half_year_report_title():
    from research_update_assistant.financial_parser import _period_with_context

    assert _period_with_context("FY2025", ("FY2025", date(2025, 12, 31), 12), True) == ("FY2025", date(2025, 12, 31), 12)


def test_unit_header_remains_active_after_more_than_twelve_rows():
    from research_update_assistant.financial_parser import _nearby_unit
    from research_update_assistant.layout_parser import LayoutRow

    rows = (LayoutRow((word("CHF", 30, 10), word("Tausend", 70, 10, 70))),) + tuple(
        LayoutRow((word(f"Zeile{index}", 30, 30 + index * 15, 70),)) for index in range(20)
    )
    assert _nearby_unit(rows, len(rows) - 1, ("CHF", "million")) == ("CHF", "thousand")


@pytest.mark.parametrize("table_channel", [False, True])
def test_sectioned_current_and_noncurrent_debt_are_components_not_total_gross_debt(table_channel):
    text = "Konzernbilanz\nCHF Mio\n2025 2024\nKurzfristige Verbindlichkeiten\nFinanzverbindlichkeiten 40 30\nLangfristige Verbindlichkeiten\nFinanzverbindlichkeiten 320 270\nVorräte 190 150\nEigenkapital 550 500"
    words = (
        word("Konzernbilanz", 30, 10, 130), word("CHF", 30, 35), word("Mio", 70, 35),
        word("2025", 400, 60), word("2024", 520, 60),
        word("Kurzfristige", 30, 85, 70), word("Verbindlichkeiten", 105, 85, 100),
        word("Finanzverbindlichkeiten", 30, 110, 150), word("40", 400, 110), word("30", 520, 110),
        word("Langfristige", 30, 135, 70), word("Verbindlichkeiten", 105, 135, 100),
        word("Finanzverbindlichkeiten", 30, 160, 150), word("320", 400, 160), word("270", 520, 160),
        word("Vorräte", 30, 185, 50), word("190", 400, 185), word("150", 520, 185),
        word("Eigenkapital", 30, 210, 80), word("550", 400, 210), word("500", 520, 210),
    )
    table = ExtractedTable(1, 1, (("Bezeichnung", "2025", "2024"),
                                 ("Kurzfristige Verbindlichkeiten", None, None),
                                 ("Finanzverbindlichkeiten", "40", "30"),
                                 ("Langfristige Verbindlichkeiten", None, None),
                                 ("Finanzverbindlichkeiten", "320", "270"),
                                 ("Vorräte", "190", "150"), ("Eigenkapital", "550", "500")))
    page = ExtractedPage(1, text, tables=(table,) if table_channel else (), words=() if table_channel else words)
    candidates = extract_financial_metric_candidates(page_document(page), load_metric_config())
    by_metric = {item.canonical_metric: item for item in candidates}
    assert "gross_debt" not in by_metric
    assert set(by_metric) == {
        "current_financial_debt", "noncurrent_financial_debt", "inventory", "equity",
    }
    assert values(by_metric["current_financial_debt"]) == {"FY2025": 40, "FY2024": 30}
    assert values(by_metric["noncurrent_financial_debt"]) == {"FY2025": 320, "FY2024": 270}


@pytest.mark.parametrize("table_channel", [False, True])
def test_explicit_current_and_noncurrent_financial_debt_are_separate_candidates(table_channel):
    text = (
        "Konzernbilanz\nCHF Mio\n2025 2024\n"
        "Kurzfristige Finanzverbindlichkeiten 40 30\n"
        "Langfristige Finanzverbindlichkeiten 320 270\n"
        "Vorräte 190 150\nEigenkapital 550 500"
    )
    words = (
        word("Konzernbilanz", 30, 10, 130), word("CHF", 30, 35), word("Mio", 70, 35),
        word("2025", 400, 60), word("2024", 520, 60),
        word("Kurzfristige", 30, 85, 75), word("Finanzverbindlichkeiten", 110, 85, 150),
        word("40", 400, 85), word("30", 520, 85),
        word("Langfristige", 30, 110, 75), word("Finanzverbindlichkeiten", 110, 110, 150),
        word("320", 400, 110), word("270", 520, 110),
        word("Vorräte", 30, 135, 50), word("190", 400, 135), word("150", 520, 135),
        word("Eigenkapital", 30, 160, 80), word("550", 400, 160), word("500", 520, 160),
    )
    table = ExtractedTable(1, 1, (
        ("Bezeichnung", "2025", "2024"),
        ("Kurzfristige Finanzverbindlichkeiten", "40", "30"),
        ("Langfristige Finanzverbindlichkeiten", "320", "270"),
        ("Vorräte", "190", "150"), ("Eigenkapital", "550", "500"),
    ))
    page = ExtractedPage(
        1, text, tables=(table,) if table_channel else (),
        words=() if table_channel else words,
    )
    candidates = extract_financial_metric_candidates(page_document(page), load_metric_config())
    by_metric = {item.canonical_metric: item for item in candidates}
    assert values(by_metric["current_financial_debt"]) == {"FY2025": 40, "FY2024": 30}
    assert values(by_metric["noncurrent_financial_debt"]) == {"FY2025": 320, "FY2024": 270}
    assert "gross_debt" not in by_metric


@pytest.mark.parametrize("ruled", [False, True])
def test_quarter_report_bare_year_headers_are_not_annualized(ruled):
    document = extract_pdf_document(make_financial_pdf(ruled=ruled))
    income = document.pages[0]
    document = replace(document, pages=(replace(income, text="Q3 Quartalsbericht\n" + income.text),))
    candidates = extract_financial_metric_candidates(document, load_metric_config())
    assert candidates
    assert all(value.period_label is None for item in candidates for value in item.values)
    assert all(value.period_months is None for item in candidates for value in item.values)
    assert all(item.confidence == "low" for item in candidates)


def test_different_unparsed_raw_values_remain_source_alternatives():
    """Mehrdeutige Rohwerte dürfen durch None nicht zu einem Duplikat werden."""
    document = ExtractedDocument("synthetic.pdf", 0, (
        ExtractedPage(1, "Highlights\nCHF Mio.\nEBIT 143 150\nEBIT 145 155"),
    ), "good")
    candidates = extract_financial_metric_candidates(document, load_metric_config())
    assert len(candidates) == 2
    assert {c.values[0].raw_value for c in candidates} == {"143 150", "145 155"}
    assert all(c.values[0].normalized_value is None for c in candidates)
