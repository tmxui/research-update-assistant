"""Mehrbericht-Historie mit synthetischen, ausdrücklich bestätigten Beobachtungen."""

from dataclasses import FrozenInstanceError, replace
from datetime import date

import pytest

from research_update_assistant.history import AmbiguousPeriodError, FinancialHistory
from research_update_assistant.history_workspace import (
    HistoryWorkspace, HistoryWorkspaceError, PeriodKey, infer_reported_precision, period_key_for,
)
from research_update_assistant.models import FinancialPeriod
from research_update_assistant.validation import ConfirmedMetricObservation


def period(year, *, label=None, months=12, end=None, company="Synthetic Industrial AG", currency="CHF", scale="million", **values):
    return FinancialPeriod(company, label or f"FY{year}", end or date(year, 12, 31), months, currency, scale, **values)


def confirmed(metric, label, value, *, document="synthetic.pdf", page=1, currency="CHF", scale="million", raw=None, original=None, status="confirmed"):
    return ConfirmedMetricObservation(
        metric, label, value, currency, "unit" if metric in ("basic_eps", "diluted_eps") else scale,
        status, original_extracted_value=value if original is None else original,
        original_raw_value=str(value) if raw is None else raw,
        original_canonical_metric=metric, original_period_label=label,
        original_currency=currency, original_scale="unit" if metric in ("basic_eps", "diluted_eps") else scale,
        candidate_id=f"candidate-{metric}-{label}", source_document=document,
        page_number=page, reported_label=metric, source_snippet=f"{metric} {value}",
        extraction_method="pymupdf_layout", bbox=(30, 50, 550, 60),
    )


def report(year):
    values = {
        2025: ((2025, 1100, 143), (2024, 1000, 148)),
        2024: ((2024, 1000, 150), (2023, 920, 145)),
    }[year]
    periods = tuple(period(label, revenue=revenue, ebit=ebit) for label, revenue, ebit in values)
    observations = tuple(confirmed(metric, item.period_label, getattr(item, metric), document=f"annual_report_{year}.pdf", page=10)
                         for item in periods for metric in ("revenue", "ebit"))
    return FinancialHistory(periods), observations


def workspace():
    return HistoryWorkspace("Synthetic Industrial AG", "CHF", "million")


def multi_report():
    history_a, observations_a = report(2025)
    history_b, observations_b = report(2024)
    return workspace().add_report(history_a, observations_a, "report-2025").add_report(history_b, observations_b, "report-2024")


def two_values(a, b, *, metric="revenue", precisions=None):
    current = workspace()
    for index, value in enumerate((a, b)):
        item = period(2024, **{metric: value})
        observation = confirmed(metric, item.period_label, value, document=f"report-{index}.pdf")
        metadata = {(item.period_label, metric): precisions[index]} if precisions is not None and precisions[index] is not None else None
        current = current.add_report(FinancialHistory((item,)), (observation,), f"report-{index}", precisions=metadata)
    return current


def test_empty_workspace_is_valid_without_invented_periods_or_values():
    current = workspace()
    assert current.periods == current.period_keys == current.observations == current.resolutions == ()
    assert current.to_financial_history().periods == ()
    assert current.reports == current.events == current.open_resolutions == ()


def test_report_a_b_keep_three_periods_and_both_sources():
    current = multi_report()
    assert [item.period_label for item in current.periods] == ["FY2023", "FY2024", "FY2025"]
    assert len(current.reports) == 2
    assert len(current.observations) == 8
    assert len({item.observation_id for item in current.observations}) == 8
    assert {item.source_document for item in current.observations} == {"annual_report_2024.pdf", "annual_report_2025.pdf"}
    assert [item.report_id for item in current.reports] == ["report-2025", "report-2024"]


