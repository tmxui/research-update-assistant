"""Research-Regeln mit echten Perioden, Grenzwerten und fehlenden Daten prüfen."""

from dataclasses import replace
from datetime import date

import pytest

from research_update_assistant.calculations import compare_periods
from research_update_assistant.flag_config import RuleThresholds, load_flag_rules
from research_update_assistant.flags import generate_research_flags
from research_update_assistant.models import FinancialPeriod, PeriodComparison


@pytest.fixture
def rules():
    return load_flag_rules()


def _comparison(periods, *, current=None, previous=None) -> PeriodComparison:
    """Konstante Ausgangswerte; Änderungen werden durch den Finance-Kern berechnet."""
    baseline = periods["FY2024"]
    prior = replace(baseline, **(previous or {}))
    latest = replace(
        baseline, period_label="FY2025", period_end=date(2025, 12, 31),
        **(current or {}),
    )
    return compare_periods(latest, prior)


def _by_id(comparison, rules):
    return {flag.rule_id: flag for flag in generate_research_flags(comparison, rules)}


def _assert_severity(comparison, rules, rule_id, severity):
    flags = _by_id(comparison, rules)
    if severity is None:
        assert rule_id not in flags
    else:
        assert flags[rule_id].severity == severity


@pytest.mark.parametrize("revenue, severity", [
    (1000, None), (1025, None), (975, "yellow"), (900, "red"),
    (850, "red"), (900.00001, "yellow"),
])
def test_revenue_decline(periods, rules, revenue, severity):
    _assert_severity(_comparison(periods, current={"revenue": revenue}), rules, "revenue_decline", severity)


@pytest.mark.parametrize("ebit, severity", [
    (145, None), (140, "yellow"), (130, "red"), (120, "red"),
    (130.00001, "yellow"), (140.00001, None),
])
def test_ebit_margin_decline_boundaries(periods, rules, ebit, severity):
    _assert_severity(_comparison(periods, current={"ebit": ebit}), rules, "ebit_margin_decline", severity)


@pytest.mark.parametrize("ebitda, severity", [(195, None), (190, "yellow"), (180, "red")])
def test_ebitda_margin_decline(periods, rules, ebitda, severity):
    _assert_severity(_comparison(periods, current={"ebitda": ebitda}), rules, "ebitda_margin_decline", severity)


@pytest.mark.parametrize("fcf, severity", [
    (90, None), (80, "yellow"), (60, "red"), (50, "red"),
    (60.00001, "yellow"), (80.00001, None),
])
def test_free_cash_flow_decline_boundaries(periods, rules, fcf, severity):
    comparison = _comparison(periods, current={"operating_cash_flow": fcf + 60})
    _assert_severity(comparison, rules, "free_cash_flow_decline", severity)


@pytest.mark.parametrize("field, rule_id", [
    ("inventory", "inventory_growth_excess"),
    ("receivables", "receivables_growth_excess"),
])
@pytest.mark.parametrize("growth, severity", [
    (0.15, None), (0.20, "yellow"), (0.25, "yellow"),
    (0.30, "red"), (0.35, "red"),
])
def test_working_capital_growth_spreads(periods, rules, field, rule_id, growth, severity):
    value = getattr(periods["FY2024"], field) * (1 + growth)
    comparison = _comparison(periods, current={"revenue": 1100, field: value})
    _assert_severity(comparison, rules, rule_id, severity)


@pytest.mark.parametrize("ebit_growth, severity", [(0.08, None), (0.05, "yellow"), (0.0, "red"), (-0.05, "red")])
def test_ebit_growth_lag(periods, rules, ebit_growth, severity):
    comparison = _comparison(periods, current={"revenue": 1100, "ebit": 150 * (1 + ebit_growth)})
    _assert_severity(comparison, rules, "ebit_growth_lag", severity)


@pytest.mark.parametrize("revenue", [1000, 900])
def test_ebit_lag_requires_rising_revenue(periods, rules, revenue):
    comparison = _comparison(periods, current={"revenue": revenue, "ebit": 100})
    assert "ebit_growth_lag" not in _by_id(comparison, rules)


@pytest.mark.parametrize("level, severity", [(1.3, None), (1.5, "yellow"), (2.0, "red")])
def test_leverage_change(periods, rules, level, severity):
    comparison = _comparison(periods, current={"gross_debt": 100 + level * 200})
    _assert_severity(comparison, rules, "leverage_increase", severity)


@pytest.mark.parametrize("level, severity", [(2.5, None), (3.0, "yellow"), (4.0, "red")])
def test_absolute_leverage_level_without_change(periods, rules, level, severity):
    values = {"gross_debt": 100 + level * 200}
    comparison = _comparison(periods, current=values, previous=values)
    _assert_severity(comparison, rules, "leverage_level", severity)
    assert "leverage_increase" not in _by_id(comparison, rules)


