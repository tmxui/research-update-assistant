"""PDF-Text, Roh-Tabellen und technische Diagnose; keine Finanzkennzahlen.

Beide Parser erhalten dieselben Bytes im Arbeitsspeicher. Seitenfehler werden
sichtbar gespeichert, statt unbemerkt als erfolgreich gelesen zu gelten.
"""

from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
import re

import pdfplumber
import pymupdf

from .document_models import (
    LOW_TEXT_CHARACTER_THRESHOLD, DocumentSearchMatch, ExtractedDocument,
    ExtractedPage, ExtractedTable, ExtractionQuality,
)


SCANNED_WARNING = (
    "Das PDF enthält wenig maschinenlesbaren Text und könnte gescannt sein. "
    "Automatische Textextraktion ist für dieses Dokument möglicherweise unzuverlässig."
)


class PdfExtractionError(ValueError):
    """Ein kritischer PDF-Fehler mit einer verständlichen deutschen Meldung."""


def _read_input(source: bytes | Path, file_name: str | None) -> tuple[bytes, str]:
    if isinstance(source, Path):
        try:
            data = source.read_bytes()
        except OSError as error:
            raise PdfExtractionError("Die PDF-Datei konnte nicht gelesen werden.") from error
        name = file_name or source.name
    elif isinstance(source, bytes):
        data, name = source, file_name or "document.pdf"
    else:
        raise TypeError("PDF-Eingabe muss bytes oder pathlib.Path sein.")
    # Nur den Dateinamen behalten; kein lokaler Benutzerpfad in der Provenance.
    name = Path(name.replace("\\", "/")).name or "document.pdf"
    if not data:
        raise PdfExtractionError("Die Datei ist leer und enthält kein gültiges PDF.")
    return data, name


def _extract_tables(pdf: pdfplumber.PDF | None, index: int) -> tuple[tuple[ExtractedTable, ...], list[str]]:
    if pdf is None:
        return (), []  # Der dokumentweite Fehler wird bereits separat angezeigt.
    warnings: list[str] = []
    tables: list[ExtractedTable] = []
    page = None
    try:
        page = pdf.pages[index]
        candidates = page.find_tables()
        for table_index, candidate in enumerate(candidates, start=1):
            try:
                rows = tuple(tuple(row) for row in candidate.extract())
                tables.append(ExtractedTable(index + 1, table_index, rows, tuple(candidate.bbox)))
            except Exception:
                warnings.append(f"PDF-Seite {index + 1}: Tabelle {table_index} konnte nicht extrahiert werden.")
    except Exception:
        warnings.append(f"PDF-Seite {index + 1}: Tabellen konnten nicht gelesen werden.")
    finally:
        if page is not None:
            page.close()  # Layout-Cache der Seite nach der Extraktion freigeben.
    return tuple(tables), warnings


def _extract_page(pdf: pymupdf.Document, table_pdf: pdfplumber.PDF | None, index: int) -> ExtractedPage:
    text, label = "", None
    warnings: list[str] = []
    try:
        page = pdf.load_page(index)
        text = page.get_text("text", sort=False)
    except Exception:
        warnings.append(f"PDF-Seite {index + 1}: Text konnte nicht gelesen werden.")
    else:
        try:
            label = page.get_label() or None
        except Exception:
            warnings.append(f"PDF-Seite {index + 1}: Seitenlabel konnte nicht gelesen werden.")
    tables, table_warnings = _extract_tables(table_pdf, index)
    return ExtractedPage(index + 1, text, tables, label, tuple(warnings + table_warnings))


