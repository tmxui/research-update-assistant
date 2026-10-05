"""Plausible Finanzkennzahl-Kandidaten aus drei unabhängigen Extraktionskanälen.

Es entstehen ausschliesslich Vorschläge mit Rohwerten und Herkunft, niemals
FinancialPeriods. Tabellen und Koordinaten stützen eine Spaltenzuordnung;
ohne Header bleibt die Periode unbekannt und die Sicherheit niedrig.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from hashlib import sha256
import re
import unicodedata

from .candidate_models import BBox, ExtractionMethod, FinancialMetricCandidate, PeriodValueCandidate, StatementPage
from .document_models import ExtractedDocument, ExtractedPage, ExtractedTable
from .input_parsing import NumberParsingError
from .layout_parser import (
    COLUMN_X_TOLERANCE, CONTINUATION_Y_GAP, LayoutRow, NumericCell, PeriodColumn,
    assign_cells_to_columns, extract_numeric_cells, group_words_into_rows,
    parse_accounting_number, parse_period_header, period_columns_in_row, union_bbox,
)
from .metric_mapping import MetricConfig, MetricMatch, map_metric_label, normalize_mapping_label
from .statement_detection import detect_statement_pages, source_priority, statement_type_for_heading


def _period_context(document: ExtractedDocument, page: ExtractedPage) -> str:
    return "\n".join((
        document.metadata_title or "", "\n".join(page.text.splitlines()[:12]),
        "\n".join(document.pages[0].text.splitlines()[:12]) if document.pages else "",
    ))


def _has_half_year_context(document: ExtractedDocument, page: ExtractedPage) -> bool:
    """Nur explizite Halbjahresbezeichnungen ändern den Jahresheader-Vorschlag."""
    return re.search(r"\bH1\b|Halbjahr|Half[ -]year|Six months", _period_context(document, page), re.IGNORECASE) is not None


def _unsupported_period_context(document: ExtractedDocument, page: ExtractedPage) -> bool:
    return re.search(r"\bQ[1-4]\b|Quartal|Quarter|(?:9|neun) Monate|Nine months", _period_context(document, page), re.IGNORECASE) is not None


def _period_with_context(
    header: str, period: tuple[str | None, date | None, int | None], half_year: bool,
    *, unsupported: bool = False,
) -> tuple[str | None, date | None, int | None]:
    label, end, months = period
    if half_year and re.fullmatch(r"20\d{2}", header.strip()):
        year = int(re.search(r"20\d{2}", header).group())
        return f"H1 {year}", date(year, 6, 30), 6
    if half_year and end is not None and (end.month, end.day) == (6, 30):
        return f"H1 {end.year}", end, 6
    if unsupported and re.fullmatch(r"20\d{2}", header.strip()):
        return None, None, None  # Quartalswerte niemals als Jahreswerte ausgeben.
    return label, end, months


def _unit_signals(text: str) -> tuple[set[str], set[str]]:
    """Explizite Einheits-Signale getrennt sammeln, damit Konflikte sichtbar bleiben."""
    upper = text.upper()
    currencies = set(re.findall(r"(?<![A-Z])(?:M)?(CHF|EUR|USD)(?![A-Z])", upper))
    scales: set[str] = set()
    if re.search(r"\b(?:MCHF|MEUR|MUSD|MIO\.?|MILLIONEN?|MILLIONS?)\b", upper):
        scales.add("million")
    if re.search(r"\b(?:TCHF|TEUR|TUSD|TSD\.?|TAUSEND|THOUSANDS?)\b", upper):
        scales.add("thousand")
        currencies.update(re.findall(r"\bT(CHF|EUR|USD)\b", upper))
    if re.search(r"\b(?:MRD\.?|MILLIARDEN?|BILLIONS?)\b", upper):
        scales.add("billion")
    if re.search(r"\b(?:EINHEITEN|UNITS)\b", upper):
        scales.add("unit")
    if re.search(r"\b(?:CHF|EUR|USD)\s*(?:IN\s*)?['’]?000\b", upper):
        scales.add("thousand")
    return currencies, scales


def detect_currency_scale(text: str) -> tuple[str | None, str | None]:
    """Erkenne explizite Währung/Einheit; fehlend oder widersprüchlich bleibt None.

    Werte werden nicht umgerechnet. MCHF/MEUR/MUSD bezeichnet Millionen.
    ``CHF`` alleine belegt keine Skalierung, daher kein stilles Default.
    """
    currencies, scales = _unit_signals(text)
    return (next(iter(currencies)) if len(currencies) == 1 else None,
            next(iter(scales)) if len(scales) == 1 else None)


def _local_unit(text: str, fallback: tuple[str | None, str | None]) -> tuple[str | None, str | None]:
    currencies, scales = _unit_signals(text)
    # Fehlende Angaben dürfen aus dem Tabellenkopf stammen. Widersprüchliche
    # explizite Angaben dürfen dagegen nicht durch den Fallback verdeckt werden.
    currency = next(iter(currencies)) if len(currencies) == 1 else None if currencies else fallback[0]
    scale = next(iter(scales)) if len(scales) == 1 else None if scales else fallback[1]
    return currency, scale


def _candidate(
    document: ExtractedDocument, page: ExtractedPage, statement: StatementPage,
    match: MetricMatch, label: str, values: tuple[PeriodValueCandidate, ...],
    method: ExtractionMethod, snippet: str, currency: str | None, scale: str | None,
    *, bbox: BBox | None = None, uncertain: bool = False,
    mapping_label: str | None = None,
) -> FinancialMetricCandidate:
    reasons = list(statement.reasons) + list(match.reasons)
    normalized_label = normalize_mapping_label(mapping_label if mapping_label is not None else label)
    narrative = _is_narrative_label(normalized_label)
    is_segment = statement.source_type == "segment" or (match.is_segment and not narrative)
    candidate_source = "segment" if is_segment else "narrative" if narrative else statement.source_type
    if narrative:
        reasons.append("Fliesstext statt einer kurzen Statement-Zeile; niedrige Quellenpriorität.")
    known = all(value.period_label is not None for value in values)
    if known and len(values) >= 2:
        reasons.append("Mehrere Periodenheader erkannt; Werte anhand der Spalten zugeordnet.")
    else:
        reasons.append("Periodenzuordnung fehlt oder ist unvollständig; Nutzerbestätigung erforderlich.")
    if currency and scale:
        reasons.append("Währung und Skalierung explizit erkannt.")
    else:
        reasons.append("Währung oder Skalierung fehlt; bitte ergänzen bzw. prüfen.")
    if method == "pymupdf_layout":
        reasons.append("Zeilen und Betragsspalten aus PDF-Wortpositionen rekonstruiert.")
    elif method == "pdfplumber_table":
        reasons.append("Werte aus expliziten Tabellenzellen mit Headern gelesen.")
    else:
        reasons.append("Nur Textfallback verfügbar; keine räumliche Spaltenzuordnung.")
    if uncertain:
        reasons.append("Layout oder Zeilenfortsetzung nicht vollständig eindeutig.")
    if is_segment:
        reasons.append("Segment-/Regionsbezeichnung; kein bestätigbarer Konzernwert.")
    if (
        is_segment or narrative or not known or method == "text_fallback"
        or statement.confidence == "low" or candidate_source == "other"
    ):
        confidence = "low"
    elif (
        statement.primary_statement and statement.confidence == "high"
        and match.confidence == "high" and currency and scale and not uncertain
        and len(values) >= 2
    ):
        confidence = "high"
    else:
        confidence = "medium" if match.confidence != "low" else "low"
    # Deterministisch: keine zeitabhängigen IDs, keine globale mutable state.
    identity = repr((
        document.file_name, page.page_number, match.canonical_metric, label,
        method, bbox, tuple((v.period_label, v.raw_value, v.bbox) for v in values),
    ))
    return FinancialMetricCandidate(
        candidate_id=sha256(identity.encode("utf-8")).hexdigest()[:20],
        canonical_metric=match.canonical_metric, display_name_de=match.display_name_de,
        reported_label=label, statement_type=match.statement_type,
        source_document=document.file_name, page_number=page.page_number,
        source_snippet=snippet, extraction_method=method, confidence=confidence,
        confidence_reasons=tuple(dict.fromkeys(reasons)), currency=currency,
        scale="unit" if match.canonical_metric in ("basic_eps", "diluted_eps") and currency else scale,
        values=values, bbox=bbox, is_segment=is_segment,
        source_priority=source_priority(candidate_source), source_type=candidate_source,
        normalized_label=normalized_label,
    )


def _is_narrative_label(label: str) -> bool:
    """Lange Satzbezeichnungen bleiben schwächer als echte Tabellenzeilen."""
    return len(label.split()) >= 6 and re.search(
        r"\b(?:stieg|sank|nahm|betrug|wuchs|erhöhte|verminderte|increased|decreased|rose|grew|amounted)\b",
        label,
    ) is not None


def _has_reference_glyph(text: str) -> bool:
    return any(unicodedata.category(char) == "Co" or char in "\ufffd→↗↘↖↙↔⇒➜➔↪↩" for char in text)


def _reference_number(text: str) -> bool:
    """Nur kleine, positive Anhangnummern; niemals beliebige Labelzahlen."""
    without_glyphs = "".join(char for char in text if not _has_reference_glyph(char)).strip()
    return re.fullmatch(r"[1-9]\d{0,2}", without_glyphs) is not None


def _layout_labels(
    row: LayoutRow, cells: tuple[NumericCell, ...], columns: tuple[PeriodColumn, ...],
    note_positions: tuple[float, ...],
) -> tuple[str, str]:
    """Erhalte das Rohlabel und entferne nur räumlich belegte Verweise fürs Mapping.

    Eine Zahl direkt im Label (etwa ``IFRS 16``) bleibt erhalten. Ein Verweis
    braucht bekannte Jahresbetragsspalten und eine explizite Anhangspalte
    oder einen PDF-Verweismarker an einer räumlich getrennten Position.
    """
    if not columns:
        label = _label_in_row(row, cells)
        return label, label
    amount_cells = tuple(cell for cell in cells if cell.bbox[2] >= min(col.right for col in columns) - COLUMN_X_TOLERANCE)
    if not amount_cells:
        return row.text.strip(), row.text.strip()
    first_amount_x = min(cell.bbox[0] for cell in amount_cells)
    words = tuple(word for word in row.words if word.x1 <= first_amount_x)
    reported_label = " ".join(word.text for word in words).strip()
    removed: set[int] = set()
    for index, word in enumerate(words):
        if not _reference_number(word.text):
            continue
        explicit_column = any(abs(word.x1 - right) <= COLUMN_X_TOLERANCE for right in note_positions)
        if index == 0:
            if explicit_column:
                removed.add(index)
            continue
        preceding = words[index - 1]
        marker_index = index - 1 if _has_reference_glyph(preceding.text) and not normalize_mapping_label(preceding.text) else None
        reference_start = words[marker_index].x0 if marker_index is not None else word.x0
        label_index = index - 2 if marker_index is not None else index - 1
        separate = label_index >= 0 and reference_start - words[label_index].x1 > 15
        has_marker = _has_reference_glyph(word.text) or marker_index is not None
        if explicit_column or (separate and has_marker):
            removed.add(index)
            if marker_index is not None:
                removed.add(marker_index)
    mapping_label = " ".join(word.text for index, word in enumerate(words) if index not in removed).strip()
    return reported_label, mapping_label


def _table_mapping_label(label: str, columns: dict[int, tuple]) -> str:
    """Ein eindeutiger PDF-Verweismarker vor der Endnummer ist keine Kennzahl."""
    if len(columns) < 2 or not _has_reference_glyph(label):
        return label
    match = re.search(r"\s+(\S*?)([1-9]\d{0,2})\s*$", label)
    if match and _has_reference_glyph(match.group(1)) and not normalize_mapping_label(match.group(1)):
        return label[:match.start()].rstrip()
    # Verweiszeichen und Nummer können im selben Tabellenfeld getrennt sein.
    match = re.search(r"\s+(\S+)\s+([1-9]\d{0,2})\s*$", label)
    if match and _has_reference_glyph(match.group(1)) and not normalize_mapping_label(match.group(1)):
        return label[:match.start()].rstrip()
    return label


def _label_in_row(row: LayoutRow, cells: tuple[NumericCell, ...]) -> str:
    if not cells:
        return row.text.strip()
    first_number_x = min(cell.bbox[0] for cell in cells)
    return " ".join(word.text for word in row.words if word.x1 <= first_number_x).strip()


def _layout_values(
    cells: tuple[NumericCell, ...], columns: tuple[PeriodColumn, ...],
) -> tuple[tuple[PeriodValueCandidate, ...], bool]:
    assignments = assign_cells_to_columns(cells, columns)
    if assignments:
        values = tuple(PeriodValueCandidate(
            column.period_label, cell.raw_value, cell.normalized_value,
            column.column_header, column.period_end, column.period_months, cell.bbox,
        ) for column, cell in assignments)
        # Zahlen links der Betragsspalten sind Anhangnummern und werden ignoriert.
        financial_cells = tuple(cell for cell in cells if cell.bbox[2] >= min(col.right for col in columns) - COLUMN_X_TOLERANCE)
        unmatched = tuple(cell for cell in financial_cells if cell not in [pair[1] for pair in assignments])
        # Unsichere Werte nicht verwerfen, aber auch keinem Jahr zuweisen.
        values += tuple(PeriodValueCandidate(None, cell.raw_value, cell.normalized_value, bbox=cell.bbox) for cell in unmatched)
        return values, len(assignments) != len(columns) or bool(unmatched)
    if columns:
        cells = tuple(cell for cell in cells if cell.bbox[2] >= min(col.right for col in columns) - COLUMN_X_TOLERANCE)
    return tuple(PeriodValueCandidate(None, cell.raw_value, cell.normalized_value, bbox=cell.bbox) for cell in cells), True


def _nearby_unit(rows: tuple[LayoutRow, ...], index: int, fallback: tuple[str | None, str | None]) -> tuple[str | None, str | None]:
    for row in reversed(rows[:index + 1]):
        signals = _unit_signals(row.text)
        if any(signals):
            # Eine Zeile mit CHF je Aktie darf die vollständige Tabelleneinheit
            # nicht durch eine implizite Annahme ersetzen.
            return _local_unit(row.text, fallback)
        if statement_type_for_heading(row.text):
            break
    return fallback


def _debt_component_heading(text: str) -> bool:
    """Kurz-/langfristige Schulden sind Bestandteile, keine Gesamtverschuldung."""
    return re.fullmatch(
        r"(?:kurzfristig\w*|langfristig\w*|current|non[ -]?current)\s+"
        r"(?:finanz)?(?:verbindlichkeiten|schulden|liabilities|debt|borrowings)",
        text.strip(), re.IGNORECASE,
    ) is not None


def _closes_debt_component_section(text: str) -> bool:
    return re.fullmatch(
        r"(?:Total\s+|Summe\s+)?(?:Eigenkapital|Equity|Aktiven|Assets|Passiven|Liabilities)",
        text.strip(), re.IGNORECASE,
    ) is not None


def _layout_candidates(
    document: ExtractedDocument, page: ExtractedPage,
    statement: StatementPage, config: MetricConfig,
) -> list[FinancialMetricCandidate]:
    rows = group_words_into_rows(page.words)
    columns: tuple[PeriodColumn, ...] = ()
    note_positions: tuple[float, ...] = ()
    fallback_unit = detect_currency_scale("\n".join(row.text for row in rows[:12]))
    candidates: list[FinancialMetricCandidate] = []
    half_year = _has_half_year_context(document, page)
    unsupported = _unsupported_period_context(document, page)
    debt_component = False
    index = 0
    while index < len(rows):
        row = rows[index]
        if statement_type_for_heading(row.text):
            # Ein Header oberhalb einer neuen Statement-Überschrift gehört
            # nicht automatisch zu den folgenden Finanzzeilen.
            columns = ()
            note_positions = ()
            fallback_unit = detect_currency_scale(row.text)
            debt_component = False
            index += 1
            continue
        if header := period_columns_in_row(row):
            note_positions = tuple(word.x1 for word in row.words if re.fullmatch(
                r"(?:Anhang|Notes?|Erläuterung)", word.text, re.IGNORECASE,
            ))
            columns = tuple(replace(
                column, period_label=period[0], period_end=period[1], period_months=period[2],
            ) for column in header if (period := _period_with_context(
                column.column_header,
                (column.period_label, column.period_end, column.period_months), half_year,
                unsupported=unsupported,
            )))
            index += 1
            continue
        cells = extract_numeric_cells(row)
        label, mapping_label = _layout_labels(row, cells, columns, note_positions)
        if _debt_component_heading(label):
            debt_component = True
        elif _closes_debt_component_section(label):
            debt_component = False
        match = map_metric_label(mapping_label, config) if mapping_label else None
        consumed = 1
        snippet = row.text
        bbox = row.bbox
        continued = False
        # Bezeichnung und Zahlen können in verschiedenen Textblöcken/Zeilen
        # stehen. Bis zu zwei nahe Folgezeilen unterstützen Label-Umbrüche.
        if label and not cells:
            combined_label = label
            combined_mapping_label = mapping_label
            for step in (1, 2):
                if index + step >= len(rows):
                    break
                following = rows[index + step]
                previous = rows[index + step - 1]
                if following.bbox[1] - previous.bbox[3] > CONTINUATION_Y_GAP:
                    break
                if period_columns_in_row(following):
                    break
                next_cells = extract_numeric_cells(following)
                next_label, next_mapping_label = _layout_labels(following, next_cells, columns, note_positions)
                next_match = map_metric_label(next_mapping_label, config) if next_mapping_label else None
                if next_match:
                    break  # Eine eigenständige Kennzahl ist keine Fortsetzung.
                combined_label = " ".join(part for part in (combined_label, next_label) if part)
                combined_mapping_label = " ".join(part for part in (combined_mapping_label, next_mapping_label) if part)
                combined_match = map_metric_label(combined_mapping_label, config)
                snippet += "\n" + following.text
                bbox = union_bbox((bbox, following.bbox))
                if next_cells and combined_match:
                    label, mapping_label, match, cells = combined_label, combined_mapping_label, combined_match, next_cells
                    consumed = step + 1
                    continued = True
                    break
                if next_cells:
                    break  # Zahlen einer unbekannten Zeile nicht mit der nächsten Kennzahl verbinden.
        if match and cells and not (match.canonical_metric == "gross_debt" and debt_component):
            values, uncertain = _layout_values(cells, columns)
            if values:
                currency, scale = _nearby_unit(rows, index, fallback_unit)
                candidates.append(_candidate(
                    document, page, statement, match, label, values,
                    "pymupdf_layout", snippet, currency, scale, bbox=bbox,
                    uncertain=uncertain or continued, mapping_label=mapping_label,
                ))
        index += consumed
    return candidates


def _table_candidates(
    document: ExtractedDocument, page: ExtractedPage, statement: StatementPage,
    table: ExtractedTable, config: MetricConfig,
) -> list[FinancialMetricCandidate]:
    candidates: list[FinancialMetricCandidate] = []
    columns: dict[int, tuple[str, tuple]] = {}
    currency, scale = detect_currency_scale("\n".join(page.text.splitlines()[:20]))
    if page.words and table.bbox:
        rows = group_words_into_rows(page.words)
        before = [index for index, row in enumerate(rows) if row.bbox[1] < table.bbox[1]]
        if before:
            currency, scale = _nearby_unit(rows, before[-1], (None, None))
    note_columns: set[int] = set()
    half_year = _has_half_year_context(document, page)
    unsupported = _unsupported_period_context(document, page)
    debt_component = False
    for row in table.rows:
        header = {
            index: (text or "", _period_with_context(text, period, half_year, unsupported=unsupported))
            for index, text in enumerate(row)
            if text and (period := parse_period_header(text.replace("\n", " ")))
        }
        non_header_labels = [text for index, text in enumerate(row) if index not in header and text]
        if len(header) >= 2 and not any(map_metric_label(text, config) for text in non_header_labels):
            columns = header
            note_columns = {index for index, text in enumerate(row) if text and re.fullmatch(r"(?:Anhang|Notes?|Erläuterung)", text.strip(), re.IGNORECASE)}
            continue
        row_text = " ".join(text or "" for text in row)
        if any(_unit_signals(row_text)):
            currency, scale = _local_unit(row_text, (currency, scale))
        for label_index, label_cell in enumerate(row):
            if not label_cell or label_index in columns or label_index in note_columns:
                continue
            label = re.sub(r"\s+", " ", label_cell).strip()
            mapping_label = _table_mapping_label(label, columns)
            if _debt_component_heading(label):
                debt_component = True
            elif _closes_debt_component_section(label):
                debt_component = False
            match = map_metric_label(mapping_label, config)
            if match is None:
                continue
            if match.canonical_metric == "gross_debt" and debt_component:
                break
            values: list[PeriodValueCandidate] = []
            value_columns = sorted(columns) if columns else range(label_index + 1, len(row))
            for column_index in value_columns:
                if column_index in note_columns or column_index >= len(row):
                    continue
                raw = (row[column_index] or "").strip()
                try:
                    number = parse_accounting_number(raw, accounting_context=True)
                except NumberParsingError:
                    continue
                if columns:
                    column_header, (period_label, end, months) = columns[column_index]
                else:
                    column_header, period_label, end, months = None, None, None, None
                # Leerzellen bleiben None, vorhandene Perioden werden erhalten.
                values.append(PeriodValueCandidate(period_label, raw, number, column_header, end, months))
            if values and any(value.normalized_value is not None for value in values):
                candidates.append(_candidate(
                    document, page, statement, match, label, tuple(values),
                    "pdfplumber_table", " | ".join(text or "" for text in row),
                    currency, scale, bbox=table.bbox, mapping_label=mapping_label,
                ))
            break
    return candidates


def _fallback_candidates(
    document: ExtractedDocument, page: ExtractedPage, statement: StatementPage, config: MetricConfig,
) -> list[FinancialMetricCandidate]:
    """Konservativer Textkanal: ohne Koordinaten keine Spaltenperioden raten."""
    candidates: list[FinancialMetricCandidate] = []
    lines = [line.strip() for line in page.text.splitlines() if line.strip()]
    currency, scale = detect_currency_scale("\n".join(lines[:20]))
    for index, line in enumerate(lines):
        # Häufig ist ein Label allein; Zahlen folgen auf eigener Textzeile.
        label, numeric_text = line, ""
        numeric_start = re.search(r"(?<!\S)[+-]?(?:\d|\(\d)", line)
        if numeric_start:
            label = line[:numeric_start.start()].strip()
            numeric_text = line[numeric_start.start():]
        match = map_metric_label(label, config)
        if match and not numeric_text and index + 1 < len(lines):
            numeric_text = lines[index + 1]
        if match is None or not numeric_text:
            continue
        # Ganze Zelle versuchen, sonst durch breite Leerbereiche trennen. Einzelne
        # Leerzeichen bleiben mögliche Schweizer Tausendergruppierung.
        parts = re.split(r"\s{2,}|\t|\|", numeric_text)
        ambiguous_space = False
        if len(parts) == 1:
            try:
                parse_accounting_number(parts[0], accounting_context=True)
            except NumberParsingError:
                parts = numeric_text.split()
            else:
                # Ohne Positionen ist "143 150" sowohl ein gruppierter Betrag
                # als auch zwei Spaltenwerte. Keinen Zahlenwert vortäuschen.
                ambiguous_space = len(parts[0].split()) > 1
        values: list[PeriodValueCandidate] = []
        for part in parts:
            try:
                value = parse_accounting_number(part, accounting_context=True)
            except NumberParsingError:
                continue
            if ambiguous_space:
                values.append(PeriodValueCandidate(None, part.strip(), None))
                continue
            if value is not None and parse_period_header(part) is None:
                values.append(PeriodValueCandidate(None, part.strip(), value))
        if values:
            candidate = _candidate(
                document, page, statement, match, label, tuple(values),
                "text_fallback", line + "\n" + numeric_text, currency, scale,
            )
            if ambiguous_space:
                candidate = replace(candidate, confidence_reasons=candidate.confidence_reasons + (
                    "Leerzeichen können Betragsspalten oder Tausendergruppen trennen; Rohwert muss manuell geklärt werden.",
                ))
            candidates.append(candidate)
    return candidates


def rank_financial_metric_candidates(
    candidates: Sequence[FinancialMetricCandidate],
) -> tuple[FinancialMetricCandidate, ...]:
    """Sortiere alle Quellen transparent, ohne Kandidaten oder Werte zu verlieren.

    Quellentyp steht vor PDF-Seitenzahl. Innerhalb desselben Typs folgen
    Sicherheit und Extraktionsmethode; keine Werte werden gerundet.
    """
    quality = {"high": 0, "medium": 1, "low": 2}
    method_order = {"pdfplumber_table": 0, "pymupdf_layout": 1, "text_fallback": 2, "manual": 3}
    return tuple(sorted(candidates, key=lambda item: (
        item.source_priority, quality[item.confidence], method_order[item.extraction_method],
        item.page_number, item.canonical_metric, item.candidate_id,
    )))


def _deduplicate(candidates: list[FinancialMetricCandidate]) -> tuple[FinancialMetricCandidate, ...]:
    """Gleiche Werte auf derselben Seite gruppieren; Quellenabweichungen bleiben.

    Unterschiedliche Seiten bleiben als Quellalternativen sichtbar. Derselbe
    Zeilenwert aus Tabellen- und Layoutkanal erscheint nur einmal, wobei
    explizite Tabellenzellen bevorzugt werden. Verschiedene Werte bleiben.
    """
    ordered = rank_financial_metric_candidates(candidates)
    results: list[FinancialMetricCandidate] = []
    seen: set[tuple] = set()
    for candidate in ordered:
        key = (
            candidate.source_document, candidate.page_number, candidate.canonical_metric,
            candidate.is_segment, candidate.currency, candidate.scale,
            tuple((value.period_label, value.normalized_value,
                   value.raw_value if value.normalized_value is None else None)
                  for value in candidate.values),
        )
        if key not in seen:
            seen.add(key)
            results.append(candidate)
    return tuple(results)


def extract_financial_metric_candidates(
    document: ExtractedDocument, metric_config: MetricConfig,
) -> tuple[FinancialMetricCandidate, ...]:
    """Erzeuge priorisierte, prüfpflichtige Kandidaten ohne Finanzdaten-Auto-Fill."""
    statements = {item.page_number: item for item in detect_statement_pages(document, metric_config)}
    candidates: list[FinancialMetricCandidate] = []
    for page in document.pages:
        statement = statements.get(page.page_number)
        if statement is None:
            continue
        for table in page.tables:
            candidates.extend(_table_candidates(document, page, statement, table, metric_config))
        if page.words:
            candidates.extend(_layout_candidates(document, page, statement, metric_config))
        # Textfallback nur ohne Layout: ohne räumliche Struktur wäre er sonst
        # eine zusätzliche, schwächere Quelle für dieselben Zahlen.
        elif not page.tables:
            candidates.extend(_fallback_candidates(document, page, statement, metric_config))
    return _deduplicate(candidates)
