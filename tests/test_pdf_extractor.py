"""Synthetische PDFs und gezielte Parserfehler; keine externen Berichte."""

import subprocess
import sys
from unittest.mock import Mock

import pymupdf
import pytest

from research_update_assistant import pdf_extractor
from research_update_assistant.document_models import ExtractedDocument, ExtractedPage, ExtractedTable
from research_update_assistant.pdf_extractor import PdfExtractionError, extract_pdf_document, search_document


def test_valid_pdf_retains_pages_metadata_unicode_and_raw_text(synthetic_pdf_bytes):
    document = extract_pdf_document(synthetic_pdf_bytes, file_name="synthetic.pdf")
    assert document.file_name == "synthetic.pdf"
    assert document.file_size_bytes == len(synthetic_pdf_bytes)
    assert document.page_count == document.text_page_count == 3
    assert [page.page_number for page in document.pages] == [1, 2, 3]
    assert "Geschäftsbericht" in document.pages[0].text
    assert "Vorräte" in document.pages[0].text
    assert "CHF 1’100,5" in document.pages[0].text
    assert "Nettoumsatz 2025 1'100" in document.pages[1].text
    assert "Nettoumsatz 2025" not in document.pages[0].text
    assert "\n" in document.pages[0].text
    assert document.pages[0].text_length == len(document.pages[0].text)
    assert document.pages[0].printed_page_label == "S-1"
    assert document.metadata_title == "Synthetischer Geschäftsbericht 2025"
    assert document.metadata_author == "Research Update Assistant"
    assert document.extraction_quality == "good"
    assert not document.possibly_scanned
    assert not document.extraction_warnings
    with pymupdf.open(stream=synthetic_pdf_bytes, filetype="pdf") as original:
        assert document.pages[1].text == original[1].get_text("text", sort=False)


def test_table_rows_bounding_box_and_page_provenance(synthetic_pdf_bytes):
    document = extract_pdf_document(synthetic_pdf_bytes)
    assert document.pages_with_tables == document.total_tables == 1
    assert not document.pages[0].has_tables
    table = document.pages[2].tables[0]
    assert table.page_number == 3
    assert table.table_index == 1
    assert table.row_count == table.column_count == 3
    assert table.rows == (("Rohbezeichnung", "2025", "2024"), ("Nettoumsatz", "1’100", "1'000"), ("EBIT", "143", "150"))
    assert table.bbox == pytest.approx((45, 210, 530, 315))


def test_path_input_matches_memory_and_keeps_only_file_name(synthetic_pdf_bytes, tmp_path):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(synthetic_pdf_bytes)
    assert extract_pdf_document(path) == extract_pdf_document(synthetic_pdf_bytes, file_name=path.name)
    assert extract_pdf_document(synthetic_pdf_bytes, file_name="C:\\private\\report.pdf").file_name == "report.pdf"


def test_empty_page_remains_present_and_limits_quality(synthetic_pdf_bytes):
    with pymupdf.open(stream=synthetic_pdf_bytes, filetype="pdf") as pdf:
        pdf.new_page()
        data = pdf.tobytes()
    document = extract_pdf_document(data)
    empty = document.pages[3]
    assert document.page_count == 4
    assert document.text_page_count == 3
    assert empty.text == ""
    assert empty.text_length == 0
    assert not empty.has_text and not empty.has_tables
    assert not empty.extraction_warnings
    assert document.extraction_quality == "limited"


@pytest.mark.parametrize("data", [b"", b"not a pdf", b"%PDF-1.7\nbroken"])
def test_invalid_or_corrupt_pdf_has_readable_error(data):
    with pytest.raises(PdfExtractionError, match="gültiges|beschädigt"):
        extract_pdf_document(data)


def test_missing_path_has_readable_error(tmp_path):
    with pytest.raises(PdfExtractionError, match="nicht gelesen"):
        extract_pdf_document(tmp_path / "missing.pdf")


def test_non_pdf_image_is_rejected():
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), False)
    pixmap.clear_with(240)
    with pytest.raises(PdfExtractionError, match="gültiges"):
        extract_pdf_document(pixmap.tobytes("png"))


def test_password_protected_pdf_is_rejected(synthetic_pdf_bytes):
    with pymupdf.open(stream=synthetic_pdf_bytes, filetype="pdf") as pdf:
        data = pdf.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="synthetic-owner", user_pw="synthetic-user")
    with pytest.raises(PdfExtractionError, match="passwortgeschützt"):
        extract_pdf_document(data)


def test_zero_page_pdf_has_readable_error(monkeypatch):
    pdf = Mock(is_pdf=True, needs_pass=False, page_count=0)
    pdf.__enter__ = Mock(return_value=pdf)
    pdf.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(pdf_extractor.pymupdf, "open", Mock(return_value=pdf))
    with pytest.raises(PdfExtractionError, match="keine Seiten"):
        extract_pdf_document(b"synthetic fake zero-page handle")
    pdf.__exit__.assert_called_once()


def test_image_only_document_is_flagged_without_ocr():
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100), False)
    pixmap.clear_with(230)
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_image(pymupdf.Rect(40, 40, 400, 220), pixmap=pixmap)
        data = pdf.tobytes()
    document = extract_pdf_document(data)
    assert document.possibly_scanned
    assert document.text_page_count == 0
    assert document.pages[0].text == ""
    assert pdf_extractor.SCANNED_WARNING in document.extraction_warnings


