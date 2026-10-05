"""Reales Fehlermuster mit rein synthetischen Seiten, Werten und Wortpositionen."""

from dataclasses import replace

import pytest

from research_update_assistant.document_models import ExtractedDocument, ExtractedPage, ExtractedTable, ExtractedWord
from research_update_assistant.financial_parser import extract_financial_metric_candidates, rank_financial_metric_candidates
from research_update_assistant.metric_mapping import load_metric_config


def word(text, x, y, width=30):
    return ExtractedWord(text, x, y, x + width, y + 10, 0, 0, 0)


def statement_page(page_number=124, *, reference="\ue00028", note_heading=False):
    title = "Konsolidierte Erfolgsrechnung"
    header = (word("Anhang", 260, 40, 40),) if note_heading else ()
    reference_words = (word(reference, 275, 80, 25),) if reference else ()
    words = (
        word(title, 30, 10, 250), *header,
        word("2025", 400, 40), word("2024", 520, 40),
        word("MCHF", 400, 60), word("MCHF", 520, 60),
        word("Nettoumsatz", 30, 80, 100), *reference_words,
        word("1099.6", 390, 80, 40), word("1000.4", 510, 80, 40),
        word("EBIT", 30, 105), word("143", 400, 105), word("150", 520, 105),
    )
    text = f"{title}\nAnhang 2025 2024\nMCHF MCHF\nNettoumsatz {reference} 1099.6 1000.4\nEBIT 143 150"
    return ExtractedPage(page_number, text, words=words)


def overview_page(*, label="Nettoumsatz MCHF", page_number=11, title="10-Jahres-Kennzahlen"):
    words = (
        word(title, 30, 10, 200), word("2025", 400, 40), word("2024", 520, 40),
        word("MCHF", 400, 60), word("MCHF", 520, 60),
        word(label, 30, 80, 280), word("1100", 400, 80), word("1000", 520, 80),
        word("EBIT", 30, 105), word("143", 400, 105), word("150", 520, 105),
    )
    return ExtractedPage(page_number, f"{title}\n2025 2024\nMCHF MCHF\n{label} 1100 1000\nEBIT 143 150", words=words)


def parse(*pages):
    document = ExtractedDocument("synthetic-source-ranking.pdf", 1, tuple(pages), "good")
    return extract_financial_metric_candidates(document, load_metric_config())


def revenues(candidates):
    return [candidate for candidate in candidates if candidate.canonical_metric == "revenue"]


def values(candidate):
    return {value.period_label: value.normalized_value for value in candidate.values}


def test_primary_statement_after_early_key_figures_is_best_and_high_confidence():
    """A: Frühere Kennzahlenübersicht schlägt niemals die exakte Primärquelle."""
    revenue = revenues(parse(overview_page(), statement_page()))
    assert len(revenue) == 2
    primary, summary = revenue
    assert primary.page_number == 124
    assert primary.source_type == "primary_statement"
    assert primary.source_priority == 1
    assert primary.confidence == "high"
    assert values(primary) == {"FY2025": 1099.6, "FY2024": 1000.4}
    assert summary.page_number == 11
    assert summary.source_type == "key_figures"
    assert summary.source_priority == 3
    assert summary.confidence == "medium"


@pytest.mark.parametrize("label", [
    "Nettoumsatz pro Beschäftigten TCHF", "Nettoumsatz je Beschäftigten",
    "Umsatz pro Mitarbeiter", "Umsatz je Mitarbeiter", "Revenue per Employee",
])
def test_per_employee_values_are_never_consolidated_revenue(label):
    """B: Abgeleitete Kennzahlen sind keine übernehmbaren Konzernumsätze."""
    candidates = parse(overview_page(label=label), statement_page())
    assert [candidate.page_number for candidate in revenues(candidates)] == [124]


def test_primary_statement_ranks_above_narrative_even_on_primary_page():
    """C: Eine primäre Überschrift macht einen Fliesstextsatz nicht hochwertig."""
    primary = statement_page()
    narrative_label = "Nettoumsatz wuchs im vergangenen Jahr trotz einer veränderten Nachfrage"
    extra_words = (
        word(narrative_label, 30, 140, 320), word("1110", 400, 140), word("1000", 520, 140),
    )
    narrative = replace(primary, words=primary.words + extra_words,
                        text=primary.text + f"\n{narrative_label} 1110 1000")
    revenue = revenues(parse(narrative))
    assert len(revenue) == 2
    assert values(revenue[0])["FY2025"] == 1099.6
    for candidate in revenue[1:]:
        assert candidate.source_type == "narrative"
        assert candidate.source_priority == 6
        assert candidate.confidence == "low"
        assert candidate.is_segment is False


@pytest.mark.parametrize("reference", ["\ue00028", "\ufffd28", "→28", "\U000f000028"])
def test_pdf_glyph_and_note_number_clean_mapping_preserve_raw_audit(reference):
    """D: Verweiszeichen und Anhangnummer verschwinden nur aus dem Mapping."""
    candidate = revenues(parse(statement_page(reference=reference)))[0]
    assert candidate.normalized_label == "nettoumsatz"
    assert candidate.reported_label == f"Nettoumsatz {reference}"
    assert reference in candidate.source_snippet
    assert candidate.confidence == "high"
    assert values(candidate) == {"FY2025": 1099.6, "FY2024": 1000.4}


