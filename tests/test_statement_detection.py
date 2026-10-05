"""Statement-Seiten benötigen nachvollziehbare Titel-, Kennzahl- und Zahlsignale."""

import pytest

from research_update_assistant.document_models import (
    ExtractedDocument, ExtractedPage, ExtractedTable, ExtractedWord,
)
from research_update_assistant.metric_mapping import load_metric_config
from research_update_assistant.statement_detection import (
    detect_statement_pages, source_priority, statement_type_for_heading,
)


def _document(*pages):
    return ExtractedDocument("synthetic.pdf", 100, tuple(pages), "good")


def _income_text(title="Konzern-Erfolgsrechnung"):
    return title + "\nin Mio. CHF\n2025 2024\nNettoumsatz 1'100 1'000\nBetriebsergebnis (EBIT) 143 150\nNettoergebnis 92 100"


@pytest.mark.parametrize("title", ["Erfolgsrechnung", "Konzern-Erfolgsrechnung", "Konsolidierte Erfolgsrechnung", "Gewinn- und Verlustrechnung", "Konzernerfolgsrechnung", "Income Statement", "Statement of Income", "Consolidated Income Statement"])
def test_income_statement_heading_and_multiple_signals_are_high(title):
    page, = detect_statement_pages(_document(ExtractedPage(7, _income_text(title))), load_metric_config())
    assert page.page_number == 7
    assert page.statement_type == "income_statement"
    assert page.confidence == "high"
    assert page.primary_statement
    assert page.source_priority == 1
    assert len(page.reasons) >= 4


@pytest.mark.parametrize("title", ["Bilanz", "Konzernbilanz", "Konsolidierte Bilanz", "Bilanz des Konzerns", "Balance Sheet", "Statement of Financial Position"])
def test_balance_sheet_heading_and_metrics_are_detected(title):
    text = title + "\nCHF Mio.\n31.12.2025 31.12.2024\nFlüssige Mittel 90 100\nVorräte 190 150\nEigenkapital 600 590"
    page, = detect_statement_pages(_document(ExtractedPage(2, text)), load_metric_config())
    assert page.statement_type == "balance_sheet"
    assert page.primary_statement
    assert page.confidence == "high"


@pytest.mark.parametrize("title", ["Geldflussrechnung", "Konzern-Geldflussrechnung", "Konsolidierte Geldflussrechnung", "Kapitalflussrechnung", "Cashflow-Rechnung", "Cash Flow Statement", "Statement of Cash Flows"])
def test_cash_flow_heading_and_metrics_are_detected(title):
    text = title + "\nCHF Mio.\n2025 2024\nGeldfluss aus Geschäftstätigkeit 140 160\nInvestitionen -80 -60\nFree Cashflow 60 100"
    page, = detect_statement_pages(_document(ExtractedPage(3, text)), load_metric_config())
    assert page.statement_type == "cash_flow"
    assert page.primary_statement
    assert page.confidence == "high"


def test_typical_metrics_years_and_numbers_can_identify_statement_without_heading():
    text = _income_text("Finanzinformationen")
    page, = detect_statement_pages(_document(ExtractedPage(1, text)), load_metric_config())
    assert page.statement_type == "income_statement"
    assert page.primary_statement
    assert page.confidence == "medium"
    assert not any("Überschrift" in reason for reason in page.reasons)


@pytest.mark.parametrize("context,priority", [
    ("Anhang", 2), ("Notes to the financial statements", 2),
    ("Alternative Performance Measures", 4), ("APM", 4),
    ("Highlights", 5), ("Kennzahlen im Überblick", 5),
    ("Segmentberichterstattung", 7), ("Segment Information", 7),
])
def test_nonprimary_context_is_retained_but_lower_prioritized(context, priority):
    primary = ExtractedPage(1, _income_text())
    alternative = ExtractedPage(2, context + "\n" + _income_text())
    pages = detect_statement_pages(_document(primary, alternative), load_metric_config())
    assert len(pages) == 2
    assert pages[0].source_priority == 1
    assert pages[1].source_priority == priority
    assert not pages[1].primary_statement
    assert pages[1].confidence == "medium"


