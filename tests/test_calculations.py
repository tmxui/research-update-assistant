"""Prüfe Formeln, fehlende Daten, Einheiten und den Verzicht auf Annualisierung."""

from dataclasses import fields, replace

import pytest

from research_update_assistant.calculations import (
    PeriodCompatibilityError,
    calculate_gross_debt,
    calculate_period_metrics,
    compare_periods,
    margin_change,
    margin_change_bps,
    normalize_capex,
    percentage_change,
    safe_divide,
)
from research_update_assistant.models import FinancialPeriod, SourceMetadata


@pytest.mark.parametrize(
    "numerator, denominator, expected",
    [(10, 2, 5), (0, 2, 0), (-10, 2, -5), (10, -2, -5),
     (None, 2, None), (10, None, None), (10, 0, None), (None, None, None)],
)
def test_safe_divide(numerator, denominator, expected) -> None:
    assert safe_divide(numerator, denominator) == expected


@pytest.mark.parametrize(
    "current, previous, expected",
    [(110, 100, 0.1), (100, 110, -1 / 11), (0, 100, -1),
     (-80, -100, -0.2), (10, 0, None), (None, 10, None), (10, None, None)],
)
def test_percentage_change(current, previous, expected) -> None:
    actual = percentage_change(current, previous)
    assert actual is None if expected is None else actual == pytest.approx(expected)


def test_margin_change_is_percentage_points_and_basis_points() -> None:
    assert margin_change(0.13, 0.15) == pytest.approx(-0.02)
    assert margin_change_bps(0.13, 0.15) == pytest.approx(-200)
    assert margin_change(0, 0.15) == pytest.approx(-0.15)
    assert margin_change_bps(0.15, 0) == pytest.approx(1500)


@pytest.mark.parametrize("current, previous", [(None, 0.15), (0.13, None), (None, None)])
def test_missing_margins(current, previous) -> None:
    assert margin_change(current, previous) is None
    assert margin_change_bps(current, previous) is None


@pytest.mark.parametrize("raw, expected", [(-80, 80), (80, 80), (0, 0), (None, None)])
def test_normalize_capex(raw, expected) -> None:
    assert normalize_capex(raw) == expected


@pytest.mark.parametrize(
    "current, noncurrent, expected",
    [(40, 320, 360), (0, 320, 320), (None, 320, None), (40, None, None), (None, None, None)],
)
def test_gross_debt_requires_both_components(current, noncurrent, expected) -> None:
    assert calculate_gross_debt(current, noncurrent) == expected


@pytest.mark.parametrize(
    "field_name, expected",
    [
        ("normalized_capex", 60),
        ("ebitda_margin", 0.20),
        ("ebit_margin", 0.15),
        ("net_income_margin", 0.10),
        ("calculated_free_cash_flow", 100),
        ("calculated_free_cash_flow_margin", 0.10),
        ("operating_cash_flow_to_ebitda", 0.80),
        ("calculated_free_cash_flow_to_net_income", 1),
        ("calculated_net_debt", 200),
        ("calculated_net_debt_to_ebitda", 1),
        ("calculated_operating_working_capital", 170),
        ("operating_working_capital_to_revenue", 0.17),
        ("inventory_to_revenue", 0.15),
        ("receivables_to_revenue", 0.12),
        ("capex_to_revenue", 0.06),
    ],
)
def test_full_year_metrics(periods, field_name, expected) -> None:
    metrics = calculate_period_metrics(periods["FY2024"])
    assert getattr(metrics, field_name) == pytest.approx(expected)


