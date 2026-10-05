"""Technische PDF-Daten mit Seitenherkunft, ohne Finanzinterpretation."""

from dataclasses import dataclass
from typing import Literal


ExtractionQuality = Literal["good", "limited", "possibly_scanned"]
LOW_TEXT_CHARACTER_THRESHOLD = 40


@dataclass(frozen=True)
class ExtractedWord:
    """Ein maschinenlesbares Wort und seine PDF-Koordinaten (Punkte).

    Block-, Zeilen- und Wortnummern stammen unverändert von PyMuPDF. Die
    spätere logische Zeilensortierung verwendet zusätzlich die Koordinaten.
    """

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    block_number: int
    line_number: int
    word_number: int
    font_size: float | None = None


@dataclass(frozen=True)
class ExtractedTable:
    """Rohzellen und Position einer Tabelle; Indizes sind 1-basiert."""

    page_number: int
    table_index: int
    rows: tuple[tuple[str | None, ...], ...]
    bbox: tuple[float, float, float, float] | None = None

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return max((len(row) for row in self.rows), default=0)


@dataclass(frozen=True)
class ExtractedPage:
    """PDF-Seite mit unverändertem extrahiertem Text und lokalen Warnungen.

    Die physische PDF-Seitennummer ist nicht zwingend die gedruckte Seitennummer.
    Ein leerer Text mit Warnung kann auch einen Lesefehler bedeuten.
    """

    page_number: int
    text: str
    tables: tuple[ExtractedTable, ...] = ()
    printed_page_label: str | None = None
    extraction_warnings: tuple[str, ...] = ()
    words: tuple[ExtractedWord, ...] = ()

    @property
    def text_length(self) -> int:
        return len(self.text)

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())

    @property
    def has_tables(self) -> bool:
        return bool(self.tables)

    @property
    def non_whitespace_character_count(self) -> int:
        return sum(not character.isspace() for character in self.text)


@dataclass(frozen=True)
class ExtractedDocument:
    """Ein Dokument ist eine Quelle, noch keine normalisierte Finanzhistorie."""

    file_name: str
    file_size_bytes: int
    pages: tuple[ExtractedPage, ...]
    extraction_quality: ExtractionQuality
    metadata_title: str | None = None
    metadata_author: str | None = None
    extraction_warnings: tuple[str, ...] = ()

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def text_page_count(self) -> int:
        return sum(page.has_text for page in self.pages)

    @property
    def pages_with_tables(self) -> int:
        return sum(page.has_tables for page in self.pages)

    @property
    def total_tables(self) -> int:
        return sum(len(page.tables) for page in self.pages)

    @property
    def low_text_page_count(self) -> int:
        return sum(
            page.non_whitespace_character_count < LOW_TEXT_CHARACTER_THRESHOLD
            for page in self.pages
        )

    @property
    def possibly_scanned(self) -> bool:
        return self.extraction_quality == "possibly_scanned"


@dataclass(frozen=True)
class DocumentSearchMatch:
    """Ein Suchtreffer je Seite mit Gesamtanzahl und Kontext des ersten Treffers."""

    page_number: int
    snippet: str
    match_count: int