def test_equal_revenue_is_equivalent_with_all_provenance_retained():
    current = multi_report()
    resolution = current.get_resolution(PeriodKey(date(2024, 12, 31), 12), "revenue")
    assert resolution.status == "equivalent"
    assert resolution.resolved_value == 1000
    assert resolution.selected_observation_id is None
    assert len(resolution.observations) == 2
    assert all(item.value == 1000 for item in resolution.observations)
    assert current.to_financial_history().get_period("FY2024").revenue == 1000


def test_different_ebit_is_unresolved_without_silent_latest_report_winner():
    current = multi_report()
    resolution = current.get_resolution(PeriodKey(date(2024, 12, 31), 12), "ebit")
    assert resolution.status == "unresolved"
    assert {item.value for item in resolution.observations} == {148, 150}
    assert resolution.resolved_value is None
    assert resolution.selected_observation_id is None
    assert current.to_financial_history().get_period("FY2024").ebit is None
    assert current.open_resolutions == (resolution,)


def test_explicit_resolution_uses_one_source_keeps_alternative_and_reason():
    original = multi_report()
    key = PeriodKey(date(2024, 12, 31), 12)
    conflict = original.get_resolution(key, "ebit")
    selected = next(item for item in conflict.observations if item.value == 148)
    current = original.resolve(key, "ebit", selected.observation_id, "Späterer Vergleichswert verwendet")
    result = current.get_resolution(key, "ebit")
    assert result.status == "resolved"
    assert result.resolved_value == 148
    assert result.selected_observation_id == selected.observation_id
    assert result.reason == "Späterer Vergleichswert verwendet"
    assert result.observations == conflict.observations
    assert current.observations == original.observations
    assert current.to_financial_history().get_period("FY2024").ebit == 148
    assert current.open_resolutions == ()
    assert original.get_resolution(key, "ebit").status == "unresolved"
    assert current.events[-1].action == "source_selected"
    assert current.events[-1].selected_observation_id == selected.observation_id
    assert current.events[-1].reason == "Späterer Vergleichswert verwendet"


def test_decision_can_be_deferred_without_deleting_previous_audit():
    current = multi_report()
    key = PeriodKey(date(2024, 12, 31), 12)
    selected = current.get_resolution(key, "ebit").observations[0]
    resolved = current.resolve(key, "ebit", selected.observation_id, "Erste Auswahl")
    deferred = resolved.resolve(key, "ebit", None, "Noch prüfen")
    conflict = deferred.get_resolution(key, "ebit")
    assert conflict.status == "unresolved" and conflict.resolved_value is None
    assert conflict.observations == current.get_resolution(key, "ebit").observations
    assert deferred.events[-1].previous_selected_observation_id == selected.observation_id
    assert deferred.events[-1].action == "resolution_deferred"
    assert any(event.reason == "Erste Auswahl" for event in deferred.events)


def test_new_differing_observation_reopens_selected_conflict():
    original = multi_report()
    key = PeriodKey(date(2024, 12, 31), 12)
    chosen = next(item for item in original.get_resolution(key, "ebit").observations if item.value == 148)
    resolved = original.resolve(key, "ebit", chosen.observation_id, "Bewusste Auswahl")
    third = period(2024, ebit=147)
    current = resolved.add_report(FinancialHistory((third,)), (confirmed("ebit", "FY2024", 147),), "third")
    conflict = current.get_resolution(key, "ebit")
    assert conflict.status == "unresolved"
    assert conflict.selected_observation_id is None
    assert conflict.resolved_value is None
    assert {item.value for item in conflict.observations} == {147, 148, 150}
    assert current.events[-1].action == "resolution_reopened"
    assert current.events[-1].previous_selected_observation_id == chosen.observation_id
    assert any(event.reason == "Bewusste Auswahl" for event in current.events)
    assert resolved.get_resolution(key, "ebit").resolved_value == 148