def test_level_can_trigger_when_previous_leverage_is_missing(periods, rules):
    comparison = _comparison(periods, current={"gross_debt": 900}, previous={"gross_debt": None})
    flags = _by_id(comparison, rules)
    assert flags["leverage_level"].severity == "red"
    assert flags["leverage_level"].previous_value is None
    assert "leverage_increase" not in flags


@pytest.mark.parametrize("ebit_growth, ocf_growth, severity", [
    (0.1, -0.10, "yellow"), (0.1, -0.30, "red"),
    (0.0, -0.30, "red"), (0.0, -0.10, None),
    (-0.1, -0.40, None), (0.1, 0.0, None), (0.1, 0.10, None),
])
def test_cashflow_ebit_divergence(periods, rules, ebit_growth, ocf_growth, severity):
    comparison = _comparison(periods, current={
        "ebit": 150 * (1 + ebit_growth), "operating_cash_flow": 160 * (1 + ocf_growth),
    })
    _assert_severity(comparison, rules, "cashflow_ebit_divergence", severity)


def test_three_sparse_positive_observations(periods, rules):
    comparison = _comparison(periods, current={"ebit": 160, "operating_cash_flow": 180, "gross_debt": 200})
    flags = generate_research_flags(comparison, rules)
    assert [flag.rule_id for flag in flags] == [
        "ebit_margin_improvement", "free_cash_flow_improvement", "leverage_decrease",
    ]
    assert all(flag.severity == "green" for flag in flags)
    assert flags[0].change_value == pytest.approx(100)
    assert flags[1].change_value == pytest.approx(0.20)
    assert flags[2].change_value == pytest.approx(-0.5)


def test_declining_leverage_and_high_level_are_separate_and_sorted(periods, rules):
    comparison = _comparison(periods, current={"gross_debt": 900}, previous={"gross_debt": 1100})
    flags = generate_research_flags(comparison, rules)
    assert [flag.rule_id for flag in flags] == ["leverage_level", "leverage_decrease"]
    assert [flag.severity for flag in flags] == ["red", "green"]


@pytest.mark.parametrize("missing, rule_ids", [
    ("revenue", {"revenue_decline", "ebit_margin_decline", "ebitda_margin_decline", "ebit_growth_lag", "inventory_growth_excess", "receivables_growth_excess"}),
    ("ebit", {"ebit_margin_decline", "ebit_growth_lag", "cashflow_ebit_divergence"}),
    ("ebitda", {"ebitda_margin_decline", "leverage_increase", "leverage_level", "leverage_decrease"}),
    ("capex", {"free_cash_flow_decline", "free_cash_flow_improvement"}),
    ("operating_cash_flow", {"free_cash_flow_decline", "free_cash_flow_improvement", "cashflow_ebit_divergence"}),
    ("inventory", {"inventory_growth_excess"}),
    ("receivables", {"receivables_growth_excess"}),
    ("gross_debt", {"leverage_increase", "leverage_level", "leverage_decrease"}),
])
@pytest.mark.parametrize("side", ["current", "previous"])
def test_missing_values_skip_dependent_rules(periods, rules, missing, rule_ids, side):
    comparison = _comparison(periods, **{side: {missing: None}})
    assert not rule_ids.intersection(_by_id(comparison, rules))


def test_missing_margin_skips_rule_even_if_comparison_change_exists(periods, rules):
    comparison = _comparison(periods, current={"ebit": 100})
    comparison = replace(comparison, current_metrics=replace(comparison.current_metrics, ebit_margin=None))
    assert "ebit_margin_decline" not in _by_id(comparison, rules)


def test_fully_missing_financial_data_produces_no_flags(rules):
    prior = FinancialPeriod("Example AG", "FY2024", date(2024, 12, 31), 12, "CHF", "million")
    current = replace(prior, period_label="FY2025", period_end=date(2025, 12, 31))
    assert generate_research_flags(compare_periods(current, prior), rules) == []


def test_half_year_does_not_produce_any_leverage_flag(periods, rules):
    comparison = _comparison(periods, current={"period_months": 6, "gross_debt": 1000}, previous={"period_months": 6})
    assert comparison.current_metrics.calculated_net_debt_to_ebitda is None
    assert not any(flag.rule_id.startswith("leverage_") for flag in generate_research_flags(comparison, rules))
    # Auch widersprüchlich gelieferte Kennzahlen dürfen nicht annualisiert werden.
    comparison = replace(comparison, current_metrics=replace(comparison.current_metrics, calculated_net_debt_to_ebitda=4.5))
    assert "leverage_level" not in _by_id(comparison, rules)


@pytest.mark.parametrize("ebitda", [0, -100])
def test_nonpositive_ebitda_is_not_used_for_leverage_observations(periods, rules, ebitda):
    comparison = _comparison(periods, current={"ebitda": ebitda, "gross_debt": 1000})
    assert not any(flag.rule_id.startswith("leverage_") for flag in generate_research_flags(comparison, rules))


