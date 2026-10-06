"""Präsentations-Snapshot aus vorhandenen synthetischen Finanzberechnungen."""

from dataclasses import FrozenInstanceError, replace
from datetime import date
from unittest.mock import Mock

import pytest

from research_update_assistant.calculations import calculate_period_metrics, compare_periods
from research_update_assistant.flag_config import load_flag_rules
from research_update_assistant.flags import generate_research_flags
from research_update_assistant.history import FinancialHistory
from research_update_assistant.history_workspace import MetricObservation, PeriodMetricResolution, period_key_for
from research_update_assistant.models import FinancialPeriod
from research_update_assistant.results_update import ResultsUpdateError, build_results_update
from research_update_assistant.sample_data import load_synthetic_history
from research_update_assistant.validation import ConfirmedMetricObservation


def sample_periods():
    return load_synthetic_history().periods[-2:]


def build(current=None, previous=None, *, history=None, flags=None, **kwargs):
    base, latest = sample_periods()
    current, previous = current or latest, previous or base
    comparison = compare_periods(current, previous)
    trend = history or FinancialHistory((previous, current))
    metrics = tuple(calculate_period_metrics(period) for period in trend.periods)
    return build_results_update(trend, metrics, comparison, flags or (), **kwargs)


def cards(snapshot):
    return {card.metric_id: card for card in snapshot.headline_metrics}


def observation(metric, period, value, *, document="synthetic-report.pdf", page=2):
    return ConfirmedMetricObservation(
        metric, period.period_label, value, period.currency, period.scale, "confirmed",
        original_extracted_value=value, original_raw_value=str(value),
        original_canonical_metric=metric, original_period_label=period.period_label,
        original_currency=period.currency, original_scale=period.scale,
        source_document=document, page_number=page, reported_label=metric,
        source_snippet=f"{metric} {value}", extraction_method="pymupdf_layout",
    )


def resolution(period, metric, values, *, status="unresolved", selected=None):
    items = tuple(MetricObservation(f"{metric}-{period.period_label}-{index}", f"report-{index}",
                                    period_key_for(period), observation(metric, period, value, document=f"report-{index}.pdf"))
                  for index, value in enumerate(values))
    return PeriodMetricResolution(period_key_for(period), metric, items, status,
                                  items[selected].observation_id if selected is not None else None)


def five_years():
    previous, current = sample_periods()
    extra = tuple(replace(previous, period_label=f"FY{year}", period_end=date(year, 12, 31), revenue=800 + year - 2021)
                  for year in range(2021, 2024))
    return FinancialHistory((*extra, previous, current))


def test_snapshot_uses_existing_pair_values_deltas_and_maximum_seven_cards():
    previous, current = sample_periods()
    comparison = compare_periods(current, previous)
    snapshot = build()
    assert snapshot.company_name == current.company_name
    assert snapshot.current_period is current or snapshot.current_period == current
    assert snapshot.base_period == previous
    assert [item.metric_id for item in snapshot.headline_metrics] == [
        "revenue", "ebitda", "ebit_margin", "operating_cash_flow", "calculated_free_cash_flow",
        "calculated_net_debt", "calculated_net_debt_to_ebitda",
    ]
    headline = cards(snapshot)
    assert headline["revenue"].current_value == 1100
    assert headline["revenue"].delta == comparison.revenue_growth
    assert headline["ebitda"].delta == comparison.ebitda_growth
    assert headline["ebit_margin"].current_value == pytest.approx(0.13)
    assert headline["ebit_margin"].delta == comparison.ebit_margin_change_bps
    assert headline["operating_cash_flow"].delta == comparison.operating_cash_flow_growth
    assert headline["calculated_free_cash_flow"].current_value == 60
    assert headline["calculated_net_debt"].current_value == 270
    assert headline["calculated_net_debt_to_ebitda"].delta == comparison.calculated_net_debt_to_ebitda_change
    assert len(snapshot.key_changes) <= 7