def test_new_equal_observation_does_not_destroy_a_user_source_decision():
    current = multi_report()
    key = PeriodKey(date(2024, 12, 31), 12)
    chosen = next(item for item in current.get_resolution(key, "ebit").observations if item.value == 148)
    current = current.resolve(key, "ebit", chosen.observation_id, "Explizite Quelle")
    third = period(2024, ebit=148)
    current = current.add_report(FinancialHistory((third,)), (confirmed("ebit", "FY2024", 148),), "third")
    assert current.get_resolution(key, "ebit").resolved_value == 148
    assert current.get_resolution(key, "ebit").selected_observation_id == chosen.observation_id
    assert len(current.get_resolution(key, "ebit").observations) == 3


def test_new_equal_evidence_keeps_explicit_selection_even_when_all_values_equal():
    current = two_values(1000, 1000)
    resolution = current.resolutions[0]
    selected = resolution.observations[1].observation_id
    current = current.resolve(resolution.period_key, "revenue", selected, "Diese Quelle geprüft")
    current = current.add_periods((period(2024, revenue=1000),), "third")
    decision = current.get_resolution(resolution.period_key, "revenue")
    assert decision.status == "resolved"
    assert decision.selected_observation_id == selected
    assert decision.reason == "Diese Quelle geprüft"
    assert len(decision.observations) == 3


@pytest.mark.parametrize("a,b,precisions", [
    (1000.0, 999.96, (1, 2)), (3163, 3162.9, (0, 1)), (-1000.0, -999.96, (1, 2)),
    (1.0, 1.04, (1, 2)), (1000, 1000.4, (0, 1)),
])
def test_explicit_decimal_precision_classifies_possible_rounding_but_does_not_choose(a, b, precisions):
    current = two_values(a, b, precisions=precisions)
    resolution = current.resolutions[0]
    assert resolution.status == "rounding_difference"
    assert resolution.selected_observation_id is None
    assert resolution.resolved_value is None
    assert current.periods[0].revenue is None
    assert len(resolution.observations) == 2
    chosen = current.resolve(resolution.period_key, "revenue", resolution.observations[1].observation_id)
    assert chosen.periods[0].revenue == b
    assert current.periods[0].revenue is None


@pytest.mark.parametrize("a,b,precisions", [
    (1000.0, 999.96, None), (1000.0, 999.96, (1, None)), (1000, 999.9, (1, 1)),
    (1000, 998, (0, 0)), (-1, 1, (0, 0)), (0, 0.04, (1, 2)),
    (-0.04, 0, (2, 1)), (-1.0, -0.9, (1, 1)), (1, 2, (0, 0)),
])
def test_close_values_without_evidence_or_boundary_only_do_not_become_rounding(a, b, precisions):
    assert two_values(a, b, precisions=precisions).resolutions[0].status == "unresolved"


def test_three_values_require_one_shared_rounding_interval():
    current = two_values(1, 1.04, precisions=(1, 2))
    third = period(2024, revenue=0.96)
    current = current.add_report(FinancialHistory((third,)), (confirmed("revenue", "FY2024", 0.96),), "third",
                                 precisions={("FY2024", "revenue"): 2})
    assert current.resolutions[0].status == "unresolved"
    assert len(current.resolutions[0].observations) == 3


@pytest.mark.parametrize("value", [-10, 0, 10])
def test_exact_equality_needs_no_precision_or_rounding_tolerance(value):
    resolution = two_values(value, value).resolutions[0]
    assert resolution.status == "equivalent"
    assert resolution.resolved_value == value


@pytest.mark.parametrize("places", [-1, 16, 1.5, True, "2"])
def test_invalid_precision_metadata_is_rejected(places):
    with pytest.raises(HistoryWorkspaceError, match="Präzision"):
        two_values(1000, 999.96, precisions=(0, places))


def test_precision_must_represent_the_actual_reported_value():
    with pytest.raises(HistoryWorkspaceError, match="widersprechen"):
        two_values(1000, 999.96, precisions=(0, 1))


@pytest.mark.parametrize("raw,value,places", [
    ("1000", 1000, 0), ("1000.0", 1000, 1), ("999,96", 999.96, 2),
    ("3’162.9", 3162.9, 1), ("1'000,00", 1000, 2), ("1 000.0", 1000, 1),
    ("(80.00)", -80, 2), ("−80.0", -80, 1), ("0.0", 0, 1),
])
def test_precision_inference_from_valid_unchanged_raw_pdf_text(raw, value, places):
    assert infer_reported_precision(confirmed("revenue", "FY2024", value, raw=raw)) == places


