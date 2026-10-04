"""Schweizer Zahlenformate und Übersetzung in das bestehende Finanzmodell."""

from dataclasses import replace
from datetime import date

import pytest

from research_update_assistant.input_parsing import (
    FINANCIAL_INPUT_GROUPS, InputValidationError, ManualPeriodInput,
    NumberParsingError, create_financial_period, create_manual_history,
    parse_optional_number,
)


@pytest.mark.parametrize("text, expected", [
    ("1100", 1100), ("1'100", 1100), ("1’100", 1100), ("1 100", 1100),
    ("1100.5", 1100.5), ("1100,5", 1100.5), ("1'100.5", 1100.5),
    ("1’100,5", 1100.5), ("1\u00a0100", 1100), ("1\u202f100", 1100),
    ("1'100'000,50", 1100000.5), ("  -1’100,5  ", -1100.5),
    ("+80", 80), ("-80", -80), ("0", 0), ("0,0", 0),
    ("", None), (" \t\n ", None),
])
def test_parse_optional_number(text: str, expected: float | None) -> None:
    value = parse_optional_number(text)
    if expected is None:
        assert value is None
    else:
        assert value == pytest.approx(expected)


@pytest.mark.parametrize("text", [
    "abc", "CHF 1100", "1,100.5", "1.100,5", "1,2,3", "11'00", "1 10",
    "1  100", "1'100 000", "1'1000", "'100", "1'100,", "1e3",
    "nan", "inf", "--80", "12-3", "1\t100", "9" * 400,
])
def test_invalid_or_ambiguous_numbers_are_rejected(text: str) -> None:
    with pytest.raises(NumberParsingError):
        parse_optional_number(text)


@pytest.fixture
def manual_period() -> ManualPeriodInput:
    return ManualPeriodInput(
        "FY2025", date(2025, 12, 31),
        values={"revenue": "1’100,5", "ebit": "143", "capex": "-80"},
    )


def test_manual_period_creation(manual_period: ManualPeriodInput) -> None:
    period = create_financial_period(" Synthetic Industrial AG ", "CHF", "million", manual_period)
    assert period.company_name == "Synthetic Industrial AG"
    assert period.period_end == date(2025, 12, 31)
    assert period.revenue == 1100.5
    assert period.ebit == 143
    assert period.capex == -80  # Parsing normalisiert keinen Capex.
    assert period.ebitda is None
    assert period.source is None


def test_every_financial_input_is_transferred(manual_period: ManualPeriodInput) -> None:
    values = {
        name: "25,5" for _, definitions in FINANCIAL_INPUT_GROUPS for name, _ in definitions
    }
    period = create_financial_period("Example AG", "USD", "billion", replace(manual_period, values=values))
    for name in values:
        assert getattr(period, name) == 25.5
    assert period.currency == "USD"
    assert period.scale == "billion"


def test_invalid_number_error_identifies_field_and_period(manual_period: ManualPeriodInput) -> None:
    raw = replace(manual_period, values={"ebit": "keine Zahl"})
    with pytest.raises(InputValidationError, match="EBIT in FY2025"):
        create_financial_period("Example AG", "CHF", "million", raw)


@pytest.mark.parametrize("company, currency, scale, message", [
    (" ", "CHF", "million", "Unternehmensnamen"),
    ("AG", "", "million", "Währung"), ("AG", "GBP", "million", "Währung"),
    ("AG", "CHF", "", "Einheit"), ("AG", "CHF", "invalid", "Einheit"),
])
def test_company_metadata_validation(manual_period, company, currency, scale, message) -> None:
    with pytest.raises(InputValidationError, match=message):
        create_financial_period(company, currency, scale, manual_period)


@pytest.mark.parametrize("changes, message", [
    ({"period_label": " "}, "Periodenbezeichnung"),
    ({"period_end": None}, "Stichtag"),
    ({"period_end": "2025-12-31"}, "Stichtag"),
    ({"period_months": 0}, "Monatsanzahl"),
    ({"period_months": 6.5}, "Monatsanzahl"),
])
def test_period_metadata_validation(manual_period, changes, message) -> None:
    with pytest.raises(InputValidationError, match=message):
        create_financial_period("AG", "CHF", "million", replace(manual_period, **changes))


def test_manual_history_sorts_dates(manual_period: ManualPeriodInput) -> None:
    raw = [
        manual_period,
        replace(manual_period, period_label="FY2023", period_end=date(2023, 12, 31)),
        replace(manual_period, period_label="FY2024", period_end=date(2024, 12, 31)),
    ]
    history = create_manual_history("AG", "CHF", "million", raw)
    assert [period.period_label for period in history.periods] == ["FY2023", "FY2024", "FY2025"]


@pytest.mark.parametrize("duplicate_label", ["FY2025", " FY2025 ", "fy2025"])
def test_manual_form_rejects_duplicate_labels(manual_period, duplicate_label) -> None:
    second = replace(manual_period, period_label=duplicate_label, period_end=date(2024, 12, 31))
    with pytest.raises(InputValidationError, match="unterschiedlich"):
        create_manual_history("AG", "CHF", "million", [manual_period, second])


def test_manual_history_requires_two_or_three_periods(manual_period: ManualPeriodInput) -> None:
    with pytest.raises(InputValidationError, match="zwei oder drei"):
        create_manual_history("AG", "CHF", "million", [manual_period])