@pytest.mark.parametrize("count", [2, 3, 5])
def test_trend_context_copies_all_selected_periods_and_metrics_without_changing_pair(count):
    full = five_years()
    trend = FinancialHistory(full.periods[-count:])
    previous, current = full.periods[-2:]
    metrics = tuple(calculate_period_metrics(period) for period in trend.periods)
    comparison = compare_periods(current, previous)
    snapshot = build_results_update(trend, metrics, comparison, ())
    assert len(snapshot.trend_periods) == len(snapshot.trend_metrics) == count
    assert snapshot.trend_periods == trend.periods
    assert snapshot.trend_metrics == metrics
    assert snapshot.current_period.period_label == "FY2025"
    assert snapshot.base_period.period_label == "FY2024"
    assert cards(snapshot)["revenue"].delta == comparison.revenue_growth


def test_older_comparison_pair_does_not_use_latest_trend_period_for_any_headline():
    history = five_years()
    previous, current = history.periods[-3:-1]
    comparison = compare_periods(current, previous)
    metrics = tuple(calculate_period_metrics(period) for period in history.periods)
    snapshot = build_results_update(history, metrics, comparison, ())
    assert snapshot.current_period.period_label == "FY2024"
    assert snapshot.base_period.period_label == "FY2023"
    assert cards(snapshot)["revenue"].current_value == current.revenue == 1000
    assert cards(snapshot)["revenue"].delta == comparison.revenue_growth
    assert all(card.current_period_label == "FY2024" and card.base_period_label == "FY2023" for card in snapshot.headline_metrics)
    assert snapshot.trend_periods[-1].period_label == "FY2025"


def test_ebit_fallback_is_explicit_when_ebitda_is_missing():
    previous, current = sample_periods()
    snapshot = build(replace(current, ebitda=None))
    assert "ebitda" not in cards(snapshot)
    assert cards(snapshot)["ebit"].label_de == "EBIT"
    assert cards(snapshot)["ebit"].current_value == 143
    assert cards(snapshot)["ebit"].delta == compare_periods(replace(current, ebitda=None), previous).ebit_growth
    assert "calculated_net_debt_to_ebitda" not in cards(snapshot)


def test_both_result_values_missing_omits_profit_card():
    _, current = sample_periods()
    snapshot = build(replace(current, ebitda=None, ebit=None))
    assert not {"ebitda", "ebit", "ebit_margin"} & set(cards(snapshot))


def test_reported_fcf_preferred_with_separate_correct_label_and_same_variant_delta():
    previous, current = sample_periods()
    previous = replace(previous, reported_free_cash_flow=613, operating_cash_flow=847.6, capex=195.3)
    current = replace(current, reported_free_cash_flow=658.6, operating_cash_flow=866.9, capex=164.9)
    snapshot = build(current, previous)
    card = cards(snapshot)["reported_free_cash_flow"]
    assert card.label_de == "Ausgewiesener FCF"
    assert card.current_value == 658.6
    assert calculate_period_metrics(current).calculated_free_cash_flow == 702
    assert card.delta == pytest.approx(658.6 / 613 - 1)
    assert "calculated_free_cash_flow" not in cards(snapshot)


def test_current_reported_fcf_missing_uses_calculated_variant_for_both_periods():
    previous, current = sample_periods()
    snapshot = build(current, replace(previous, reported_free_cash_flow=95))
    card = cards(snapshot)["calculated_free_cash_flow"]
    assert card.label_de == "Berechneter FCF"
    assert card.current_value == 60
    assert card.delta == pytest.approx(60 / 100 - 1)


def test_current_reported_fcf_with_missing_reported_base_does_not_mix_calculated_base():
    _, current = sample_periods()
    snapshot = build(replace(current, reported_free_cash_flow=58))
    card = cards(snapshot)["reported_free_cash_flow"]
    assert card.current_value == 58
    assert card.delta is None and card.formatted_delta is None
    assert not any(change.metric_id == "reported_free_cash_flow" for change in snapshot.key_changes)


def test_no_fcf_data_does_not_create_a_card():
    _, current = sample_periods()
    snapshot = build(replace(current, operating_cash_flow=None, capex=None, reported_free_cash_flow=None))
    assert "calculated_free_cash_flow" not in cards(snapshot)
    assert "reported_free_cash_flow" not in cards(snapshot)


