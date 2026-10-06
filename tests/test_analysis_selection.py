"""Historie, Trendfenster und genau ein Vergleich bleiben unabhängig."""

from dataclasses import replace
from datetime import date
import subprocess
import sys
from unittest.mock import Mock

import pytest

from research_update_assistant import analysis_selection as selection
from research_update_assistant.analysis_selection import (
    SelectionValidationError, analyse_selection, default_comparison_keys, period_key,
)
from research_update_assistant.flag_config import FlagConfigError, load_flag_rules
from research_update_assistant.history import FinancialHistory
from research_update_assistant.validation import ConfirmedMetricObservation


@pytest.fixture
def five_year_history(periods):
    early = tuple(
        replace(periods["FY2023"], period_label=f"FY{year}", period_end=date(year, 12, 31),
                revenue=revenue, ebit=ebit, operating_cash_flow=cashflow)
        for year, revenue, ebit, cashflow in ((2021, 800, 120, 130), (2022, 860, 130, 140))
    )
    return FinancialHistory((*reversed(tuple(periods.values())), *reversed(early)))


def _keys(history):
    return tuple(period_key(period) for period in history.periods)


def _analyse_all(history):
    previous, current = default_comparison_keys(history)
    return analyse_selection(history, _keys(history), previous, current)


def test_five_year_trend_uses_exactly_one_selected_comparison_and_flag_run(five_year_history, monkeypatch):
    compare = Mock(wraps=selection.compare_periods)
    flag_engine = Mock(wraps=selection.generate_research_flags)
    monkeypatch.setattr(selection, "compare_periods", compare)
    monkeypatch.setattr(selection, "generate_research_flags", flag_engine)
    result = _analyse_all(five_year_history)
    assert [period.period_label for period in result.history.periods] == [f"FY{year}" for year in range(2021, 2026)]
    assert len(result.metrics) == 5
    assert len(result.comparisons) == len(result.research_flags) == 1
    comparison = result.comparisons[0]
    assert comparison.previous_period.period_label == "FY2024"
    assert comparison.current_period.period_label == "FY2025"
    assert comparison.revenue_growth == pytest.approx(0.10)
    assert comparison.ebit_margin_change_bps == pytest.approx(-200)
    compare.assert_called_once_with(five_year_history.periods[-1], five_year_history.periods[-2])
    flag_engine.assert_called_once()
    assert all(flag.period_previous == "FY2024" and flag.period_current == "FY2025" for flag in result.research_flags[0])


@pytest.mark.parametrize("count", [2, 3, 5])
def test_arbitrary_trend_selection_preserves_full_stored_history(five_year_history, count):
    original = five_year_history.periods
    keys = _keys(five_year_history)
    selected = tuple(reversed(keys[-count:]))
    result = analyse_selection(five_year_history, selected, keys[-2], keys[-1])
    assert len(result.history.periods) == len(result.metrics) == count
    assert result.history is not five_year_history
    assert result.history.periods == original[-count:]
    assert five_year_history.periods is original
    assert len(five_year_history.periods) == 5
    assert all(result_period is source_period for result_period, source_period in zip(result.history.periods, original[-count:], strict=True))


def test_two_then_five_period_analysis_does_not_destroy_other_periods(five_year_history):
    keys = _keys(five_year_history)
    short = analyse_selection(five_year_history, keys[-2:], keys[-2], keys[-1])
    full = analyse_selection(five_year_history, keys, keys[-2], keys[-1])
    assert len(short.history.periods) == 2
    assert len(full.history.periods) == len(five_year_history.periods) == 5
    assert short.comparisons == full.comparisons


def test_comparison_can_be_outside_trend_and_use_nonadjacent_periods(five_year_history):
    keys = _keys(five_year_history)
    result = analyse_selection(five_year_history, keys[:2], keys[2], keys[4])
    assert [period.period_label for period in result.history.periods] == ["FY2021", "FY2022"]
    assert result.comparisons[0].previous_period.period_label == "FY2023"
    assert result.comparisons[0].current_period.period_label == "FY2025"
    assert len(result.comparisons) == 1
    assert result.comparisons[0].revenue_growth == pytest.approx(1100 / 920 - 1)


def test_no_fixed_maximum_for_history_analysis(five_year_history):
    latest = five_year_history.periods[-1]
    later = tuple(replace(latest, period_label=f"FY{year}", period_end=date(year, 12, 31)) for year in range(2026, 2036))
    history = FinancialHistory((*five_year_history.periods, *later))
    result = _analyse_all(history)
    assert len(result.history.periods) == len(result.metrics) == 15
    assert len(result.comparisons) == 1


