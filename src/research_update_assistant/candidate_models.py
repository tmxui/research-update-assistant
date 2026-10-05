"""Unbestätigte Vorschläge, getrennt von normalisierten Finanzperioden."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

StatementType = Literal["income_statement", "balance_sheet", "cash_flow", "other"]
SourceType = Literal["primary_statement", "notes", "key_figures", "apm", "highlights", "narrative", "segment", "other"]
Confidence = Literal["high", "medium", "low"]
ExtractionMethod = Literal["pdfplumber_table", "pymupdf_layout", "text_fallback", "manual"]
BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class StatementPage:
    """Transparente Klassifikation einer Seite; keine Wahrscheinlichkeit."""

    page_number: int
    statement_type: StatementType
    confidence: Confidence
    reasons: tuple[str, ...]
    primary_statement: bool = False
    source_priority: int = 6
    source_type: SourceType = "other"


@dataclass(frozen=True)
class PeriodValueCandidate:
    """Ein Rohwert und seine vorgeschlagene Spaltenzuordnung.

    Ohne sicheren Header bleiben Periodenmetadaten None. Zahlen werden weder
    skaliert noch gerundet. EPS ist stets ein Währungsbetrag je Aktie.
    """

    period_label: str | None
    raw_value: str
    normalized_value: float | None
    column_header: str | None = None
    period_end: date | None = None
    period_months: int | None = None
    bbox: BBox | None = None


@dataclass(frozen=True)
class FinancialMetricCandidate:
    """Kennzahl-Vorschlag mit Herkunft, Alternativen bleiben separat erhalten.

    reported_label bewahrt die Originalbezeichnung für den Audit-Trail.
    normalized_label dient nur dem Mapping. Die Quellenart ist unabhängig
    davon, ob die Zeile fachlich zur Erfolgsrechnung, Bilanz oder zum Cashflow gehört.
    """

    candidate_id: str
    canonical_metric: str
    display_name_de: str
    reported_label: str
    statement_type: StatementType
    source_document: str
    page_number: int
    source_snippet: str
    extraction_method: ExtractionMethod
    confidence: Confidence
    confidence_reasons: tuple[str, ...]
    currency: str | None
    scale: str | None
    values: tuple[PeriodValueCandidate, ...]
    bbox: BBox | None = None
    is_segment: bool = False
    source_priority: int = 6
    source_type: SourceType = "other"
    normalized_label: str | None = None