def test_reported_debt_card_does_not_change_canonical_precalculated_leverage():
    previous, current = sample_periods()
    snapshot = build(replace(current, reported_net_debt=250), replace(previous, reported_net_debt=190))
    headline = cards(snapshot)
    assert headline["reported_net_debt"].label_de == "Ausgewiesene Nettoverschuldung"
    assert headline["reported_net_debt"].current_value == 250
    assert headline["reported_net_debt"].delta == pytest.approx(250 / 190 - 1)
    prepared = compare_periods(current, previous)
    leverage = headline["calculated_net_debt_to_ebitda"]
    assert leverage.label_de == "Net Debt / EBITDA (berechnet)"
    assert leverage.current_value == prepared.current_metrics.calculated_net_debt_to_ebitda
    assert leverage.delta == prepared.calculated_net_debt_to_ebitda_change
    assert "calculated_net_debt" not in headline
    assert "reported_net_debt_to_ebitda" not in headline


def test_missing_reported_debt_in_base_does_not_mix_calculated_previous_debt():
    _, current = sample_periods()
    snapshot = build(replace(current, reported_net_debt=250))
    assert cards(snapshot)["reported_net_debt"].delta is None
    assert cards(snapshot)["calculated_net_debt_to_ebitda"].delta == compare_periods(current, sample_periods()[0]).calculated_net_debt_to_ebitda_change
    assert "reported_net_debt_to_ebitda" not in cards(snapshot)


def test_reported_net_debt_without_gross_debt_does_not_create_leverage():
    previous, current = sample_periods()
    previous = replace(previous, reported_net_debt=965.4, ebitda=912.6, gross_debt=None)
    current = replace(current, reported_net_debt=769, ebitda=930.6, gross_debt=None)
    prepared = compare_periods(current, previous)
    assert prepared.current_metrics.calculated_net_debt_to_ebitda is None
    # Die bestehende Finance-Schicht kennt diese andere Ratio-Variante bereits.
    # Das Ergebnis-Update darf sie trotzdem nicht als Ersatz verwenden.
    assert prepared.current_metrics.reported_net_debt_to_ebitda == pytest.approx(769 / 930.6)
    snapshot = build(current, previous)
    assert cards(snapshot)["reported_net_debt"].label_de == "Ausgewiesene Nettoverschuldung"
    assert cards(snapshot)["reported_net_debt"].current_value == 769
    assert not any(item.metric_id.endswith("_to_ebitda") for item in snapshot.headline_metrics)
    assert not any(item.metric_id.endswith("_to_ebitda") for item in snapshot.key_changes)


def test_canonical_leverage_does_not_fall_back_to_reported_when_prepared_value_is_missing():
    previous, current = sample_periods()
    current = replace(current, reported_net_debt=769, ebitda=930.6)
    comparison = compare_periods(current, previous)
    comparison = replace(
        comparison,
        current_metrics=replace(comparison.current_metrics, calculated_net_debt_to_ebitda=None),
        calculated_net_debt_to_ebitda_change=None,
    )
    history = FinancialHistory((previous, current))
    snapshot = build_results_update(
        history, (comparison.previous_metrics, comparison.current_metrics), comparison, (),
    )
    assert comparison.current_metrics.reported_net_debt_to_ebitda is not None
    assert "reported_net_debt" in cards(snapshot)
    assert not any(item.metric_id.endswith("_to_ebitda") for item in snapshot.headline_metrics)


def test_no_debt_data_does_not_create_debt_or_leverage_cards():
    _, current = sample_periods()
    snapshot = build(replace(current, gross_debt=None, cash=None))
    assert not {"calculated_net_debt", "reported_net_debt", "calculated_net_debt_to_ebitda"} & set(cards(snapshot))


@pytest.mark.parametrize("field,metric_id", [
    ("revenue", "revenue"), ("ebitda", "ebitda"), ("operating_cash_flow", "operating_cash_flow"),
    ("reported_free_cash_flow", "reported_free_cash_flow"), ("reported_net_debt", "reported_net_debt"),
])
def test_real_zero_current_values_are_retained(field, metric_id):
    _, current = sample_periods()
    snapshot = build(replace(current, **{field: 0}))
    assert cards(snapshot)[metric_id].current_value == 0
    assert cards(snapshot)[metric_id].formatted_value.startswith("CHF 0")