def test_title_alone_and_table_of_contents_references_do_not_create_high_match():
    doc = _document(ExtractedPage(1, "Inhalt\nKonzern-Erfolgsrechnung 120\nKonzernbilanz 121"), ExtractedPage(2, "CEO-Brief\nWir danken unseren Mitarbeitenden."))
    assert detect_statement_pages(doc, load_metric_config()) == ()


def test_sparse_highlight_label_is_low_confidence_without_inferred_period():
    page, = detect_statement_pages(_document(ExtractedPage(1, "Highlights\nFree Cashflow 60")), load_metric_config())
    assert page.confidence == "low"
    assert not page.primary_statement
    assert page.source_priority == 5


def test_table_labels_are_additional_detection_signal_when_text_order_is_poor():
    table = ExtractedTable(1, 1, (("Kennzahl", "2025", "2024"), ("Nettoumsatz", "1100", "1000"), ("EBIT", "143", "150"), ("Nettoergebnis", "92", "100")))
    page = ExtractedPage(1, "Konzern-Erfolgsrechnung\n2025 2024\n1100 1000 143 150 92 100", (table,))
    result, = detect_statement_pages(_document(page), load_metric_config())
    assert result.primary_statement
    assert result.confidence == "high"


def test_words_use_spatial_title_position_instead_of_raw_extraction_order():
    text = "Nettoumsatz 1100 1000\nEBIT 143 150\nNettoergebnis 92 100\n2025 2024\nKonzern-Erfolgsrechnung"
    words = []
    spatial_lines = [(30, "Konzern-Erfolgsrechnung"), (70, "2025 2024"), (100, "Nettoumsatz 1100 1000"), (130, "EBIT 143 150"), (160, "Nettoergebnis 92 100")]
    for index, (y, label) in enumerate(spatial_lines):
        for offset, token in enumerate(label.split()):
            words.append(ExtractedWord(token, 40 + 100 * offset, y, 90 + 100 * offset, y + 12, index, 0, offset))
    page = ExtractedPage(1, text, words=tuple(reversed(words)))
    result, = detect_statement_pages(_document(page), load_metric_config())
    assert result.confidence == "high"
    assert any("Überschrift" in reason for reason in result.reasons)


def test_no_header_does_not_stop_page_detection_but_not_high_confidence():
    text = "Konzern-Erfolgsrechnung\nNettoumsatz 1100 1000\nEBIT 143 150\nNettoergebnis 92 100"
    page, = detect_statement_pages(_document(ExtractedPage(1, text)), load_metric_config())
    assert page.confidence == "medium"
    assert not any("Jahresangaben" in reason for reason in page.reasons)


def test_heading_only_at_bottom_as_prose_reference_is_not_primary():
    text = "Geschäftsverlauf\n" + "\n".join(f"Textabschnitt {index}" for index in range(20)) + "\nKonzern-Erfolgsrechnung\nNettoumsatz 1100 1000"
    result, = detect_statement_pages(_document(ExtractedPage(1, text)), load_metric_config())
    assert result.confidence == "low"
    assert not result.primary_statement


@pytest.mark.parametrize("column_header", [
    "Anhang 2025 2024", "Notes 2025 2024", "Anhang", "Notes",
    "Bezeichnung Anhang 2025 2024", "Description Notes 2025 2024",
    "Bezeichnung Anhang 31.12.2025 31.12.2024",
])
def test_notes_reference_column_does_not_demote_primary_statement(column_header):
    text = _income_text().replace("2025 2024", column_header + "\n2025 2024")
    result, = detect_statement_pages(_document(ExtractedPage(1, text)), load_metric_config())
    assert result.primary_statement
    assert result.source_priority == 1