def test_reported_and_adjusted_values_remain_separate(periods) -> None:
    period = replace(
        periods["FY2024"], adjusted_ebitda=220, adjusted_ebit=180,
        reported_free_cash_flow=125, reported_net_debt=180,
    )
    metrics = calculate_period_metrics(period)
    assert metrics.ebitda_margin == pytest.approx(0.20)
    assert metrics.adjusted_ebitda_margin == pytest.approx(0.22)
    assert metrics.ebit_margin == pytest.approx(0.15)
    assert metrics.adjusted_ebit_margin == pytest.approx(0.18)
    assert period.reported_free_cash_flow == 125
    assert metrics.reported_free_cash_flow_margin == pytest.approx(0.125)
    assert metrics.calculated_free_cash_flow == 100
    assert period.reported_net_debt == 180
    assert metrics.calculated_net_debt == 200
    assert metrics.reported_net_debt_to_ebitda == pytest.approx(0.9)
    assert metrics.calculated_net_debt_to_ebitda == pytest.approx(1)


def test_reported_values_do_not_replace_missing_calculated_inputs(periods) -> None:
    period = replace(
        periods["FY2024"], operating_cash_flow=None, cash=None,
        reported_free_cash_flow=125, reported_net_debt=180,
    )
    metrics = calculate_period_metrics(period)
    assert metrics.calculated_free_cash_flow is None
    assert metrics.calculated_net_debt is None
    assert metrics.reported_free_cash_flow_margin == pytest.approx(0.125)
    assert metrics.reported_net_debt_to_ebitda == pytest.approx(0.9)


def test_missing_reported_and_adjusted_values_have_no_fallback(periods) -> None:
    metrics = calculate_period_metrics(periods["FY2024"])
    assert metrics.adjusted_ebitda_margin is None
    assert metrics.adjusted_ebit_margin is None
    assert metrics.reported_free_cash_flow_margin is None
    assert metrics.reported_net_debt_to_ebitda is None


def test_missing_ebitda_is_safe(periods) -> None:
    metrics = calculate_period_metrics(replace(periods["FY2024"], ebitda=None))
    assert metrics.ebitda_margin is None
    assert metrics.operating_cash_flow_to_ebitda is None
    assert metrics.calculated_net_debt_to_ebitda is None
    assert metrics.ebit_margin == pytest.approx(0.15)


def test_zero_revenue_leaves_amounts_but_no_revenue_ratios(periods) -> None:
    period = replace(
        periods["FY2024"], revenue=0, adjusted_ebitda=220,
        adjusted_ebit=180, reported_free_cash_flow=125,
    )
    metrics = calculate_period_metrics(period)
    for definition in fields(metrics):
        if definition.name.endswith("_margin") or definition.name.endswith("_to_revenue"):
            assert getattr(metrics, definition.name) is None
    assert metrics.calculated_free_cash_flow == 100
    assert metrics.calculated_net_debt == 200


def test_zero_ebitda_and_net_income_denominators(periods) -> None:
    period = replace(periods["FY2024"], ebitda=0, net_income=0, reported_net_debt=180)
    metrics = calculate_period_metrics(period)
    assert metrics.ebitda_margin == 0
    assert metrics.net_income_margin == 0
    assert metrics.operating_cash_flow_to_ebitda is None
    assert metrics.calculated_free_cash_flow_to_net_income is None
    assert metrics.calculated_net_debt_to_ebitda is None
    assert metrics.reported_net_debt_to_ebitda is None


@pytest.mark.parametrize(
    "missing_field, affected_metrics",
    [
        ("revenue", ("ebit_margin", "inventory_to_revenue", "calculated_free_cash_flow_margin")),
        ("operating_cash_flow", ("calculated_free_cash_flow", "operating_cash_flow_to_ebitda")),
        ("capex", ("calculated_free_cash_flow", "capex_to_revenue")),
        ("cash", ("calculated_net_debt", "calculated_net_debt_to_ebitda")),
        ("gross_debt", ("calculated_net_debt", "calculated_net_debt_to_ebitda")),
        ("inventory", ("calculated_operating_working_capital", "inventory_to_revenue")),
        ("receivables", ("calculated_operating_working_capital", "receivables_to_revenue")),
        ("payables", ("calculated_operating_working_capital", "operating_working_capital_to_revenue")),
        ("net_income", ("net_income_margin", "calculated_free_cash_flow_to_net_income")),
    ],
)
def test_missing_inputs_are_not_zero(periods, missing_field, affected_metrics) -> None:
    metrics = calculate_period_metrics(replace(periods["FY2024"], **{missing_field: None}))
    for name in affected_metrics:
        assert getattr(metrics, name) is None