def test_short_machine_readable_document_can_also_trigger_scan_heuristic():
    pages = (ExtractedPage(1, "Kurzer Text"),)
    warnings = []
    assert pdf_extractor._diagnose(pages, warnings) == "possibly_scanned"
    assert warnings == [pdf_extractor.SCANNED_WARNING]


@pytest.mark.parametrize("sparse_count, total, expected", [(4, 5, "possibly_scanned"), (1, 4, "limited"), (0, 4, "good")])
def test_quality_heuristic_boundaries_are_transparent(sparse_count, total, expected):
    pages = tuple(ExtractedPage(i + 1, "" if i < sparse_count else "a" * 300) for i in range(total))
    assert pdf_extractor._diagnose(pages, []) == expected


def test_failed_page_keeps_other_pages_and_warning(synthetic_pdf_bytes, monkeypatch):
    original = pymupdf.Page.get_text
    def fail_middle(page, *args, **kwargs):
        if page.number == 1:
            raise RuntimeError("synthetic text failure")
        return original(page, *args, **kwargs)
    monkeypatch.setattr(pymupdf.Page, "get_text", fail_middle)
    document = extract_pdf_document(synthetic_pdf_bytes)
    assert document.page_count == 3
    assert document.pages[0].has_text and document.pages[2].has_text
    assert document.pages[1].text == ""
    assert "PDF-Seite 2: Text konnte nicht gelesen werden." in document.extraction_warnings
    assert document.extraction_quality == "limited"


def test_table_page_failure_keeps_text_and_other_tables(synthetic_pdf_bytes, monkeypatch):
    original = pdf_extractor.pdfplumber.page.Page.find_tables
    def fail_first(page, *args, **kwargs):
        if page.page_number == 1:
            raise RuntimeError("synthetic table failure")
        return original(page, *args, **kwargs)
    monkeypatch.setattr(pdf_extractor.pdfplumber.page.Page, "find_tables", fail_first)
    document = extract_pdf_document(synthetic_pdf_bytes)
    assert document.text_page_count == 3
    assert document.total_tables == 1
    assert "PDF-Seite 1: Tabellen konnten nicht gelesen werden." in document.extraction_warnings


def test_single_table_failure_is_not_reported_as_success(synthetic_pdf_bytes, monkeypatch):
    monkeypatch.setattr(pdf_extractor.pdfplumber.table.Table, "extract", Mock(side_effect=RuntimeError("synthetic failure")))
    document = extract_pdf_document(synthetic_pdf_bytes)
    assert document.text_page_count == 3
    assert document.total_tables == 0
    assert "PDF-Seite 3: Tabelle 1 konnte nicht extrahiert werden." in document.extraction_warnings


def test_table_parser_failure_does_not_block_text(synthetic_pdf_bytes, monkeypatch):
    monkeypatch.setattr(pdf_extractor.pdfplumber, "open", Mock(side_effect=ValueError("synthetic failure")))
    document = extract_pdf_document(synthetic_pdf_bytes)
    assert document.text_page_count == 3
    assert document.total_tables == 0
    assert document.extraction_quality == "limited"
    assert any("Tabellen konnten für dieses Dokument" in warning for warning in document.extraction_warnings)


@pytest.mark.parametrize("query, pages, counts", [
    ("EBIT", [2, 3], [2, 1]), ("ebit", [2, 3], [2, 1]),
    ("Nettoumsatz", [2, 3], [2, 1]), ("vORRÄTE", [1], [1]),
    ("nicht vorhandener Begriff", [], []), ("", [], []), ("   ", [], []),
    ("1’100,5", [1], [1]), ("(EBIT)", [2], [2]),
])
def test_literal_unicode_search_returns_pages_counts_and_original_snippets(synthetic_pdf_bytes, query, pages, counts):
    matches = search_document(extract_pdf_document(synthetic_pdf_bytes), query)
    assert [match.page_number for match in matches] == pages
    assert [match.match_count for match in matches] == counts
    assert all(len(match.snippet) <= len(query.strip()) + 142 for match in matches)
    if query.lower() == "ebit":
        assert "Betriebsgewinn (EBIT)" in matches[0].snippet
        assert "…" in matches[0].snippet


def test_search_escapes_regex_and_preserves_newlines():
    document = ExtractedDocument("synthetic.pdf", 100, (ExtractedPage(1, "Anfang\nMarge: 13,0 %\n[EBIT].\nEnde"),), "limited")
    result = search_document(document, "[EBIT].")
    assert result[0].match_count == 1
    assert "\n[EBIT].\n" in result[0].snippet
    assert search_document(document, ".*") == ()


def test_empty_and_ragged_table_cells_are_raw_values():
    table = ExtractedTable(2, 1, (("Kopf", ""), (None, "1’100", "CHF")))
    assert table.row_count == 2
    assert table.column_count == 3
    assert table.rows[0][1] == ""
    assert table.rows[1][0] is None


def test_pdf_layer_has_no_finance_or_streamlit_dependency():
    script = (
        "import sys; "
        "blocked=['streamlit','research_update_assistant.calculations','research_update_assistant.flags','research_update_assistant.charts']; "
        "sys.modules.update({name: None for name in blocked}); "
        "from research_update_assistant.pdf_extractor import extract_pdf_document, search_document"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