def test_reported_and_adjusted_values_do_not_replace_calculated_values(periods, rules):
    comparison = _comparison(periods, current={
        "operating_cash_flow": None, "reported_free_cash_flow": 10,
        "gross_debt": None, "reported_net_debt": 1000,
        "ebitda": None, "adjusted_ebitda": 10,
    })
    flags = _by_id(comparison, rules)
    assert "free_cash_flow_decline" not in flags
    assert "ebitda_margin_decline" not in flags
    assert "leverage_level" not in flags


@pytest.mark.parametrize("previous_fcf", [0, -100])
def test_nonpositive_fcf_base_does_not_create_misleading_growth_flags(periods, rules, previous_fcf):
    comparison = _comparison(periods, current={"operating_cash_flow": -140}, previous={"operating_cash_flow": previous_fcf + 60})
    flags = _by_id(comparison, rules)
    assert "free_cash_flow_improvement" not in flags
    assert "free_cash_flow_decline" not in flags


def test_negative_ebit_base_does_not_create_growth_lag_but_margins_remain_comparable(periods, rules):
    comparison = _comparison(periods, previous={"ebit": -150}, current={"ebit": -130, "revenue": 1100})
    flags = _by_id(comparison, rules)
    assert "ebit_growth_lag" not in flags
    assert flags["ebit_margin_improvement"].severity == "green"
    assert "-15,0 %" in flags["ebit_margin_improvement"].message


def test_changing_threshold_changes_classification_without_changing_numbers(periods, rules):
    comparison = compare_periods(periods["FY2025"], periods["FY2024"])
    modified = replace(rules, ebit_margin_decline=RuleThresholds(-100, -250))
    flag = _by_id(comparison, modified)["ebit_margin_decline"]
    assert flag.severity == "yellow"
    assert flag.threshold == -100
    assert flag.change_value == pytest.approx(-200)


def test_synthetic_workflow_has_exact_rule_ids_and_transparent_facts(periods, rules):
    comparison = compare_periods(periods["FY2025"], periods["FY2024"])
    flags = generate_research_flags(comparison, rules)
    assert [(flag.rule_id, flag.severity) for flag in flags] == [
        ("ebit_margin_decline", "red"), ("free_cash_flow_decline", "red"),
        ("ebit_growth_lag", "red"), ("inventory_growth_excess", "yellow"),
        ("receivables_growth_excess", "yellow"),
    ]
    assert all(flag.period_current == "FY2025" and flag.period_previous == "FY2024" for flag in flags)
    by_id = {flag.rule_id: flag for flag in flags}
    assert by_id["ebit_margin_decline"].current_value == pytest.approx(0.13)
    assert by_id["ebit_margin_decline"].previous_value == pytest.approx(0.15)
    assert by_id["ebit_margin_decline"].change_value == pytest.approx(-200)
    assert "15,0 % auf 13,0 %" in by_id["ebit_margin_decline"].message
    assert "200 Basispunkte" in by_id["ebit_margin_decline"].message
    assert "CHF 100 Mio. auf CHF 60 Mio." in by_id["free_cash_flow_decline"].message
    assert "40,0 %" in by_id["free_cash_flow_decline"].message
    assert "4,7 %" in by_id["ebit_growth_lag"].message
    assert "10,0 %" in by_id["ebit_growth_lag"].message
    assert "+16,7 Prozentpunkte" in by_id["inventory_growth_excess"].message
    assert "+15,0 Prozentpunkte" in by_id["receivables_growth_excess"].message
    assert "leverage_increase" not in by_id


def test_same_engine_processes_previous_synthetic_pair(periods, rules):
    flags = generate_research_flags(compare_periods(periods["FY2024"], periods["FY2023"]), rules)
    assert [(flag.rule_id, flag.severity) for flag in flags] == [("ebit_growth_lag", "yellow")]


@pytest.mark.parametrize("currency, scale, expected", [
    ("EUR", "thousand", "EUR 100 Tsd."), ("USD", "billion", "USD 100 Mrd."),
    ("CHF", "unit", "CHF 100"),
])
def test_money_messages_respect_currency_and_scale(periods, rules, currency, scale, expected):
    metadata = {"currency": currency, "scale": scale}
    comparison = _comparison(periods, current={**metadata, "operating_cash_flow": 120}, previous=metadata)
    assert expected in _by_id(comparison, rules)["free_cash_flow_decline"].message


def test_generated_flag_values_and_input_periods_remain_unrounded(periods, rules):
    comparison = compare_periods(periods["FY2025"], periods["FY2024"])
    flags = _by_id(comparison, rules)
    assert flags["ebit_growth_lag"].change_value == comparison.ebit_growth - comparison.revenue_growth
    assert comparison.current_period is periods["FY2025"]
    assert comparison.current_period.reported_free_cash_flow is None