@pytest.mark.parametrize("text,expected", [("Konzern-Erfolgsrechnung", "income_statement"), ("Consolidated Income Statement 2025", "income_statement"), ("Bilanz des Konzerns", "balance_sheet"), ("Geldflussrechnung", "cash_flow"), ("Siehe Konzern-Erfolgsrechnung", None), ("Nettoumsatz", None)])
def test_public_heading_helper_recognizes_section_start(text, expected):
    assert statement_type_for_heading(text) == expected


@pytest.mark.parametrize("title", [
    "10-Jahres-Kennzahlen", "10 Jahres Kennzahlen", "Kennzahlen", "Key Figures",
    "Key Financial Figures", "Kennzahlenübersicht", "Finanzielle Kennzahlenübersicht",
    "Mehrjahresübersicht", "Financial overview", "10-Jahres-Kennzahlenübersicht",
    "10 Jahreskennzahlenübersicht",
])
def test_key_figures_density_cannot_upgrade_to_primary_statement(title):
    text = _income_text(title) + "\nEBITDA 210 200\nFree Cashflow 60 100"
    page, = detect_statement_pages(_document(ExtractedPage(11, text)), load_metric_config())
    assert page.source_type == "key_figures"
    assert page.source_priority == 3
    assert not page.primary_statement
    assert page.confidence == "medium"


def test_key_figures_heading_in_upper_area_after_running_headers_is_detected():
    running_headers = "\n".join(f"Kopfzeile {index}" for index in range(7))
    text = running_headers + "\n" + _income_text("10-Jahres-Kennzahlen")
    page, = detect_statement_pages(_document(ExtractedPage(11, text)), load_metric_config())
    assert page.source_type == "key_figures"
    assert not page.primary_statement


@pytest.mark.parametrize("heading,label,statement", [
    ("Konsolidierte Erfolgsrechnung", "Nettoumsatz", "income_statement"),
    ("Konsolidierte Bilanz", "Eigenkapital", "balance_sheet"),
    ("Konsolidierte Geldflussrechnung", "Geldfluss aus Geschäftstätigkeit", "cash_flow"),
])
def test_explicit_consolidated_title_supports_one_exact_metric_with_paired_values(heading, label, statement):
    text = f"{heading}\n2025 2024\nMCHF MCHF\n{label} \ue000 28 1099.6 1000.4"
    page, = detect_statement_pages(_document(ExtractedPage(124, text)), load_metric_config())
    assert page.statement_type == statement
    assert page.source_type == "primary_statement"
    assert page.source_priority == 1
    assert page.primary_statement
    assert page.confidence == "high"


def test_narrative_heading_prevents_density_from_upgrading_to_primary():
    page, = detect_statement_pages(_document(ExtractedPage(3, _income_text("Geschäftsverlauf"))), load_metric_config())
    assert page.source_type == "narrative"
    assert page.source_priority == 6
    assert page.confidence == "low"
    assert not page.primary_statement


def test_statement_kind_and_source_kind_remain_separate():
    text = "10-Jahres-Kennzahlen\n2025 2024\nNettoumsatz MCHF 1100 1000"
    page, = detect_statement_pages(_document(ExtractedPage(11, text)), load_metric_config())
    assert page.statement_type == "income_statement"
    assert page.source_type == "key_figures"


def test_source_ranking_does_not_depend_on_page_number():
    kinds = ("primary_statement", "notes", "key_figures", "apm", "highlights", "narrative", "segment")
    assert [source_priority(kind) for kind in kinds] == list(range(1, 8))


def test_notes_title_with_reporting_year_is_not_mistaken_for_reference_column():
    text = "Notes to the financial statements 2025\n" + _income_text()
    page, = detect_statement_pages(_document(ExtractedPage(125, text)), load_metric_config())
    assert page.source_type == "notes"
    assert page.source_priority == 2
    assert not page.primary_statement


def test_reference_header_without_statement_title_does_not_create_notes_context():
    text = _income_text("Finanzinformationen").replace("2025 2024", "Bezeichnung Anhang 2025 2024")
    page, = detect_statement_pages(_document(ExtractedPage(1, text)), load_metric_config())
    assert page.source_type == "primary_statement"
    assert page.primary_statement
    assert page.confidence == "medium"