def test_all_financial_inputs_missing(periods) -> None:
    original = periods["FY2024"]
    period = FinancialPeriod(
        company_name=original.company_name, period_label=original.period_label,
        period_end=original.period_end, period_months=12, currency="CHF", scale="million",
    )
    metrics = calculate_period_metrics(period)
    assert all(getattr(metrics, definition.name) is None for definition in fields(metrics))


def test_negative_capex_normalizes_without_mutating_period(periods) -> None:
    period = replace(periods["FY2025"], capex=-80)
    metrics = calculate_period_metrics(period)
    assert period.capex == -80
    assert metrics.normalized_capex == 80
    assert metrics.calculated_free_cash_flow == 60
    assert metrics.capex_to_revenue == pytest.approx(80 / 1100)


@pytest.mark.parametrize("months", [6, 3, 9, 18])
def test_non_annual_leverage_is_not_annualized(periods, months) -> None:
    period = replace(periods["FY2025"], period_months=months, reported_net_debt=260)
    metrics = calculate_period_metrics(period)
    assert metrics.calculated_net_debt == 270
    assert metrics.calculated_net_debt_to_ebitda is None
    assert metrics.reported_net_debt_to_ebitda is None
    assert metrics.ebitda_margin == pytest.approx(210 / 1100)


@pytest.mark.parametrize(
    "field_name, value, message",
    [("currency", "EUR", "Währung"), ("scale", "thousand", "Skalierung"),
     ("period_months", 6, "Periodenlänge"), ("company_name", "Other AG", "Unternehmen")],
)
def test_incompatible_periods_raise(periods, field_name, value, message) -> None:
    current = replace(periods["FY2025"], **{field_name: value})
    with pytest.raises(PeriodCompatibilityError, match=message):
        compare_periods(current, periods["FY2024"])


def test_current_must_be_later_than_previous(periods) -> None:
    with pytest.raises(PeriodCompatibilityError, match="nach"):
        compare_periods(periods["FY2023"], periods["FY2024"])
    with pytest.raises(PeriodCompatibilityError, match="nach"):
        compare_periods(periods["FY2024"], periods["FY2024"])


@pytest.mark.parametrize(
    "current_label, previous_label, expected",
    [
        ("FY2024", "FY2023", {
            "revenue_growth": 1000 / 920 - 1,
            "ebitda_growth": 200 / 190 - 1,
            "ebit_growth": 150 / 145 - 1,
            "net_income_growth": 100 / 95 - 1,
            "operating_cash_flow_growth": 160 / 150 - 1,
            "calculated_free_cash_flow_growth": 100 / 95 - 1,
            "inventory_growth": 150 / 140 - 1,
            "receivables_growth": 120 / 110 - 1,
            "gross_debt_growth": 300 / 280 - 1,
            "ebitda_margin_change": 0.2 - 190 / 920,
            "ebitda_margin_change_bps": (0.2 - 190 / 920) * 10000,
            "ebit_margin_change": 0.15 - 145 / 920,
            "ebit_margin_change_bps": (0.15 - 145 / 920) * 10000,
            "net_income_margin_change": 0.1 - 95 / 920,
            "net_income_margin_change_bps": (0.1 - 95 / 920) * 10000,
            "calculated_free_cash_flow_margin_change": 0.1 - 95 / 920,
            "calculated_free_cash_flow_margin_change_bps": (0.1 - 95 / 920) * 10000,
            "calculated_net_debt_to_ebitda_change": 1 - 185 / 190,
        }),
        ("FY2025", "FY2024", {
            "revenue_growth": 0.10,
            "ebitda_growth": 0.05,
            "ebit_growth": 143 / 150 - 1,
            "net_income_growth": -0.08,
            "operating_cash_flow_growth": -0.125,
            "calculated_free_cash_flow_growth": -0.40,
            "inventory_growth": 190 / 150 - 1,
            "receivables_growth": 0.25,
            "gross_debt_growth": 0.20,
            "ebitda_margin_change": 210 / 1100 - 0.2,
            "ebitda_margin_change_bps": (210 / 1100 - 0.2) * 10000,
            "ebit_margin_change": -0.02,
            "ebit_margin_change_bps": -200,
            "net_income_margin_change": 92 / 1100 - 0.1,
            "net_income_margin_change_bps": (92 / 1100 - 0.1) * 10000,
            "calculated_free_cash_flow_margin_change": 60 / 1100 - 0.1,
            "calculated_free_cash_flow_margin_change_bps": (60 / 1100 - 0.1) * 10000,
            "calculated_net_debt_to_ebitda_change": 270 / 210 - 1,
        }),
    ],
)
def test_both_year_comparisons_use_the_same_function(
    periods, current_label, previous_label, expected
) -> None:
    current = periods[current_label]
    previous = periods[previous_label]
    comparison = compare_periods(current, previous)
    assert comparison.current_period is current
    assert comparison.previous_period is previous
    for name, value in expected.items():
        assert getattr(comparison, name) == pytest.approx(value), name