@pytest.mark.parametrize("base", [0, -1, -100])
@pytest.mark.parametrize("field,metric_id", [
    ("revenue", "revenue"), ("ebitda", "ebitda"), ("operating_cash_flow", "operating_cash_flow"),
    ("reported_free_cash_flow", "reported_free_cash_flow"), ("reported_net_debt", "reported_net_debt"),
])
def test_nonpositive_bases_suppress_percentage_presentation_only(field, metric_id, base):
    previous, current = sample_periods()
    if field.startswith("reported_"):
        current = replace(current, **{field: 60})
    previous = replace(previous, **{field: base})
    snapshot = build(current, previous)
    card = cards(snapshot)[metric_id]
    assert card.delta is None and card.formatted_delta is None
    assert card.current_value == getattr(current, field)
    assert not any(change.metric_id == metric_id for change in snapshot.key_changes)


def test_margin_delta_is_existing_basis_points_not_relative_percentage():
    snapshot = build()
    card = cards(snapshot)["ebit_margin"]
    assert card.current_value == pytest.approx(0.13)
    assert card.delta == pytest.approx(-200)
    assert card.formatted_value == "13.0 %"
    assert card.formatted_delta == "-200 bps"
    assert card.change_type == "bps"
    assert next(change for change in snapshot.key_changes if change.metric_id == "ebit_margin").text == "EBIT-Marge -200 bps"


def test_leverage_delta_is_an_absolute_x_difference():
    card = cards(build())["calculated_net_debt_to_ebitda"]
    assert card.current_value == pytest.approx(270 / 210)
    assert card.delta == pytest.approx(270 / 210 - 1)
    assert card.formatted_delta == "+0.29x"
    assert card.change_type == "multiple"


def test_h1_omits_leverage_without_artificial_annualization():
    previous, current = sample_periods()
    previous = replace(previous, period_label="H1 2024", period_end=date(2024, 6, 30), period_months=6, reported_net_debt=190)
    current = replace(current, period_label="H1 2025", period_end=date(2025, 6, 30), period_months=6, reported_net_debt=250)
    snapshot = build(current, previous)
    assert not any(card.metric_id.endswith("to_ebitda") for card in snapshot.headline_metrics)
    assert cards(snapshot)["reported_net_debt"].current_value == 250


def test_key_changes_have_fixed_neutral_priority_when_no_flag_references_exist():
    snapshot = build()
    assert [item.metric_id for item in snapshot.key_changes] == [
        "revenue", "ebit", "ebit_margin", "operating_cash_flow", "calculated_free_cash_flow",
        "calculated_net_debt_to_ebitda", "inventory",
    ]
    assert all("gut" not in item.text and "schlecht" not in item.text for item in snapshot.key_changes)
    assert len(snapshot.key_changes) == 7


def test_existing_flag_reference_can_promote_receivables_without_new_financial_interpretation():
    previous, current = sample_periods()
    comparison = compare_periods(current, previous)
    flags = tuple(generate_research_flags(comparison, load_flag_rules()))
    snapshot = build(current, previous, flags=flags)
    changes = {change.metric_id: index for index, change in enumerate(snapshot.key_changes)}
    assert "receivables" in changes
    assert changes["receivables"] < changes["revenue"]
    assert all(item in flags for item in snapshot.flags)
    assert snapshot.flags == tuple(sorted(flags, key=lambda flag: {"red": 0, "yellow": 1, "green": 2}[flag.severity]))


def test_flags_are_passed_through_as_original_objects_sorted_by_severity():
    previous, current = sample_periods()
    flags = tuple(generate_research_flags(compare_periods(current, previous), load_flag_rules()))
    snapshot = build(flags=tuple(reversed(flags)))
    assert len(snapshot.flags) == len(flags)
    assert all(any(result is source for source in flags) for result in snapshot.flags)
    assert [flag.severity for flag in snapshot.flags] == sorted([flag.severity for flag in flags], key={"red": 0, "yellow": 1, "green": 2}.get)


def test_wrong_pair_flags_are_rejected_instead_of_showing_old_session_flags():
    previous, current = sample_periods()
    flags = tuple(generate_research_flags(compare_periods(current, previous), load_flag_rules()))
    with pytest.raises(ResultsUpdateError, match="Vergleichspaar"):
        build(flags=(replace(flags[0], period_previous="FY2023"),))


def test_stale_flag_values_even_in_same_named_pair_are_rejected():
    previous, current = sample_periods()
    flags = tuple(generate_research_flags(compare_periods(current, previous), load_flag_rules()))
    with pytest.raises(ResultsUpdateError, match="veralteten"):
        build(flags=(replace(flags[0], current_value=123456),))


