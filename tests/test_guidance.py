"""Guidance-Formen, Historienänderungen und Actual-vs-Guidance-Regeln."""

from dataclasses import replace
from datetime import date

import pytest

from research_update_assistant.calculations import calculate_period_metrics, compare_periods
from research_update_assistant.guidance import (
    GuidanceCompatibilityError,
    compare_actual_to_guidance,
    compare_guidance_snapshots,
    create_guidance_item,
)
from research_update_assistant.guidance_models import GuidanceItem, GuidanceSnapshot
from research_update_assistant.history_workspace import PeriodKey


def _snapshot(period, when, items, **changes) -> GuidanceSnapshot:
    values = dict(
        company=period.company_name,
        target_period=PeriodKey(period.period_end, period.period_months),
        as_of_date=when,
        label=f"FY2025 Guidance {when.isoformat()}",
        source_type="results_presentation",
        currency=period.currency,
        scale=period.scale,
        guidance_items=tuple(items),
        source_document="synthetic_results.pdf",
        source_page=3,
        notes="Ausschliesslich synthetische Testdaten.",
    )
    values.update(changes)
    return GuidanceSnapshot(**values)


@pytest.mark.parametrize(
    "item",
    [
        GuidanceItem("revenue", "exact", exact_value=1100),
        GuidanceItem("revenue", "min", minimum=1000),
        GuidanceItem("revenue", "max", maximum=1200),
        GuidanceItem("revenue_growth", "range", minimum=0.04, maximum=0.06),
    ],
)
def test_exact_min_max_and_range_guidance_keep_their_form(item) -> None:
    assert item.guidance_type in {"exact", "min", "max", "range"}


def test_approximate_and_qualitative_guidance_do_not_invent_precision() -> None:
    approximate = GuidanceItem("reported_free_cash_flow", "approximate", exact_value=650)
    qualitative = GuidanceItem(
        "revenue_growth", "qualitative", qualitative_direction="increase"
    )
    assert approximate.exact_value == 650
    assert approximate.guidance_type == "approximate"
    assert qualitative.qualitative_direction == "increase"


def test_range_narrowing_and_raised_lower_boundary_are_both_preserved(periods) -> None:
    period = periods["FY2025"]
    previous = _snapshot(
        period, date(2025, 3, 1),
        (GuidanceItem("revenue_growth", "range", minimum=0.04, maximum=0.06),),
    )
    current = _snapshot(
        period, date(2025, 8, 1),
        (GuidanceItem("revenue_growth", "range", minimum=0.05, maximum=0.06),),
    )
    change = compare_guidance_snapshots(current, previous).get("revenue_growth")
    assert change.changes == ("raised", "narrowed")


def test_guidance_can_be_raised_lowered_widened_or_unchanged(periods) -> None:
    period = periods["FY2025"]
    previous = _snapshot(
        period, date(2025, 3, 1),
        (
            GuidanceItem("revenue", "exact", exact_value=1000),
            GuidanceItem("ebit", "exact", exact_value=160),
            GuidanceItem("ebitda_margin", "range", minimum=0.28, maximum=0.30),
            GuidanceItem("reported_free_cash_flow", "exact", exact_value=70),
        ),
    )
    current = _snapshot(
        period, date(2025, 8, 1),
        (
            GuidanceItem("revenue", "exact", exact_value=1050),
            GuidanceItem("ebit", "exact", exact_value=150),
            GuidanceItem("ebitda_margin", "range", minimum=0.27, maximum=0.31),
            GuidanceItem("reported_free_cash_flow", "exact", exact_value=70),
        ),
    )
    comparison = compare_guidance_snapshots(current, previous)
    assert comparison.get("revenue").changes == ("raised",)
    assert comparison.get("ebit").changes == ("lowered",)
    assert comparison.get("ebitda_margin").changes == ("widened",)
    assert comparison.get("reported_free_cash_flow").changes == ("unchanged",)


def test_incompatible_guidance_forms_are_neutrally_changed(periods) -> None:
    period = periods["FY2025"]
    previous = _snapshot(
        period, date(2025, 3, 1), (GuidanceItem("revenue", "min", minimum=1000),)
    )
    current = _snapshot(
        period, date(2025, 8, 1), (GuidanceItem("revenue", "range", minimum=1000, maximum=1100),)
    )
    assert compare_guidance_snapshots(current, previous).get("revenue").changes == ("changed",)