def test_comparison_can_span_multiple_years_without_annualization(periods) -> None:
    comparison = compare_periods(periods["FY2025"], periods["FY2023"])
    assert comparison.revenue_growth == pytest.approx(1100 / 920 - 1)


def test_missing_comparison_values_are_safe(periods) -> None:
    current = replace(periods["FY2025"], ebitda=None, operating_cash_flow=None)
    comparison = compare_periods(current, periods["FY2024"])
    assert comparison.ebitda_growth is None
    assert comparison.ebitda_margin_change is None
    assert comparison.ebitda_margin_change_bps is None
    assert comparison.calculated_free_cash_flow_growth is None
    assert comparison.calculated_free_cash_flow_margin_change is None
    assert comparison.calculated_free_cash_flow_margin_change_bps is None
    assert comparison.calculated_net_debt_to_ebitda_change is None


def test_previous_zero_values_give_no_growth(periods) -> None:
    previous = replace(periods["FY2024"], revenue=0, ebitda=0, operating_cash_flow=60)
    comparison = compare_periods(periods["FY2025"], previous)
    assert comparison.revenue_growth is None
    assert comparison.ebitda_growth is None
    assert comparison.calculated_free_cash_flow_growth is None


def test_two_half_years_compare_but_no_leverage_change(periods) -> None:
    previous = replace(periods["FY2024"], period_months=6, reported_net_debt=190)
    current = replace(periods["FY2025"], period_months=6, reported_net_debt=260)
    comparison = compare_periods(current, previous)
    assert comparison.revenue_growth == pytest.approx(0.1)
    assert comparison.calculated_net_debt_to_ebitda_change is None
    assert comparison.reported_net_debt_to_ebitda_change is None


def test_reported_leverage_change_is_separate(periods) -> None:
    previous = replace(periods["FY2024"], reported_net_debt=180)
    current = replace(periods["FY2025"], reported_net_debt=252)
    comparison = compare_periods(current, previous)
    assert comparison.reported_net_debt_to_ebitda_change == pytest.approx(1.2 - 0.9)
    assert comparison.calculated_net_debt_to_ebitda_change == pytest.approx(270 / 210 - 1)


def test_source_metadata_does_not_affect_metrics(periods) -> None:
    original = periods["FY2024"]
    other_source = replace(original, source=SourceMetadata(
        source_document="anderer_bericht.pdf", source_page=42,
        source_label="Nettomittelfluss aus Geschäftstätigkeit – CHF Mio.",
        restated=True, user_confirmed=True,
    ))
    assert calculate_period_metrics(original) == calculate_period_metrics(other_source)
