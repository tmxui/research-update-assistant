"""Anzeigeformatierung von Quoten, Beträgen und fehlenden Werten."""

import pytest

from research_update_assistant.formatting import (
    format_amount, format_basis_points, format_multiple, format_percentage,
    format_currency_unit, format_money,
)


@pytest.mark.parametrize("value, expected", [
    (None, "–"), (0, "0"), (1100, "1'100"), (1100.5, "1'100.5"),
    (-80, "-80"), (1234.567, "1'234.57"),
])
def test_amount(value: float | None, expected: str) -> None:
    assert format_amount(value) == expected


def test_ratios_and_changes_format_without_mutating_values() -> None:
    value = 270 / 210
    assert format_multiple(value) == "1.29x"
    assert value == 270 / 210
    assert format_multiple(value - 1, signed=True) == "+0.29x"
    assert format_percentage(0.13) == "13.0 %"
    assert format_percentage(0.1, signed=True) == "+10.0 %"
    assert format_percentage(-0.4, signed=True) == "-40.0 %"
    assert format_basis_points(-200.00000000000017) == "-200 bps"
    assert format_basis_points(76.087) == "+76 bps"


def test_missing_ratios_are_dashes() -> None:
    assert format_percentage(None) == "–"
    assert format_multiple(None) == "–"
    assert format_basis_points(None) == "–"


@pytest.mark.parametrize("currency, scale, unit, amount", [
    ("CHF", "million", "CHF Mio.", "CHF 1'100.5 Mio."),
    ("EUR", "thousand", "EUR Tsd.", "EUR 1'100.5 Tsd."),
    ("USD", "billion", "USD Mrd.", "USD 1'100.5 Mrd."),
    ("CHF", "unit", "CHF", "CHF 1'100.5"),
])
def test_money_and_axis_units_do_not_rescale_values(currency, scale, unit, amount) -> None:
    assert format_currency_unit(currency, scale) == unit
    assert format_money(1100.5, currency, scale) == amount


def test_missing_money_and_zero_remain_distinct() -> None:
    assert format_money(None, "CHF", "million") == "–"
    assert format_money(0, "CHF", "million") == "CHF 0 Mio."