def test_stale_flag_delta_even_with_unchanged_pair_values_is_rejected():
    previous, current = sample_periods()
    flags = tuple(generate_research_flags(compare_periods(current, previous), load_flag_rules()))
    margin_flag = next(flag for flag in flags if flag.metric_name == "ebit_margin_change_bps")
    with pytest.raises(ResultsUpdateError, match="veraltete Vergleichsveränderung"):
        build(flags=(replace(margin_flag, change_value=-999),))


@pytest.mark.parametrize("role", ["current", "base"])
def test_old_margin_flag_is_rejected_when_its_input_resolution_is_open(role):
    previous, current = sample_periods()
    flags = tuple(generate_research_flags(compare_periods(current, previous), load_flag_rules()))
    margin_flag = next(flag for flag in flags if flag.metric_name == "ebit_margin_change_bps")
    period = current if role == "current" else previous
    with pytest.raises(ResultsUpdateError, match="ungeklärten historischen Wert"):
        build(flags=(margin_flag,), resolutions=(resolution(period, "ebit", (period.ebit, period.ebit + 1)),))


def test_unrelated_valid_flag_is_not_rejected_for_an_open_cash_input():
    previous, current = sample_periods()
    flags = tuple(generate_research_flags(compare_periods(current, previous), load_flag_rules()))
    margin_flag = next(flag for flag in flags if flag.metric_name == "ebit_margin_change_bps")
    snapshot = build(flags=(margin_flag,), resolutions=(resolution(current, "cash", (90, 95)),))
    assert snapshot.flags == (margin_flag,)
    assert snapshot.conflicts


def test_flag_configuration_error_is_preserved_without_replacement_flags():
    snapshot = build(flag_error="Die Regelkonfiguration konnte nicht geladen werden.")
    assert snapshot.flag_error == "Die Regelkonfiguration konnte nicht geladen werden."
    assert snapshot.flags == ()


def test_current_unresolved_revenue_hides_raw_and_dependent_margin_even_with_stale_pair_data():
    _, current = sample_periods()
    unresolved = resolution(current, "revenue", (1100, 1090))
    snapshot = build(resolutions=(unresolved,))
    assert "revenue" not in cards(snapshot)
    assert "ebit_margin" not in cards(snapshot)
    assert not {"revenue", "ebit_margin"} & {change.metric_id for change in snapshot.key_changes}
    notice = snapshot.conflicts[0]
    assert notice.canonical_metric == "revenue"
    assert notice.role == "current"
    assert notice.affected_metrics == ("revenue", "ebit_margin")
    assert "Historischer Wert ungeklärt" in snapshot.notices[0]


def test_base_unresolved_revenue_keeps_current_values_but_suppresses_dependent_deltas():
    previous, _ = sample_periods()
    snapshot = build(resolutions=(resolution(previous, "revenue", (1000, 999)),))
    assert cards(snapshot)["revenue"].current_value == 1100
    assert cards(snapshot)["revenue"].delta is None
    assert cards(snapshot)["ebit_margin"].current_value == pytest.approx(0.13)
    assert cards(snapshot)["ebit_margin"].delta is None
    assert snapshot.conflicts[0].role == "base"


@pytest.mark.parametrize("metric,hidden", [
    ("ebit", {"ebit_margin"}), ("operating_cash_flow", {"operating_cash_flow", "calculated_free_cash_flow"}),
    ("capex", {"calculated_free_cash_flow"}),
    ("cash", {"calculated_net_debt", "calculated_net_debt_to_ebitda"}),
    ("gross_debt", {"calculated_net_debt", "calculated_net_debt_to_ebitda"}),
    ("ebitda", {"ebitda", "calculated_net_debt_to_ebitda"}),
])
def test_open_input_conflicts_suppress_all_dependent_headlines(metric, hidden):
    _, current = sample_periods()
    value = getattr(current, metric)
    snapshot = build(resolutions=(resolution(current, metric, (value, value + 1)),))
    assert not hidden & set(cards(snapshot))
    assert snapshot.conflicts[0].canonical_metric == metric