def test_period_identity_depends_on_end_and_duration_not_display_name(periods):
    period = periods["FY2025"]
    assert period_key(period) == "2025-12-31:12"
    assert period_key(replace(period, period_label="Jahresergebnis 2025")) == period_key(period)
    assert period_key(replace(period, period_months=6)) == "2025-12-31:6"


def test_defaults_choose_latest_compatible_annual_pair_before_newer_halfyears(periods):
    h1 = tuple(replace(periods["FY2025"], period_label=f"H1 {year}", period_end=date(year, 6, 30), period_months=6) for year in (2025, 2026))
    history = FinancialHistory((*h1, *periods.values()))
    assert default_comparison_keys(history) == ("2024-12-31:12", "2025-12-31:12")


def test_defaults_fall_back_to_latest_compatible_halfyear_pair(periods):
    h1 = tuple(replace(periods["FY2025"], period_label=f"H1 {year}", period_end=date(year, 6, 30), period_months=6) for year in (2023, 2024, 2025))
    history = FinancialHistory((*h1, periods["FY2025"]))
    assert default_comparison_keys(history) == ("2024-06-30:6", "2025-06-30:6")


def test_defaults_never_mix_period_duration_or_incompatible_units(periods):
    history = FinancialHistory((periods["FY2024"], replace(periods["FY2025"], currency="EUR")))
    assert default_comparison_keys(history) is None
    history = FinancialHistory((periods["FY2024"], replace(periods["FY2025"], period_months=6)))
    assert default_comparison_keys(history) is None
    assert default_comparison_keys(FinancialHistory()) is None
    assert default_comparison_keys(FinancialHistory((periods["FY2024"],))) is None


def test_defaults_skip_incompatible_latest_source_without_silent_conversion(periods):
    history = FinancialHistory((*periods.values(), replace(periods["FY2025"], period_label="FY2026", period_end=date(2026, 12, 31), currency="EUR")))
    assert default_comparison_keys(history) == ("2024-12-31:12", "2025-12-31:12")


def test_halfyear_trend_and_comparison_have_no_invented_leverage(periods):
    periods_h1 = tuple(replace(periods[f"FY{year}"], period_label=f"H1 {year}", period_end=date(year, 6, 30), period_months=6) for year in (2024, 2025))
    history = FinancialHistory(periods_h1)
    result = _analyse_all(history)
    assert len(result.comparisons) == 1
    assert result.comparisons[0].revenue_growth == pytest.approx(0.10)
    assert all(metrics.calculated_net_debt_to_ebitda is None for metrics in result.metrics)
    assert not any(flag.rule_id.startswith("leverage") for flag in result.research_flags[0])


def test_full_year_and_halfyear_comparison_is_rejected(periods):
    half = replace(periods["FY2025"], period_label="H1 2025", period_end=date(2025, 6, 30), period_months=6)
    history = FinancialHistory((*periods.values(), half))
    with pytest.raises(SelectionValidationError, match="Periodenlänge"):
        analyse_selection(history, _keys(FinancialHistory(tuple(periods.values()))), period_key(half), period_key(periods["FY2025"]))


@pytest.mark.parametrize("change,expected", [
    ({"currency": "EUR"}, "Währung"), ({"scale": "thousand"}, "Einheit"),
    ({"company_name": "Other AG"}, "Unternehmen"), ({"period_months": 6}, "Periodenlänge"),
])
def test_mixed_trend_metadata_is_rejected(periods, change, expected):
    history = FinancialHistory((periods["FY2024"], replace(periods["FY2025"], **change)))
    keys = _keys(history)
    with pytest.raises(SelectionValidationError, match=expected):
        analyse_selection(history, keys, keys[0], keys[1])


def test_comparison_cannot_belong_to_another_company_than_trend(five_year_history):
    foreign = tuple(replace(period, company_name="Other AG") for period in five_year_history.periods[-2:])
    history = FinancialHistory((*five_year_history.periods[:2], *foreign))
    keys = _keys(history)
    with pytest.raises(SelectionValidationError, match="Vergleich und Trend"):
        analyse_selection(history, keys[:2], keys[-2], keys[-1])


@pytest.mark.parametrize("trend", [(), ("2025-12-31:12",), "2025-12-31:12"])
def test_at_least_two_trend_periods_are_required(five_year_history, trend):
    with pytest.raises(SelectionValidationError, match="mindestens zwei"):
        analyse_selection(five_year_history, trend, "2024-12-31:12", "2025-12-31:12")


@pytest.mark.parametrize("which", ["trend", "previous", "current"])
def test_unknown_period_selection_has_readable_error(five_year_history, which):
    keys = _keys(five_year_history)
    trend, previous, current = keys, keys[-2], keys[-1]
    if which == "trend":
        trend = (*keys[:-1], "absent")
    elif which == "previous":
        previous = "absent"
    else:
        current = "absent"
    with pytest.raises(SelectionValidationError, match="nicht vorhanden"):
        analyse_selection(five_year_history, trend, previous, current)


