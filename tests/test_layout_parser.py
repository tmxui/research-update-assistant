"""Räumliche Zeilen, Header, Schweizer Zahlen und explizite Toleranzen."""

from datetime import date

import pytest

from research_update_assistant.document_models import ExtractedWord
from research_update_assistant.input_parsing import NumberParsingError
from research_update_assistant.layout_parser import (
    LayoutRow, NumericCell, PeriodColumn, assign_cells_to_columns,
    detect_period_columns, extract_numeric_cells, group_words_into_rows,
    parse_accounting_number, parse_period_header, period_columns_in_row,
)


def word(text, x, y=10, width=30, block=0):
    return ExtractedWord(text, x, y, x + width, y + 10, block, 0, 0)


def test_group_words_rows_uses_positions_not_pdf_block_order():
    words = (word("2024", 500, 10, block=8), word("150", 500, 40),
             word("EBIT", 30, 40.8, block=9), word("2025", 400, 11), word("143", 400, 40))
    rows = group_words_into_rows(words)
    assert [row.text for row in rows] == ["2025 2024", "EBIT 143 150"]
    assert rows[1].bbox == (30, 40, 530, 50.8)


def test_group_rows_does_not_chain_into_another_line():
    rows = group_words_into_rows((word("a", 0, 0), word("b", 20, 2.5), word("c", 40, 5)))
    assert len(rows) == 2
    assert [row.text for row in rows] == ["a b", "c"]
    assert group_words_into_rows(()) == ()
    with pytest.raises(ValueError):
        group_words_into_rows((), y_tolerance=-1)


@pytest.mark.parametrize("header,label,end,months", [
    ("2025", "FY2025", date(2025, 12, 31), 12),
    ("FY2024", "FY2024", date(2024, 12, 31), 12),
    ("H1 2026", "H1 2026", date(2026, 6, 30), 6),
    ("31.12.2025", "FY2025", date(2025, 12, 31), 12),
    ("31 December 2024", "FY2024", date(2024, 12, 31), 12),
    ("30.06.2025", "2025-06-30", date(2025, 6, 30), None),
])
def test_parse_period_header(header, label, end, months):
    assert parse_period_header(header) == (label, end, months)


@pytest.mark.parametrize("header", ["Q3 2025", "FY20", "31.02.2025", "1'100", "2025 Umsatz", "203"])
def test_invalid_period_header_is_not_guessed(header):
    assert parse_period_header(header) is None


def test_multi_word_date_headers_group_into_columns():
    row = LayoutRow((word("31", 360, width=10), word("December", 375, width=45),
                     word("2025", 425, width=30), word("31", 490, width=10),
                     word("December", 505, width=45), word("2024", 555, width=30)))
    columns = detect_period_columns((row,))
    assert [column.period_label for column in columns] == ["FY2025", "FY2024"]
    assert columns[0].bbox == (360, 10, 455, 20)


def test_h1_split_words_and_reverse_year_columns():
    row = LayoutRow((word("H1", 360, width=12), word("2025", 377),
                     word("H1", 490, width=12), word("2026", 507)))
    columns = period_columns_in_row(row)
    assert [column.period_label for column in columns] == ["H1 2025", "H1 2026"]
    assert [column.period_months for column in columns] == [6, 6]


@pytest.mark.parametrize("unit", ["MCHF", "MEUR", "MUSD", "TCHF", "TEUR", "TUSD"])
def test_compact_units_next_to_years_are_valid_header_context(unit):
    row = LayoutRow((word(unit, 30, width=40), word("2025", 400), word("2024", 520)))
    assert [column.period_label for column in period_columns_in_row(row)] == ["FY2025", "FY2024"]


@pytest.mark.parametrize("label", ["Nettoumsatz", "Forderungen", "Inventories", "EBIT", "Eigenkapital"])
def test_financial_values_that_look_like_years_are_not_header(label):
    row = LayoutRow((word(label, 30, width=100), word("2025", 400), word("2024", 500)))
    assert period_columns_in_row(row) == ()


@pytest.mark.parametrize("raw,expected", [
    ("1’234", 1234), ("1'234", 1234), ("1 234", 1234),
    ("1’234,5", 1234.5), ("1'234.5", 1234.5), ("1 234,5", 1234.5),
    ("(123)", -123), ("-123", -123), ("−123", -123), ("–", None), ("", None),
])
def test_accounting_numeric_cell(raw, expected):
    assert parse_accounting_number(raw, accounting_context=True) == expected


@pytest.mark.parametrize("raw", ["(123)", "(EBITDA)", "(-123)", "(1foo)"])
def test_accounting_parentheses_need_numeric_context(raw):
    with pytest.raises(NumberParsingError):
        parse_accounting_number(raw)
    if raw != "(123)":
        with pytest.raises(NumberParsingError):
            parse_accounting_number(raw, accounting_context=True)


def test_numeric_groups_join_but_separate_columns_do_not():
    row = LayoutRow((word("Umsatz", 30, width=50), word("1", 400, width=6),
                     word("234,5", 410, width=30), word("1'000", 530, width=30)))
    cells = extract_numeric_cells(row)
    assert [cell.normalized_value for cell in cells] == [1234.5, 1000]
    assert cells[0].raw_value == "1 234,5"


def test_assign_columns_using_position_even_if_previous_is_left():
    columns = (PeriodColumn("2024", "FY2024", date(2024, 12, 31), 12, (400, 10, 430, 20)),
               PeriodColumn("2025", "FY2025", date(2025, 12, 31), 12, (530, 10, 560, 20)))
    cells = (NumericCell("3", 3, (300, 40, 305, 50)),
             NumericCell("1000", 1000, (402, 40, 430, 50)),
             NumericCell("1100", 1100, (532, 40, 560, 50)))
    values = assign_cells_to_columns(cells, columns)
    assert [(column.period_label, cell.normalized_value) for column, cell in values] == [("FY2024", 1000), ("FY2025", 1100)]


def test_ambiguous_column_is_not_forced():
    columns = (PeriodColumn("2024", "FY2024", None, 12, (400, 10, 430, 20)),
               PeriodColumn("2025", "FY2025", None, 12, (430, 10, 460, 20)))
    assert assign_cells_to_columns((NumericCell("143", 143, (420, 40, 445, 50)),), columns) == ()
    cells = (NumericCell("143", 143, (400, 40, 430, 50)), NumericCell("144", 144, (400, 40, 430, 50)))
    assert assign_cells_to_columns(cells, columns) == ()