def test_open_reported_fcf_never_falls_back_silently_to_calculated_fcf():
    _, current = sample_periods()
    unresolved = resolution(current, "reported_free_cash_flow", (658.6, 650))
    snapshot = build(current, resolutions=(unresolved,))
    assert not {"reported_free_cash_flow", "calculated_free_cash_flow"} & set(cards(snapshot))
    assert snapshot.conflicts[0].canonical_metric == "reported_free_cash_flow"


def test_open_reported_debt_does_not_replace_card_or_change_independent_calculated_ratio():
    _, current = sample_periods()
    unresolved = resolution(current, "reported_net_debt", (250, 255))
    snapshot = build(resolutions=(unresolved,))
    assert "reported_net_debt" not in cards(snapshot)
    assert "calculated_net_debt" not in cards(snapshot)
    assert cards(snapshot)["calculated_net_debt_to_ebitda"].current_value == calculate_period_metrics(current).calculated_net_debt_to_ebitda
    assert snapshot.conflicts[0].canonical_metric == "reported_net_debt"


def test_rounding_difference_is_open_until_analyst_selects_a_source():
    _, current = sample_periods()
    snapshot = build(resolutions=(resolution(current, "revenue", (1100, 1099.96), status="rounding_difference"),))
    assert "revenue" not in cards(snapshot)
    assert snapshot.conflicts[0].status == "rounding_difference"


def test_resolved_source_and_nonactive_alternative_are_both_preserved():
    _, current = sample_periods()
    resolved = resolution(current, "revenue", (1100, 1099.6), status="resolved", selected=0)
    snapshot = build(resolutions=(resolved,))
    sources = cards(snapshot)["revenue"].source_references
    assert len(sources) == 2
    assert [source.is_active for source in sources] == [True, False]
    assert [source.source_document for source in sources] == ["report-0.pdf", "report-1.pdf"]
    assert all(source.role == "current" and source.input_metric == "revenue" for source in sources)
    assert sources[0].confirmed is resolved.observations[0].confirmed
    assert sources[0].report_id == "report-0"
    assert sources[0].page_number == 2


def test_equivalent_sources_are_all_visible_without_an_arbitrary_preferred_report():
    _, current = sample_periods()
    equivalent = resolution(current, "revenue", (1100, 1100), status="equivalent")
    sources = cards(build(resolutions=(equivalent,)))["revenue"].source_references
    assert len(sources) == 2
    assert all(source.is_active and source.resolution_status == "equivalent" for source in sources)


@pytest.mark.parametrize("status,selected", [("resolved", 0), ("equivalent", None)])
def test_resolved_source_values_cannot_label_an_outdated_numeric_comparison(status, selected):
    _, current = sample_periods()
    resolved = resolution(current, "revenue", (1090, 1090), status=status, selected=selected)
    with pytest.raises(ResultsUpdateError, match="Aufgelöste Quellenwerte"):
        build(resolutions=(resolved,))


def test_resolution_links_by_economic_period_even_when_raw_label_is_an_alias():
    _, current = sample_periods()
    resolved = resolution(current, "revenue", (1100,), status="resolved", selected=0)
    source = resolved.observations[0]
    alias = replace(source, confirmed=replace(source.confirmed, period_label="Geschäftsjahr 2025"))
    resolved = replace(resolved, observations=(alias,))
    card = cards(build(resolutions=(resolved,)))["revenue"]
    assert card.source_references[0].period_label == "FY2025"
    assert card.source_references[0].confirmed.period_label == "Geschäftsjahr 2025"


def test_pair_outside_trend_has_sources_for_both_comparison_periods():
    history = five_years()
    previous, current = history.periods[-3:-1]
    trend = FinancialHistory(history.periods[-2:])
    sources = (observation("revenue", previous, previous.revenue), observation("revenue", current, current.revenue))
    snapshot = build(current, previous, history=trend, observations=sources)
    refs = cards(snapshot)["revenue"].source_references
    assert [(ref.role, ref.period_label) for ref in refs] == [("current", "FY2024"), ("base", "FY2023")]
    assert snapshot.trend_periods[-1].period_label == "FY2025"