@pytest.mark.parametrize("raw", ["", "1foo", "1,000.0", "1000 MCHF", "–", "NaN"])
def test_invalid_raw_text_does_not_create_a_precision_claim(raw):
    assert infer_reported_precision(confirmed("revenue", "FY2024", 1000, raw=raw)) is None


def test_changed_value_and_manual_value_do_not_infer_precision_from_original():
    corrected = confirmed("revenue", "FY2024", 1001, original=1000, raw="1000.0", status="changed")
    assert infer_reported_precision(corrected) is None
    manual = ConfirmedMetricObservation("revenue", "FY2024", 1000, "CHF", "million", "confirmed")
    assert infer_reported_precision(manual) is None
    assert infer_reported_precision(replace(corrected, confirmed_value=1000, extraction_method="manual")) is None


def test_raw_numeric_precision_is_not_guessed_from_float_string():
    observation = replace(confirmed("revenue", "FY2024", 1000), original_raw_value=None)
    assert infer_reported_precision(observation) is None


def test_economic_period_aliases_merge_with_first_confirmed_label_for_display():
    current = two_values(1000, 1000)
    alias = period(2024, label="Geschäftsjahr 2024", revenue=1000)
    current = current.add_report(FinancialHistory((alias,)), (confirmed("revenue", alias.period_label, 1000),), "alias")
    assert len(current.periods) == 1
    assert current.periods[0].period_label == "FY2024"
    assert current.period_aliases(period_key_for(alias)) == ("FY2024", "Geschäftsjahr 2024")
    assert len(current.resolutions[0].observations) == 3
    assert current.observations[-1].confirmed.period_label == "Geschäftsjahr 2024"


def test_same_label_different_economic_periods_do_not_merge_across_reports():
    current = workspace().add_periods((period(2024, label="FY", revenue=1000),), "first")
    current = current.add_periods((period(2025, label="FY", revenue=1100),), "second")
    assert len(current.periods) == 2
    assert len(current.period_keys) == 2
    assert [item.revenue for item in current.periods] == [1000, 1100]
    assert [item.period_label for item in current.periods] == ["FY (2024-12-31, 12 Monate)", "FY (2025-12-31, 12 Monate)"]
    assert [item.confirmed.period_label for item in current.observations] == ["FY", "FY"]


def test_label_collision_for_same_end_but_different_duration_keeps_distinct_columns():
    current = workspace().add_periods((period(2025, label="2025", revenue=1100),), "annual")
    current = current.add_periods((period(2025, label="2025", months=6, revenue=550),), "half")
    assert [item.period_label for item in current.periods] == ["2025 (2025-12-31, 6 Monate)", "2025 (2025-12-31, 12 Monate)"]
    assert current.period_aliases(PeriodKey(date(2025, 12, 31), 6)) == ("2025",)
    assert current.period_aliases(PeriodKey(date(2025, 12, 31), 12)) == ("2025",)
    assert {item.confirmed.period_label for item in current.observations} == {"2025"}


def test_same_end_half_year_and_full_year_have_different_keys_and_stable_order():
    current = workspace().add_periods((period(2025, label="FY2025", revenue=1100),), "annual")
    half = period(2025, label="H2 2025", months=6, revenue=550)
    current = current.add_periods((half,), "half")
    assert current.period_keys == (PeriodKey(date(2025, 12, 31), 6), PeriodKey(date(2025, 12, 31), 12))
    assert [item.period_months for item in current.periods] == [6, 12]
    assert [item.revenue for item in current.periods] == [550, 1100]