def test_rounded_summary_and_precise_statement_values_are_both_kept():
    """E: Ranking wählt Genauigkeit; Deduplizierung verliert keine Abweichung."""
    revenue = revenues(parse(overview_page(), statement_page()))
    assert [values(candidate) for candidate in revenue] == [
        {"FY2025": 1099.6, "FY2024": 1000.4}, {"FY2025": 1100, "FY2024": 1000},
    ]
    assert rank_financial_metric_candidates(tuple(reversed(revenue))) == tuple(revenue)


def test_explicit_note_column_plain_number_is_removed_only_from_mapping():
    candidate = revenues(parse(statement_page(reference="28", note_heading=True)))[0]
    assert candidate.reported_label == "Nettoumsatz 28"
    assert candidate.normalized_label == "nettoumsatz"
    assert candidate.confidence == "high"
    assert [value.raw_value for value in candidate.values] == ["1099.6", "1000.4"]


def test_close_number_in_label_is_not_assumed_to_be_a_note_reference():
    page = statement_page(reference="28")
    words = tuple(replace(item, x0=135, x1=150) if item.text == "28" else item for item in page.words)
    candidate = revenues(parse(replace(page, words=words)))[0]
    assert candidate.reported_label == "Nettoumsatz 28"
    assert candidate.normalized_label == "nettoumsatz 28"
    assert candidate.confidence == "low"


def test_wide_number_without_marker_or_notes_header_is_not_removed():
    page = statement_page(reference="28")
    candidate = revenues(parse(page))[0]
    assert candidate.normalized_label == "nettoumsatz 28"
    assert candidate.confidence == "low"


@pytest.mark.parametrize("name,number", [("IFRS", "16"), ("Scope", "3")])
def test_even_widely_set_genuine_label_numbers_survive(name, number):
    from research_update_assistant.financial_parser import _layout_labels
    from research_update_assistant.layout_parser import LayoutRow, NumericCell, PeriodColumn

    row = LayoutRow((word(name, 30, 80, 40), word(number, 275, 80, 25),
                     word("1099.6", 390, 80, 40), word("1000.4", 510, 80, 40)))
    cells = (NumericCell(number, float(number), (275, 80, 300, 90)),
             NumericCell("1099.6", 1099.6, (390, 80, 430, 90)),
             NumericCell("1000.4", 1000.4, (510, 80, 550, 90)))
    columns = (PeriodColumn("2025", "FY2025", None, 12, (400, 40, 430, 50)),
               PeriodColumn("2024", "FY2024", None, 12, (520, 40, 550, 50)))
    assert _layout_labels(row, cells, columns, ()) == (f"{name} {number}", f"{name} {number}")


def test_separate_marker_and_note_word_between_label_and_amounts():
    page = statement_page(reference="")
    words = page.words + (word("\ue000", 265, 80, 5), word("28", 275, 80, 15))
    candidate = revenues(parse(replace(page, words=words)))[0]
    assert candidate.reported_label == "Nettoumsatz \ue000 28"
    assert candidate.normalized_label == "nettoumsatz"
    assert candidate.confidence == "high"


@pytest.mark.parametrize("label,expected", [
    ("Nettoumsatz \ue00028", "nettoumsatz"),
    ("Nettoumsatz → 28", "nettoumsatz"),
    ("Nettoumsatz 28", "nettoumsatz 28"),
])
def test_table_label_marker_and_reference_are_conservative(label, expected):
    page = statement_page()
    table = ExtractedTable(124, 1, (
        ("Bezeichnung", "Anhang", "2025", "2024"),
        (label, "28", "1099.6", "1000.4"),
    ))
    candidate = revenues(parse(replace(page, words=(), tables=(table,))))[0]
    assert candidate.normalized_label == expected
    assert candidate.reported_label == label
    assert "28" in candidate.source_snippet
    assert values(candidate) == {"FY2025": 1099.6, "FY2024": 1000.4}


def test_source_priority_order_does_not_follow_pdf_page_order():
    base = revenues(parse(statement_page()))[0]
    sources = [("primary_statement", 1), ("notes", 2), ("key_figures", 3),
               ("apm", 4), ("highlights", 5), ("narrative", 6), ("segment", 7)]
    candidates = tuple(replace(base, candidate_id=str(priority), source_type=source,
                               source_priority=priority, page_number=100 - priority)
                       for source, priority in reversed(sources))
    assert [candidate.source_type for candidate in rank_financial_metric_candidates(candidates)] == [source for source, _ in sources]


def test_unclear_source_stays_low_even_with_exact_label_periods_and_units():
    """Gute Einzel-Signale dürfen die unklare Quellenklasse nicht verdecken."""
    candidate = revenues(parse(overview_page(title="Ungeklärte Quelle")))[0]
    assert candidate.source_type == "other"
    assert candidate.source_priority == 6
    assert candidate.currency == "CHF"
    assert candidate.scale == "million"
    assert values(candidate) == {"FY2025": 1100, "FY2024": 1000}
    assert candidate.confidence == "low"