def _diagnose(pages: tuple[ExtractedPage, ...], warnings: list[str]) -> ExtractionQuality:
    """Transparente Textmengen-Heuristik; keine OCR- oder Inhaltsbewertung.

    Weniger als 40 Nicht-Leerzeichen gilt als textarme Seite. Mindestens 80 %
    textarme Seiten und weniger als 80 Zeichen im Mittel ergeben Scan-Verdacht.
    Mindestens 25 % textarme Seiten, weniger als 200 Zeichen im Mittel oder
    Parser-Warnungen ergeben eingeschränkte Qualität. Grenzen sind inklusiv.
    """
    counts = [page.non_whitespace_character_count for page in pages]
    sparse_ratio = sum(count < LOW_TEXT_CHARACTER_THRESHOLD for count in counts) / len(pages)
    average = sum(counts) / len(pages)
    if sparse_ratio >= 0.8 and average < 80:
        warnings.append(SCANNED_WARNING)
        return "possibly_scanned"
    if sparse_ratio >= 0.25 or average < 200 or warnings:
        return "limited"
    return "good"


def extract_pdf_document(source: bytes | Path, *, file_name: str | None = None) -> ExtractedDocument:
    """Lese ein PDF seitenweise aus Bytes oder Path, ohne es dauerhaft abzulegen.

    Passwortpflichtige und nicht lesbare Dokumente werden abgewiesen. Einzelne
    Text-/Tabellenfehler verhindern die übrige Extraktion nicht.
    """
    data, name = _read_input(source, file_name)
    try:
        pdf = pymupdf.open(stream=data, filetype="pdf")
    except Exception as error:
        raise PdfExtractionError("Die Datei ist kein gültiges oder lesbares PDF; sie könnte beschädigt sein.") from error
    with pdf:
        if not pdf.is_pdf:
            raise PdfExtractionError("Die Datei ist kein gültiges PDF.")
        if pdf.needs_pass:
            raise PdfExtractionError("Das PDF ist passwortgeschützt. Bitte verwende eine ungeschützte PDF-Datei.")
        if pdf.page_count == 0:
            raise PdfExtractionError("Das PDF enthält keine Seiten.")
        warnings: list[str] = []
        if pdf.is_repaired:
            warnings.append("Die PDF-Struktur war beschädigt und wurde vom Parser repariert. Bitte prüfe die extrahierten Inhalte.")
        metadata = pdf.metadata or {}
        with ExitStack() as resources:
            try:
                table_pdf = resources.enter_context(pdfplumber.open(BytesIO(data)))
            except Exception:
                table_pdf = None
                warnings.append("Tabellen konnten für dieses Dokument nicht eingelesen werden. Die Textausgabe bleibt verfügbar.")
            pages = tuple(_extract_page(pdf, table_pdf, index) for index in range(pdf.page_count))
        for page in pages:
            warnings.extend(page.extraction_warnings)
        quality = _diagnose(pages, warnings)
        return ExtractedDocument(
            name, len(data), pages, quality,
            metadata_title=metadata.get("title") or None,
            metadata_author=metadata.get("author") or None,
            extraction_warnings=tuple(warnings),
        )


def search_document(document: ExtractedDocument, query: str) -> tuple[DocumentSearchMatch, ...]:
    """Wörtliche, case-insensitive Unicode-Suche im extrahierten Seitentext.

    Kein Regex vom Nutzer, kein Fuzzy Matching und kein Metric Mapping.
    Pro Seite werden alle nicht überlappenden Treffer gezählt; das Snippet
    zeigt den ersten Treffer mit bis zu 70 Zeichen Kontext auf jeder Seite.
    """
    term = query.strip()
    if not term:
        return ()
    pattern = re.compile(re.escape(term), re.IGNORECASE)
    results: list[DocumentSearchMatch] = []
    for page in document.pages:
        matches = list(pattern.finditer(page.text))
        if not matches:
            continue
        first = matches[0]
        start, end = max(0, first.start() - 70), min(len(page.text), first.end() + 70)
        snippet = ("…" if start else "") + page.text[start:end] + ("…" if end < len(page.text) else "")
        results.append(DocumentSearchMatch(page.page_number, snippet, len(matches)))
    return tuple(results)
