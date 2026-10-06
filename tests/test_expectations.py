"""Business-Regeln für manuelle Erwartungen und neutrale Abweichungen."""

from dataclasses import replace
from datetime import date

import pytest

from research_update_assistant.calculations import calculate_period_metrics
from research_update_assistant.expectation_models import ExpectationSnapshot
from research_update_assistant.expectations import (
    ExpectationCompatibilityError,
    compare_actual_to_expectation,
    parse_expectation_values,
)
from research_update_assistant.history_workspace import PeriodKey


def _snapshot(period, values, **changes) -> ExpectationSnapshot:
    data = dict(
        company=period.company_name,
        target_period=PeriodKey(period.period_end, period.period_months),
        as_of_date=date(2025, 10, 1),
        label="Illustrative Testerwartungen",
        source_type="consensus",
        currency=period.currency,
        scale=period.scale,
        metric_expectations=values,
        notes="Synthetische Werte für Tests.",
    )
    data.update(changes)
    return ExpectationSnapshot(**data)


def test_amount_surprises_above_and_below_estimate(periods) -> None:
    actual = periods["FY2025"]
    comparison = compare_actual_to_expectation(
        actual,
        calculate_period_metrics(actual),
        _snapshot(actual, {"revenue": 1080, "ebit": 150}),
    )

    revenue = comparison.get("revenue")
    ebit = comparison.get("ebit")
    assert revenue.surprise_absolute == 20
    assert revenue.surprise_percent == pytest.approx(1100 / 1080 - 1)
    assert revenue.direction == "above"
    assert ebit.surprise_absolute == -7
    assert ebit.surprise_percent == pytest.approx(143 / 150 - 1)
    assert ebit.direction == "below"


def test_margin_surprise_is_percentage_point_and_basis_point_difference(periods) -> None:
    actual = periods["FY2025"]
    surprise = compare_actual_to_expectation(
        actual,
        calculate_period_metrics(actual),
        _snapshot(actual, {"ebit_margin": 0.14}),
    ).get("ebit_margin")

    assert surprise.actual_value == pytest.approx(0.13)
    assert surprise.surprise_absolute == pytest.approx(-0.01)
    assert surprise.surprise_bps == pytest.approx(-100)
    assert surprise.surprise_percent is None


def test_leverage_surprise_is_an_absolute_difference_in_x(periods) -> None:
    actual = periods["FY2025"]
    surprise = compare_actual_to_expectation(
        actual,
        calculate_period_metrics(actual),
        _snapshot(actual, {"calculated_net_debt_to_ebitda": 1.2}),
    ).get("calculated_net_debt_to_ebitda")

    assert surprise.actual_value == pytest.approx(270 / 210)
    assert surprise.surprise_absolute == pytest.approx(270 / 210 - 1.2)
    assert surprise.surprise_percent is None
    assert surprise.surprise_bps is None


def test_zero_negative_and_sign_change_have_no_percentage_surprise(periods) -> None:
    actual = replace(periods["FY2025"], net_income=5)
    comparison = compare_actual_to_expectation(
        actual,
        calculate_period_metrics(actual),
        _snapshot(actual, {"revenue": 0, "net_income": -10}),
    )

    revenue = comparison.get("revenue")
    net_income = comparison.get("net_income")
    assert revenue.surprise_absolute == 1100
    assert revenue.surprise_percent is None
    assert net_income.surprise_absolute == 15
    assert net_income.surprise_percent is None


def test_missing_estimate_stays_missing(periods) -> None:
    actual = periods["FY2025"]
    surprise = compare_actual_to_expectation(
        actual, calculate_period_metrics(actual), _snapshot(actual, {})
    ).get("reported_free_cash_flow")
    assert surprise.estimate_value is None
    assert surprise.surprise_absolute is None
    assert surprise.direction is None


@pytest.mark.parametrize(
    "change, message",
    [
        ({"target_period": PeriodKey(date(2024, 12, 31), 12)}, "Zielperiode"),
        ({"currency": "EUR"}, "Währungen"),
        ({"scale": "thousand"}, "Skalierungen"),
    ],
)
def test_incompatible_expectations_are_blocked(periods, change, message) -> None:
    actual = periods["FY2025"]
    with pytest.raises(ExpectationCompatibilityError, match=message):
        compare_actual_to_expectation(
            actual,
            calculate_period_metrics(actual),
            _snapshot(actual, {"revenue": 1075}, **change),
        )


def test_multiple_snapshots_for_one_period_remain_distinct(periods) -> None:
    actual = periods["FY2025"]
    first = _snapshot(actual, {"revenue": 1075}, label="Snapshot September")
    second = _snapshot(actual, {"revenue": 1080}, label="Snapshot Oktober")
    snapshots = (first, second)

    assert len({item.snapshot_id for item in snapshots}) == 2
    assert snapshots[0].target_period == snapshots[1].target_period
    assert snapshots[0].get("revenue") == 1075
    assert snapshots[1].get("revenue") == 1080


def test_form_parser_keeps_missing_values_and_converts_margin_percent() -> None:
    values = parse_expectation_values({"revenue": "1’075,5", "ebit_margin": "14"})
    assert values["revenue"] == 1075.5
    assert values["ebit_margin"] == pytest.approx(0.14)
    assert values["reported_free_cash_flow"] is None