def test_h1_and_fy_history_is_chronological_and_preserves_duration():
    values = (period(2025, revenue=1100), period(2024, label="H1 2024", months=6, end=date(2024, 6, 30), revenue=500),
              period(2024, revenue=1000), period(2025, label="H1 2025", months=6, end=date(2025, 6, 30), revenue=550))
    current = workspace().add_periods(values, "mixed")
    assert [item.period_label for item in current.periods] == ["H1 2024", "FY2024", "H1 2025", "FY2025"]
    assert [item.period_months for item in current.periods] == [6, 12, 6, 12]


def test_manual_adapter_has_no_invented_pdf_provenance():
    current = workspace().add_periods((period(2024, revenue=1000, ebit=150),), "manual-1")
    assert len(current.observations) == 2
    for item in current.observations:
        assert item.confirmed.source_document is None
        assert item.confirmed.page_number is None
        assert item.confirmed.original_extracted_value is None
        assert item.confirmed.extraction_method == "manual"
        assert item.decimal_places is None
    assert current.periods[0].revenue == 1000


def test_five_period_history_stores_all_and_missing_values_remain_none():
    periods = tuple(period(year, revenue=100 * (year - 2020), reported_free_cash_flow=None if year == 2022 else 10 * (year - 2020))
                    for year in reversed(range(2021, 2026)))
    current = workspace().add_periods(periods, "five-years")
    assert [item.period_label for item in current.periods] == [f"FY{year}" for year in range(2021, 2026)]
    assert current.periods[1].reported_free_cash_flow is None
    assert current.periods[0].reported_free_cash_flow == 10
    assert current.periods[2].reported_free_cash_flow == 30
    assert all(item.inventory is None for item in current.periods)
    assert len(current.observations) == 9


def test_eps_is_unit_per_share_inside_million_scale_history():
    item = period(2024, revenue=1000, basic_eps=12.34, diluted_eps=12.30)
    observations = (confirmed("revenue", "FY2024", 1000), confirmed("basic_eps", "FY2024", 12.34), confirmed("diluted_eps", "FY2024", 12.30))
    current = workspace().add_report(FinancialHistory((item,)), observations, "eps")
    assert current.periods[0].scale == "million"
    assert current.periods[0].basic_eps == 12.34
    assert current.periods[0].diluted_eps == 12.30
    assert all(item.confirmed.scale == "unit" for item in current.observations if item.canonical_metric.endswith("eps"))


def test_same_report_id_identical_content_is_idempotent():
    history, observations = report(2025)
    current = workspace().add_report(history, observations, "annual-2025")
    assert current.add_report(history, observations, "annual-2025") is current
    assert len(current.reports) == 1


def test_same_report_id_changed_content_is_rejected_without_losing_correction():
    history, observations = report(2025)
    current = workspace().add_report(history, observations, "annual-2025")
    with pytest.raises(HistoryWorkspaceError, match="neue ID"):
        current.add_report(history, tuple(replace(item, source_snippet="different") for item in observations), "annual-2025")
    assert len(current.reports) == 1
    assert current.reports[0].observations == observations


def test_mutating_input_history_after_add_does_not_change_snapshot():
    history, observations = report(2025)
    current = workspace().add_report(history, observations, "annual-2025")
    history.add_period(period(2023))
    assert len(current.periods) == 2
    assert len(current.reports[0].periods) == 2


def test_workspace_and_wrapped_original_data_are_immutable():
    current = multi_report()
    with pytest.raises(FrozenInstanceError):
        current.company_name = "Different AG"
    with pytest.raises(FrozenInstanceError):
        current.observations[0].report_id = "changed"
    with pytest.raises(FrozenInstanceError):
        current.observations[0].confirmed.confirmed_value = 0
    with pytest.raises(FrozenInstanceError):
        current.reports[0].report_id = "changed"