def test_duplicate_trend_choice_is_not_silently_deduplicated(five_year_history):
    keys = _keys(five_year_history)
    with pytest.raises(SelectionValidationError, match="einmal"):
        analyse_selection(five_year_history, (keys[-1], keys[-1]), keys[-2], keys[-1])


def test_unresolved_duplicate_economic_period_requires_resolution(periods):
    duplicate = replace(periods["FY2024"], period_label="FY2024 comparative", ebit=148)
    history = FinancialHistory((*periods.values(), duplicate))
    with pytest.raises(SelectionValidationError, match="aufgelöste Finanzhistorie"):
        default_comparison_keys(history)
    with pytest.raises(SelectionValidationError, match="aufgelöste Finanzhistorie"):
        analyse_selection(history, ("2024-12-31:12", "2025-12-31:12"), "2024-12-31:12", "2025-12-31:12")


@pytest.mark.parametrize("same", [False, True])
def test_current_period_must_end_after_previous(five_year_history, same):
    keys = _keys(five_year_history)
    with pytest.raises(SelectionValidationError, match="nach der Vergleichsperiode"):
        analyse_selection(five_year_history, keys, keys[-1], keys[-1] if same else keys[-2])


def test_missing_conflicted_ebit_does_not_create_flags_or_backfill(periods):
    missing = replace(periods["FY2024"], ebit=None)
    history = FinancialHistory((periods["FY2023"], missing, periods["FY2025"]))
    result = _analyse_all(history)
    comparison = result.comparisons[0]
    assert result.metrics[1].ebit_margin is None
    assert comparison.ebit_growth is None
    assert comparison.ebit_margin_change_bps is None
    assert missing.ebit is None
    ebit_rules = {"ebit_margin_decline", "ebit_margin_improvement", "ebit_growth_lag", "cashflow_ebit_divergence"}
    assert not ebit_rules & {flag.rule_id for flag in result.research_flags[0]}


def test_missing_free_cash_flow_stays_none_between_available_values(five_year_history):
    missing = replace(five_year_history.periods[1], capex=None, reported_free_cash_flow=99)
    history = FinancialHistory((*five_year_history.periods[:1], missing, *five_year_history.periods[2:]))
    result = _analyse_all(history)
    assert result.metrics[0].calculated_free_cash_flow is not None
    assert result.metrics[1].calculated_free_cash_flow is None
    assert result.metrics[2].calculated_free_cash_flow is not None
    assert result.history.periods[1].reported_free_cash_flow == 99
    assert result.history.periods[1].capex is None


def test_explicit_rules_are_used_without_loading_other_rules(five_year_history, monkeypatch):
    rules = load_flag_rules()
    loader = Mock(side_effect=AssertionError("Konfiguration soll nicht erneut geladen werden"))
    monkeypatch.setattr(selection, "load_flag_rules", loader)
    keys = _keys(five_year_history)
    result = analyse_selection(five_year_history, keys, keys[-2], keys[-1], rules=rules)
    assert result.flag_error is None
    assert result.research_flags[0]
    loader.assert_not_called()


def test_invalid_flag_configuration_preserves_financial_analysis_without_fallback(five_year_history, monkeypatch):
    monkeypatch.setattr(selection, "load_flag_rules", Mock(side_effect=FlagConfigError("Konfiguration fehlt")))
    result = _analyse_all(five_year_history)
    assert result.flag_error == "Konfiguration fehlt"
    assert result.research_flags == ((),)
    assert len(result.metrics) == 5 and len(result.comparisons) == 1
    assert result.metrics[-1].calculated_free_cash_flow == 60


def test_optional_observations_keep_provenance_and_original_value(five_year_history):
    observation = ConfirmedMetricObservation(
        "ebit", "FY2025", 143, "CHF", "million", "changed",
        original_extracted_value=145, original_raw_value="145", source_document="AR2025.pdf", page_number=124,
    )
    keys = _keys(five_year_history)
    supplied = (observation,)
    result = analyse_selection(five_year_history, keys, keys[-2], keys[-1], observations=supplied)
    assert result.observations is supplied
    assert result.observations[0].original_value == 145
    assert result.observations[0].source_document == "AR2025.pdf"


def test_selection_module_is_independent_of_streamlit():
    script = (
        "import sys; sys.modules['streamlit'] = None; "
        "from research_update_assistant.analysis_selection import default_comparison_keys; "
        "from research_update_assistant.sample_data import load_synthetic_history; "
        "assert default_comparison_keys(load_synthetic_history()) == ('2024-12-31:12', '2025-12-31:12')"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
