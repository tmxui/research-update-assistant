"""Kleine, testbare Hilfen zur logischen Rekonstruktion von PDF-Zeilen.

Koordinaten sind PDF-Punkte. Wir rekonstruieren keine originalgetreue Ansicht:
Wörter nahe derselben Grundlinie bilden eine Zeile, Jahresheader definieren
Spalten, Zahlen werden anhand ihrer rechten Kante diesen Spalten zugeordnet.
"""

from dataclasses import dataclass
from datetime import date
import re

from .candidate_models import BBox
from .document_models import ExtractedWord
from .input_parsing import NumberParsingError, parse_optional_number

# Kleine Baseline-Abweichungen kommen z.B. bei unterschiedlichen Schriftgrössen vor.
ROW_Y_TOLERANCE = 3.0
# Rechtsbündige Beträge und kurze Jahresheader haben unterschiedliche Wortbreiten.
COLUMN_X_TOLERANCE = 45.0
# Eine umgebrochene Bezeichnung darf höchstens eine typische Zeilenhöhe entfernt sein.
CONTINUATION_Y_GAP = 25.0


@dataclass(frozen=True)
class LayoutRow:
    """Eine logische Zeile mit von links nach rechts geordneten Wörtern."""

    words: tuple[ExtractedWord, ...]

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)

    @property
    def bbox(self) -> BBox:
        return (
            min(word.x0 for word in self.words), min(word.y0 for word in self.words),
            max(word.x1 for word in self.words), max(word.y1 for word in self.words),
        )


@dataclass(frozen=True)
class PeriodColumn:
    """Ein erkannter Header; seine Position entscheidet über die Zuordnung."""

    column_header: str
    period_label: str | None
    period_end: date | None
    period_months: int | None
    bbox: BBox

    @property
    def right(self) -> float:
        return self.bbox[2]


@dataclass(frozen=True)
class NumericCell:
    """Unveränderter Rohtext und ein ungerundeter Zahlenwert."""

    raw_value: str
    normalized_value: float | None
    bbox: BBox


def union_bbox(boxes: tuple[BBox, ...]) -> BBox:
    """Umfassendes Rechteck für mindestens ein Wort/eine Zelle."""
    return (
        min(box[0] for box in boxes), min(box[1] for box in boxes),
        max(box[2] for box in boxes), max(box[3] for box in boxes),
    )


def group_words_into_rows(
    words: tuple[ExtractedWord, ...], *, y_tolerance: float = ROW_Y_TOLERANCE,
) -> tuple[LayoutRow, ...]:
    """Gruppiere anhand der unteren Wortkante und sortiere die Zeilen räumlich.

    Die Gruppenanker werden nicht laufend verschoben: Eine Kette jeweils
    knapp benachbarter Wörter kann dadurch nicht zwei echte Zeilen verbinden.
    """
    if y_tolerance < 0:
        raise ValueError("Die Zeilentoleranz darf nicht negativ sein.")
    groups: list[tuple[float, list[ExtractedWord]]] = []
    for word in sorted(words, key=lambda item: (item.y1, item.x0)):
        if not word.text.strip():
            continue
        possible = [group for group in groups if abs(word.y1 - group[0]) <= y_tolerance]
        if possible:
            min(possible, key=lambda group: abs(word.y1 - group[0]))[1].append(word)
        else:
            groups.append((word.y1, [word]))
    return tuple(
        LayoutRow(tuple(sorted(group, key=lambda word: word.x0)))
        for _, group in sorted(groups, key=lambda item: item[0])
    )


def parse_accounting_number(text: str, *, accounting_context: bool = False) -> float | None:
    """Nutze Schweizer Zahlenformate; Klammern sind nur in Zahlenzellen erlaubt.

    Gedankenstriche/Leerzellen bedeuten fehlend, niemals null. Ein Text wie
    ``(EBITDA)`` wird auch im Tabellenkontext niemals zur Zahl.
    """
    value = text.strip().replace("−", "-")
    if value in ("", "–", "—", "-"):
        return None
    if value.startswith("(") and value.endswith(")"):
        if not accounting_context:
            raise NumberParsingError("Klammern benötigen einen numerischen Tabellenkontext.")
        number = parse_optional_number(value[1:-1].strip())
        if number is None or number < 0:
            raise NumberParsingError("Ungültige Accounting-Zahl in Klammern.")
        return -number
    return parse_optional_number(value)


def parse_period_header(text: str) -> tuple[str, date | None, int | None] | None:
    """Erkenne Jahres-/H1-Header und vollständige Stichtage, keine Quartalsmixe.

    Ein Jahresheader ist ein FY-Vorschlag (12 Monate). Ein H1-Header ist ein
    Sechsmonatsvorschlag. Andere Stichtage haben bewusst keine Monatsdauer.
    Sämtliche vorgeschlagenen Metadaten müssen später bestätigt werden.
    """
    value = re.sub(r"\s+", " ", text.strip())
    annual = re.fullmatch(r"(?:FY\s*)?(20\d{2})", value, re.IGNORECASE)
    if annual:
        year = int(annual.group(1))
        return f"FY{year}", date(year, 12, 31), 12
    half = re.fullmatch(r"(?:H1\s*|1\.?\s*(?:Halbjahr|Half)\s*)(20\d{2})", value, re.IGNORECASE)
    if half:
        year = int(half.group(1))
        return f"H1 {year}", date(year, 6, 30), 6
    numeric = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](20\d{2})", value)
    english = re.fullmatch(r"(\d{1,2}) (December|June|Dezember|Juni) (20\d{2})", value, re.IGNORECASE)
    if numeric:
        day, month, year = map(int, numeric.groups())
    elif english:
        day, year = int(english.group(1)), int(english.group(3))
        month = 12 if english.group(2).casefold() in ("december", "dezember") else 6
    else:
        return None
    try:
        end = date(year, month, day)
    except ValueError:
        return None
    if (month, day) == (12, 31):
        return f"FY{year}", end, 12
    # Ein Bilanzstichtag alleine beweist noch keine Sechsmonatsperiode.
    return end.isoformat(), end, None