def test_full_phase5b_provenance_object_is_preserved_without_reconstruction():
    history, observations = report(2025)
    changed = tuple(replace(item, status="changed", original_extracted_value=144, original_raw_value="144.0")
                    if item.canonical_metric == "ebit" and item.period_label == "FY2025" else item for item in observations)
    current = workspace().add_report(history, changed, "audit")
    for source, wrapped in zip(changed, current.observations):
        assert wrapped.confirmed is source
        assert wrapped.confirmed.original_raw_value == source.original_raw_value
        assert wrapped.confirmed.source_snippet == source.source_snippet
        assert wrapped.confirmed.bbox == source.bbox


@pytest.mark.parametrize("company", ["Geberit", "Synthetic Industrial", "Synthetic Industrial AG Gruppe"])
def test_company_aliases_are_not_silently_merged(company):
    item = period(2024, company=company)
    with pytest.raises(HistoryWorkspaceError, match="Unternehmen"):
        workspace().add_report(FinancialHistory((item,)), (), "wrong-company")


def test_outer_company_whitespace_is_cleaned_but_not_case_or_entity_identity():
    current = HistoryWorkspace(" Synthetic Industrial AG ", "CHF", "million")
    assert current.company_name == "Synthetic Industrial AG"
    assert current.add_periods((period(2024, company=" Synthetic Industrial AG "),), "trim").company_name == "Synthetic Industrial AG"
    with pytest.raises(HistoryWorkspaceError):
        current.add_periods((period(2024, company="synthetic industrial ag"),), "case")


@pytest.mark.parametrize("change", [{"currency": "EUR"}, {"scale": "thousand"}])
def test_report_currency_and_scale_mismatch_are_rejected(change):
    with pytest.raises(HistoryWorkspaceError, match="Währung oder Skalierung"):
        workspace().add_report(FinancialHistory((period(2024, **change),)), (), "wrong-unit")


@pytest.mark.parametrize("change", [{"currency": "EUR"}, {"scale": "thousand"}])
def test_observation_currency_and_scale_mismatch_are_rejected(change):
    observation = confirmed("revenue", "FY2024", 1000, **change)
    with pytest.raises(HistoryWorkspaceError, match="Observation"):
        workspace().add_report(FinancialHistory((period(2024, revenue=1000),)), (observation,), "wrong-unit")


def test_period_value_without_confirmed_observation_is_never_silently_dropped():
    with pytest.raises(HistoryWorkspaceError, match="benötigt eine bestätigte"):
        workspace().add_report(FinancialHistory((period(2024, revenue=1000),)), (), "unconfirmed")


def test_observation_must_match_report_period_value():
    with pytest.raises(HistoryWorkspaceError, match="widersprechen"):
        workspace().add_report(FinancialHistory((period(2024, revenue=1000),)), (confirmed("revenue", "FY2024", 1100),), "contradiction")


def test_observation_period_must_exist_in_the_report():
    with pytest.raises(HistoryWorkspaceError, match="keiner bestätigten Periode"):
        workspace().add_report(FinancialHistory((period(2024),)), (confirmed("revenue", "FY2025", 1000),), "wrong-period")


def test_duplicate_economic_periods_with_different_labels_inside_one_report_are_rejected():
    history = FinancialHistory((period(2024), period(2024, label="FY 2024")))
    with pytest.raises(HistoryWorkspaceError, match="doppelte"):
        workspace().add_report(history, (), "duplicate")


def test_duplicate_labels_for_different_economic_periods_inside_one_report_are_rejected():
    history = FinancialHistory((period(2024, label="FY"), period(2025, label="FY")))
    with pytest.raises(HistoryWorkspaceError, match="unklare"):
        workspace().add_report(history, (), "duplicate")


def test_duplicate_observations_inside_one_report_need_explicit_report_validation():
    observation = confirmed("revenue", "FY2024", 1000)
    with pytest.raises(HistoryWorkspaceError, match="nur einen bestätigten"):
        workspace().add_report(FinancialHistory((period(2024, revenue=1000),)), (observation, observation), "duplicate")


def test_blank_period_metadata_is_preserved_even_without_any_observations():
    current = workspace().add_report(FinancialHistory((period(2024),)), (), "blank")
    assert len(current.periods) == 1
    assert current.periods[0].revenue is None
    assert current.observations == current.resolutions == ()