def test_derived_card_sources_are_input_amounts_not_claimed_reported_ratios():
    previous, current = sample_periods()
    observations = tuple(observation(metric, current, getattr(current, metric)) for metric in ("revenue", "ebit", "operating_cash_flow", "capex", "gross_debt", "cash", "ebitda"))
    headline = cards(build(observations=observations))
    assert {source.input_metric for source in headline["ebit_margin"].source_references} == {"ebit", "revenue"}
    assert {source.input_metric for source in headline["calculated_free_cash_flow"].source_references} == {"operating_cash_flow", "capex"}
    assert {source.input_metric for source in headline["calculated_net_debt"].source_references} == {"gross_debt", "cash"}
    assert {source.input_metric for source in headline["calculated_net_debt_to_ebitda"].source_references} == {"gross_debt", "cash", "ebitda"}
    assert headline["ebit_margin"].source_references[0].value != headline["ebit_margin"].current_value
    assert set(snapshot_ref.headline_metric_id for snapshot_ref in build(observations=observations).source_summary) <= set(headline)


def test_manual_input_does_not_receive_invented_pdf_provenance():
    snapshot = build()
    assert snapshot.source_summary == ()
    assert all(card.source_references == () for card in snapshot.headline_metrics)
    _, current = sample_periods()
    manual = ConfirmedMetricObservation("revenue", "FY2025", 1100, "CHF", "million", "confirmed")
    references = cards(build(observations=(manual,)))["revenue"].source_references
    assert references[0].source_document is None
    assert references[0].page_number is None
    assert references[0].confirmed.extraction_method == "manual"


def test_snapshot_is_frozen_and_history_adapter_cannot_mutate_trend_tuple():
    snapshot = build()
    with pytest.raises(FrozenInstanceError):
        snapshot.company_name = "Different AG"
    with pytest.raises(FrozenInstanceError):
        snapshot.headline_metrics[0].current_value = 0
    copy = snapshot.history
    copy.add_period(replace(snapshot.current_period, period_label="FY2026", period_end=date(2026, 12, 31)))
    assert len(snapshot.trend_periods) == 2
    assert len(snapshot.trend_history.periods) == 2


def test_builder_reuses_supplied_metrics_comparison_and_flags_without_recalculation(monkeypatch):
    import research_update_assistant.calculations as calculations
    import research_update_assistant.flags as flags_module

    previous, current = sample_periods()
    history = FinancialHistory((previous, current))
    metrics = tuple(calculate_period_metrics(period) for period in history.periods)
    comparison = compare_periods(current, previous)
    flags = tuple(generate_research_flags(comparison, load_flag_rules()))
    forbidden = Mock(side_effect=AssertionError("Presentation darf Finance-Kern nicht erneut ausführen."))
    monkeypatch.setattr(calculations, "calculate_period_metrics", forbidden)
    monkeypatch.setattr(calculations, "compare_periods", forbidden)
    monkeypatch.setattr(flags_module, "generate_research_flags", forbidden)
    snapshot = build_results_update(history, metrics, comparison, flags)
    assert snapshot.trend_metrics == metrics
    assert cards(snapshot)["revenue"].delta == comparison.revenue_growth
    assert forbidden.call_count == 0


@pytest.mark.parametrize("change", [{"company_name": "Other AG"}, {"currency": "EUR"}, {"scale": "thousand"}])
def test_mismatched_trend_identity_or_units_are_rejected(change):
    previous, current = sample_periods()
    history = FinancialHistory((replace(previous, **change), replace(current, **change)))
    with pytest.raises(ResultsUpdateError, match="Unternehmen"):
        build(current, previous, history=history)


def test_mismatched_metrics_and_trend_length_are_rejected():
    previous, current = sample_periods()
    with pytest.raises(ResultsUpdateError, match="zusammenpassen"):
        build_results_update(FinancialHistory((previous, current)), (), compare_periods(current, previous), ())


def test_incompatible_pair_duration_is_rejected_without_recalculation():
    previous, current = sample_periods()
    comparison = compare_periods(current, previous)
    invalid = replace(comparison, previous_period=replace(previous, period_months=6))
    with pytest.raises(ResultsUpdateError, match="gleich lange"):
        build_results_update(FinancialHistory((previous, current)), (comparison.previous_metrics, comparison.current_metrics), invalid, ())


def test_pair_must_be_chronological():
    previous, current = sample_periods()
    comparison = compare_periods(current, previous)
    invalid = replace(comparison, current_period=previous, previous_period=current)
    with pytest.raises(ResultsUpdateError, match="chronologische"):
        build_results_update(FinancialHistory((previous, current)), (comparison.previous_metrics, comparison.current_metrics), invalid, ())