def period_columns_in_row(row: LayoutRow) -> tuple[PeriodColumn, ...]:
    """Erkenne Header aus bis zu drei zusammengehörigen Wörtern."""
    columns: list[PeriodColumn] = []
    index = 0
    while index < len(row.words):
        found = None
        # Vollständiges Datum/H1 hat Vorrang vor dem darin enthaltenen Jahr.
        for length in (3, 2, 1):
            words = row.words[index:index + length]
            if len(words) != length:
                continue
            if any(right.x0 - left.x1 > 25 for left, right in zip(words, words[1:])):
                continue
            header = " ".join(word.text for word in words)
            period = parse_period_header(header)
            if period is not None:
                found = (length, header, period, words)
                break
        if found:
            length, header, (label, end, months), words = found
            columns.append(PeriodColumn(header, label, end, months, union_bbox(tuple(
                (word.x0, word.y0, word.x1, word.y1) for word in words
            ))))
            index += length
        else:
            index += 1
    # Eine isolierte Jahreszahl im Fliesstext ist noch kein Spaltenheader.
    if len(columns) < 2 or len({column.period_label for column in columns}) != len(columns):
        return ()
    # Eine Kennzahlenzeile mit Beträgen 2025 / 2024 ist kein Header.
    # Nur kurze Überschriften/Notizspalten zusätzlich zu den Jahresangaben zulassen.
    used_words = sum(len(column.column_header.split()) for column in columns)
    if len(row.words) - used_words > 4:
        return ()
    leftovers = row.text
    for column in columns:
        leftovers = leftovers.replace(column.column_header, "", 1)
    # Nur generische Tabellenkopf-Wörter dürfen neben den Jahren stehen.
    # Insbesondere können Beträge zufällig selbst 2025 / 2024 lauten.
    allowed = {"bezeichnung", "kennzahl", "anhang", "note", "notes", "jahr", "year",
               "periode", "period", "vorjahr", "aktuelles", "in", "chf", "eur",
               "usd", "mchf", "meur", "musd", "tchf", "teur", "tusd",
               "mio", "millionen", "million", "mrd", "tsd", "tausend"}
    if any(word.casefold() not in allowed for word in re.findall(r"[\w]+", leftovers)):
        return ()
    return tuple(columns)


def detect_period_columns(rows: tuple[LayoutRow, ...]) -> tuple[PeriodColumn, ...]:
    """Liefere das erste plausible Mehrperioden-Headerpaar einer Seite."""
    return next((columns for row in rows if (columns := period_columns_in_row(row))), ())


def extract_numeric_cells(row: LayoutRow) -> tuple[NumericCell, ...]:
    """Verbinde eng benachbarte Zahlenteile, z.B. ``1 234,5``.

    Wörter aus unterschiedlichen Betragsspalten werden nicht zusammengefasst.
    Vorzeichen/Accounting-Klammern gelten ausschliesslich für Zahlenzellen.
    """
    cells: list[NumericCell] = []
    index = 0
    while index < len(row.words):
        best: tuple[int, NumericCell] | None = None
        for length in (4, 3, 2, 1):
            words = row.words[index:index + length]
            if len(words) != length or any(
                right.x0 - left.x1 > 8 for left, right in zip(words, words[1:])
            ):
                continue
            raw = " ".join(word.text for word in words)
            try:
                value = parse_accounting_number(raw, accounting_context=True)
            except NumberParsingError:
                continue
            if value is None:
                continue
            best = (length, NumericCell(raw, value, union_bbox(tuple(
                (word.x0, word.y0, word.x1, word.y1) for word in words
            ))))
            break
        if best is not None:
            length, cell = best
            cells.append(cell)
            index += length
        else:
            index += 1
    return tuple(cells)


def assign_cells_to_columns(
    cells: tuple[NumericCell, ...], columns: tuple[PeriodColumn, ...],
    *, x_tolerance: float = COLUMN_X_TOLERANCE,
) -> tuple[tuple[PeriodColumn, NumericCell], ...]:
    """Ordne nur räumlich plausible Zahlen zu; Anhangnummern bleiben ausserhalb.

    Bei zwei gleich nahen Spalten oder mehreren Zahlen in derselben Spalte
    wird keine sichere Zuordnung erzwungen. Die aufrufende Schicht kann die
    unzugeordneten Zellen als unsichere Alternative darstellen.
    """
    proposals: dict[int, list[NumericCell]] = {}
    for cell in cells:
        distances = sorted((abs(cell.bbox[2] - column.right), i) for i, column in enumerate(columns))
        if not distances or distances[0][0] > x_tolerance:
            continue
        if len(distances) > 1 and distances[1][0] - distances[0][0] < 2:
            continue
        proposals.setdefault(distances[0][1], []).append(cell)
    return tuple(
        (column, proposals[index][0])
        for index, column in enumerate(columns)
        if len(proposals.get(index, ())) == 1
    )