@pytest.mark.parametrize("metadata", [
    {"precisions": {("FY2024", "ebit"): 1}},
    {"source_priorities": {("FY2024", "ebit"): 1}},
])
def test_unassociated_precision_or_priority_metadata_is_rejected(metadata):
    with pytest.raises(HistoryWorkspaceError, match="keiner bestätigten Observation"):
        workspace().add_report(FinancialHistory((period(2024),)), (), "metadata", **metadata)


@pytest.mark.parametrize("priority", [0, 8, True, 1.5])
def test_source_priority_metadata_is_bounded_and_explicit(priority):
    with pytest.raises(HistoryWorkspaceError, match="Quellenpriorität"):
        workspace().add_report(FinancialHistory((period(2024, revenue=1000),)), (confirmed("revenue", "FY2024", 1000),), "priority",
                               source_priorities={("FY2024", "revenue"): priority})


def test_source_priority_metadata_does_not_automatically_resolve_disagreement():
    current = two_values(1000, 999.96)
    assert current.resolutions[0].status == "unresolved"
    first = period(2023, revenue=920)
    current = current.add_report(FinancialHistory((first,)), (confirmed("revenue", "FY2023", 920),), "primary",
                                 source_priorities={("FY2023", "revenue"): 1})
    assert next(item for item in current.observations if item.period_label == "FY2023").source_priority == 1
    assert current.get_resolution(PeriodKey(date(2024, 12, 31), 12), "revenue").status == "unresolved"


def test_invalid_source_selection_cannot_use_observation_from_another_metric():
    current = multi_report()
    key = PeriodKey(date(2024, 12, 31), 12)
    unrelated = current.get_resolution(key, "revenue").observations[0]
    with pytest.raises(HistoryWorkspaceError, match="gehört nicht"):
        current.resolve(key, "ebit", unrelated.observation_id)


def test_missing_resolution_lookup_is_explicit():
    with pytest.raises(KeyError):
        workspace().get_resolution(PeriodKey(date(2024, 12, 31), 12), "revenue")


@pytest.mark.parametrize("value", ["", " ", None])
def test_report_requires_an_identifier(value):
    with pytest.raises(HistoryWorkspaceError, match="ID"):
        workspace().add_report(FinancialHistory((period(2024),)), (), value)


def test_report_requires_at_least_one_period():
    with pytest.raises(HistoryWorkspaceError, match="mindestens eine"):
        workspace().add_report(FinancialHistory(), (), "empty")


@pytest.mark.parametrize("company,currency,scale", [("", "CHF", "million"), ("A", "JPY", "million"), ("A", "CHF", "mio")])
def test_workspace_identity_metadata_is_required(company, currency, scale):
    with pytest.raises(HistoryWorkspaceError):
        HistoryWorkspace(company, currency, scale)


def test_period_key_serialization_is_stable_and_duration_is_part_of_identity():
    key = period_key_for(period(2024))
    assert str(key) == key.token == "2024-12-31:12"
    assert key != PeriodKey(date(2024, 12, 31), 6)


@pytest.mark.parametrize("end,months", [("2024-12-31", 12), (date(2024, 12, 31), 0), (date(2024, 12, 31), True)])
def test_invalid_period_keys_are_rejected(end, months):
    with pytest.raises(HistoryWorkspaceError):
        PeriodKey(end, months)


def test_existing_financial_history_duplicate_capability_is_unchanged():
    source_a = period(2024, ebit=148)
    source_b = period(2024, ebit=150)
    history = FinancialHistory((source_a, source_b))
    assert history.get_periods("FY2024") == (source_a, source_b)
    with pytest.raises(AmbiguousPeriodError):
        history.get_period("FY2024")


def test_same_inputs_create_stable_observation_ids_and_equal_immutable_workspaces():
    assert multi_report() == multi_report()
    assert [item.observation_id for item in multi_report().observations] == [item.observation_id for item in multi_report().observations]
