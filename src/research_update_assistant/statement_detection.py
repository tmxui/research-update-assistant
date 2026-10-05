"""Transparente Statement-Seitenerkennung aus mehreren unabhängigen Signalen."""

import re

from .candidate_models import SourceType, StatementPage, StatementType
from .document_models import ExtractedDocument, ExtractedPage
from .metric_mapping import MetricConfig, map_metric_label, normalize_metric_label


# Überschriften sind strukturelle Hinweise, keine Zahlen- oder Mapping-Regeln.
_HEADINGS: tuple[tuple[StatementType, tuple[str, ...]], ...] = (
    ("income_statement", (
        "Erfolgsrechnung", "Konzern-Erfolgsrechnung", "Konsolidierte Erfolgsrechnung",
        "Gewinn- und Verlustrechnung", "Konzernerfolgsrechnung", "Income Statement",
        "Statement of Income", "Consolidated Income Statement",
    )),
    ("balance_sheet", (
        "Bilanz", "Konzernbilanz", "Konsolidierte Bilanz", "Bilanz des Konzerns",
        "Balance Sheet", "Statement of Financial Position",
    )),
    ("cash_flow", (
        "Geldflussrechnung", "Konzern-Geldflussrechnung", "Konsolidierte Geldflussrechnung",
        "Kapitalflussrechnung", "Cashflow-Rechnung", "Cash Flow Statement",
        "Statement of Cash Flows",
    )),
)
_CONTEXTS: tuple[tuple[SourceType, str, str], ...] = (
    ("segment", "Segment-/Regionenkontext", r"\b(?:segment(?:bericht|berichterstattung|information|e|s)?|segmental|geographisch\w*|regional\w*)\b"),
    ("notes", "Notes-/Anhangkontext", r"\b(?:anhang|erläuterungen|notes(?: to)?|note \d+)\b"),
    ("apm", "APM-/alternative Kennzahlentabelle", r"\b(?:apm|alternative performance measures|alternative leistungskennzahlen)\b"),
    ("highlights", "Highlights-/Zusammenfassungskontext", r"\b(?:highlights|kennzahlen im überblick|auf einen blick|finanzielle highlights|financial highlights)\b"),
    ("key_figures", "Key-Figures-/mehrjährige Kennzahlenübersicht", r"\b(?:kennzahlen(?:übersicht(?:en)?|überblick|tabelle(?:n)?)?|jahreskennzahlen(?:übersicht)?|mehrjahresübersicht(?:en)?|key figures|key financial figures|financial key figures|financial overview)\b"),
    ("narrative", "Fliesstext-/Geschäftsverlaufskontext", r"\b(?:geschäftsverlauf|lagebericht|ceo brief|management discussion|financial review|review of the year)\b"),
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_NUMBER = re.compile(r"(?<!\w)[−-]?\d+(?:[’'.,]\d+)*(?!\w)")
TITLE_LINE_LIMIT = 12
MIN_PRIMARY_METRIC_COUNT = 3
MIN_PRIMARY_NUMERIC_COUNT = 6


def source_priority(source_type: SourceType) -> int:
    """Quellenart vor Fundreihenfolge: Primärstatement bis Segmentwert."""
    return {
        "primary_statement": 1, "notes": 2, "key_figures": 3, "apm": 4,
        "highlights": 5, "narrative": 6, "other": 6, "segment": 7,
    }[source_type]


def _page_lines(page: ExtractedPage) -> tuple[str, ...]:
    """Räumlich vorhandene Wörter helfen bei ungewöhnlicher Text-Lesereihenfolge."""
    words = getattr(page, "words", ())
    if not words:
        return tuple(line.strip() for line in page.text.splitlines() if line.strip())
    rows: list[list] = []
    for word in sorted(words, key=lambda item: (item.y0, item.x0)):
        if rows and abs(word.y0 - rows[-1][0].y0) <= 3.0:
            rows[-1].append(word)
        else:
            rows.append([word])
    return tuple(" ".join(word.text for word in sorted(row, key=lambda item: item.x0)) for row in rows)


def statement_type_for_heading(text: str) -> StatementType | None:
    """Erkenne eine vollständige bekannte Überschrift, keinen Fliesstext-Verweis.

    Kurze Titelzusätze wie eine Jahresangabe sind zulässig. Der Layoutparser
    kann damit einen neuen Abschnitt beginnen und alte Spalten verwerfen.
    """
    normalized = normalize_metric_label(text)
    for statement, headings in _HEADINGS:
        for heading in headings:
            target = normalize_metric_label(heading)
            if normalized == target or normalized.startswith(target + " ") and len(normalized) <= len(target) + 35:
                return statement
    return None


def _heading_type(lines: tuple[str, ...]) -> StatementType | None:
    return next((statement for line in lines[:TITLE_LINE_LIMIT] if (statement := statement_type_for_heading(line))), None)


def _context(lines: tuple[str, ...]) -> tuple[SourceType, str] | None:
    for source_type, reason, pattern in _CONTEXTS:
        for index, line in enumerate(lines[:TITLE_LINE_LIMIT]):
            normalized = normalize_metric_label(line)
            # Quellentypen werden an kurzen Überschriften erkannt, nicht an
            # beiläufigen Erwähnungen innerhalb langer Zahlen-/Textzeilen.
            if len(line) > 120 or not re.search(pattern, normalized):
                continue
            if source_type == "notes":
                # Primärstatements führen häufig eine Referenzspalte "Anhang"
                # oder "Notes". Sie ist keine Überschrift des Seitenkontexts.
                reference_header = normalized in ("anhang", "notes", "note")
                earlier_statement_title = _heading_type(lines[:index]) is not None
                # Räumliche Zeilen können den Labelspaltenkopf und datierte
                # Perioden zusammenführen: "Bezeichnung Anhang 31.12.2025 ...".
                # Fachliche Notes-Titel enthalten weitere Wörter und bleiben
                # dadurch Notes, selbst wenn ihr Titel ein Berichtsjahr nennt.
                header_words = set(re.findall(r"[^\W\d_]+", normalized))
                reference_header_with_years = bool(
                    _YEAR.search(line)
                    and header_words <= {
                        "bezeichnung", "beschreibung", "position", "description",
                        "item", "label", "anhang", "notes", "note", "referenz",
                        "reference", "ref", "chf", "eur", "usd", "mchf", "mio",
                    }
                    and (earlier_statement_title or len(set(_YEAR.findall(line))) >= 2)
                )
                if reference_header_with_years or reference_header and earlier_statement_title:
                    continue
            return source_type, reason
    return None


def _metric_signals(page: ExtractedPage, lines: tuple[str, ...], config: MetricConfig) -> dict[str, set[str]]:
    matches: dict[str, set[str]] = {"income_statement": set(), "balance_sheet": set(), "cash_flow": set()}
    labels = list(lines)
    # Eine erkannte Tabelle liefert oft sauberere vollständige Zeilenlabels.
    labels.extend(str(row[0]) for table in page.tables for row in table.rows if row and row[0])
    for line in labels:
        label = re.split(r"\s+(?=[−\-(]?\d)", line, maxsplit=1)[0].strip()
        match = map_metric_label(label, config)
        if match:
            matches[match.statement_type].add(match.canonical_metric)
    return matches


def _has_structured_metric_rows(page: ExtractedPage, lines: tuple[str, ...], config: MetricConfig) -> bool:
    """Ein titelarmes Primärstatement benötigt echte Kennzahl-/Zahlenzeilen.

    Blosse Kennzahlenerwähnungen mit Jahren im Fliesstext reichen nicht aus.
    Eine explizite Tabelle kann dieselbe Struktur unabhängig vom Rohtext zeigen.
    """
    structured_metrics: set[str] = set()
    for line in lines:
        label = re.split(r"\s+(?=[−\-(]?\d)", line, maxsplit=1)[0].strip()
        match = map_metric_label(label, config)
        if match and not match.is_segment and len(_NUMBER.findall(line)) >= 2:
            structured_metrics.add(match.canonical_metric)
    for table in page.tables:
        for row in table.rows:
            if not row or not row[0]:
                continue
            match = map_metric_label(row[0], config)
            if match and not match.is_segment and sum(bool(_NUMBER.search(cell or "")) for cell in row[1:]) >= 2:
                structured_metrics.add(match.canonical_metric)
    return len(structured_metrics) >= MIN_PRIMARY_METRIC_COUNT


def detect_statement_pages(document: ExtractedDocument, config: MetricConfig) -> tuple[StatementPage, ...]:
    """Behalte plausible Seiten inklusive niedriger priorisierter Alternativen.

    Titel, typische Kennzahlen, numerische Dichte und Jahresangaben stützen die
    Klassifikation gemeinsam. Notes, APMs, Highlights und Segmente bleiben
    verfügbar. Ein Titel allein erzeugt keine hohe Zuordnungssicherheit.
    """
    result = []
    for page in document.pages:
        lines = _page_lines(page)
        heading = _heading_type(lines)
        consolidated_heading = any(
            statement_type_for_heading(line) and re.search(r"\b(?:konsolidiert\w*|konzern\w*|consolidated)\b", normalize_metric_label(line))
            for line in lines[:TITLE_LINE_LIMIT]
        )
        metrics = _metric_signals(page, lines, config)
        context = _context(lines)
        years = set(_YEAR.findall(page.text))
        number_count = len(_NUMBER.findall(page.text))
        dominant = max(metrics, key=lambda statement: len(metrics[statement]))
        statement: StatementType = heading or dominant
        count = len(metrics[statement])
        if not heading and not any(metrics.values()):
            continue
        # Reine Inhaltsverzeichnis-Verweise ohne Kennzahlen/Zahlen sind unnötig.
        if count == 0 and number_count < 4:
            continue
        reasons = []
        if heading:
            reasons.append("Statement-Überschrift im oberen Seitenbereich erkannt.")
        if count:
            reasons.append(f"{count} typische Kennzahlen derselben Statement-Art erkannt.")
        if len(years) >= 2:
            reasons.append("Mindestens zwei unterschiedliche Jahresangaben vorhanden.")
        if number_count >= MIN_PRIMARY_NUMERIC_COUNT:
            reasons.append("Mehrere numerische Werte unterstützen einen Statement-Kontext.")
        structured = (
            count >= MIN_PRIMARY_METRIC_COUNT and number_count >= MIN_PRIMARY_NUMERIC_COUNT
            and len(years) >= 2 and _has_structured_metric_rows(page, lines, config)
        )
        paired_periods = len(years) >= 2 and number_count >= 4
        primary = context is None and (
            heading is not None and (count >= 2 and number_count >= 4 or count >= 1 and paired_periods)
            or structured
        )
        if context:
            source_type, explanation = context
            reasons.append(explanation + "; gegenüber Primärstatements niedriger priorisiert.")
            confidence = "medium" if source_type != "narrative" and count >= 1 and paired_periods else "low"
        elif primary:
            source_type = "primary_statement"
            confidence = "high" if heading and structured or consolidated_heading and count >= 1 and paired_periods else "medium"
            if consolidated_heading:
                reasons.append("Explizite konsolidierte Statement-Überschrift ist ein starkes Primärquellensignal.")
        else:
            source_type = "other"
            confidence = "low"
            reasons.append("Primärstatement-Kontext nicht ausreichend gestützt.")
        result.append(StatementPage(
            page.page_number, statement, confidence, tuple(reasons), primary,
            source_priority(source_type), source_type,
        ))
    return tuple(result)