@pytest.mark.parametrize(
    "actual_growth, expected_status",
    [(0.054, "within"), (0.065, "above"), (0.035, "below")],
)
def test_actual_can_be_inside_above_or_below_range(periods, actual_growth, expected_status) -> None:
    previous, actual = periods["FY2024"], periods["FY2025"]
    previous_revenue = actual.revenue / (1 + actual_growth)
    previous = replace(previous, revenue=previous_revenue)
    guidance = _snapshot(
        actual, date(2025, 3, 1),
        (GuidanceItem("revenue_growth", "range", minimum=0.04, maximum=0.06),),
    )
    period_comparison = compare_periods(actual, previous)
    result = compare_actual_to_guidance(
        actual, calculate_period_metrics(actual), guidance,
        period_comparison=period_comparison,
    )
    assert result.get("revenue_growth").actual_value == pytest.approx(actual_growth)
    assert result.get("revenue_growth").status == expected_status


def test_actual_respects_min_max_and_exact_boundaries(periods) -> None:
    actual = periods["FY2025"]
    guidance = _snapshot(
        actual, date(2025, 3, 1),
        (
            GuidanceItem("revenue", "exact", exact_value=1100),
            GuidanceItem("ebitda_margin", "min", minimum=0.19),
            GuidanceItem("ebit", "max", maximum=140),
        ),
    )
    result = compare_actual_to_guidance(actual, calculate_period_metrics(actual), guidance)
    assert result.get("revenue").status == "within"
    assert result.get("ebitda_margin").status == "within"
    assert result.get("ebit").status == "above"


def test_strict_above_boundary_is_preserved(periods) -> None:
    actual = replace(periods["FY2025"], ebitda=319)
    guidance = _snapshot(
        actual, date(2025, 3, 1),
        (GuidanceItem("ebitda_margin", "above", minimum=0.29),),
    )
    result = compare_actual_to_guidance(actual, calculate_period_metrics(actual), guidance)
    assert result.get("ebitda_margin").actual_value == pytest.approx(0.29)
    assert result.get("ebitda_margin").status == "below"


def test_missing_actual_and_non_numeric_guidance_are_not_assessed(periods) -> None:
    actual = replace(periods["FY2025"], reported_free_cash_flow=None)
    guidance = _snapshot(
        actual, date(2025, 3, 1),
        (
            GuidanceItem("reported_free_cash_flow", "min", minimum=60),
            GuidanceItem("revenue_growth", "qualitative", qualitative_direction="increase"),
        ),
    )
    result = compare_actual_to_guidance(actual, calculate_period_metrics(actual), guidance)
    assert result.get("reported_free_cash_flow").status == "missing_actual"
    assert result.get("revenue_growth").status == "not_assessable"


def test_missing_guidance_item_returns_none(periods) -> None:
    actual = periods["FY2025"]
    guidance = _snapshot(actual, date(2025, 3, 1), ())
    result = compare_actual_to_guidance(actual, calculate_period_metrics(actual), guidance)
    assert result.get("revenue") is None


def test_multiple_snapshots_for_same_target_remain_distinct_and_chronological(periods) -> None:
    period = periods["FY2025"]
    first = _snapshot(period, date(2025, 3, 1), ())
    second = _snapshot(period, date(2025, 8, 1), ())
    snapshots = tuple(sorted((second, first), key=lambda item: item.as_of_date))
    assert [item.as_of_date.month for item in snapshots] == [3, 8]
    assert len({item.snapshot_id for item in snapshots}) == 2


def test_wrong_actual_target_period_is_blocked(periods) -> None:
    actual = periods["FY2025"]
    guidance = _snapshot(
        actual, date(2025, 3, 1), (),
        target_period=PeriodKey(date(2024, 12, 31), 12),
    )
    with pytest.raises(GuidanceCompatibilityError, match="Zielperiode"):
        compare_actual_to_guidance(actual, calculate_period_metrics(actual), guidance)


def test_form_parser_normalizes_percentages_but_keeps_ranges(periods) -> None:
    item = create_guidance_item(
        "revenue_growth", "range", raw_minimum="4", raw_maximum="6"
    )
    assert item.minimum == pytest.approx(0.04)
    assert item.maximum == pytest.approx(0.06)
    assert item.exact_value is None
