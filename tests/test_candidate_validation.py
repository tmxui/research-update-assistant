"""Bestätigung, Korrektur und Übernahme ohne automatische Quellenauswahl."""

from dataclasses import FrozenInstanceError, replace
from datetime import date

import pytest

from research_update_assistant.calculations import calculate_period_metrics, compare_periods
from research_update_assistant.candidate_models import FinancialMetricCandidate, PeriodValueCandidate
from research_update_assistant.models import FinancialPeriod
from research_update_assistant.validation import (
    SUPPORTED_METRICS,
    CandidateValidationError,
    ConfirmedMetricObservation,
    ConfirmedPeriodMetadata,
    confirm_candidate,
    confirm_manual_metric,
    create_confirmed_history,
)


@pytest.fixture
def ebit_candidate() -> FinancialMetricCandidate:
    return FinancialMetricCandidate(
        candidate_id="income-ebit", canonical_metric="ebit", display_name_de="EBIT",
        reported_label="Betriebsergebnis (EBIT)", statement_type="income_statement",
        source_document="synthetic_2025.pdf", page_number=2,
        source_snippet="Betriebsergebnis (EBIT) 143 150",
        extraction_method="pymupdf_layout", confidence="high",
        confidence_reasons=("Statement-Überschrift", "Jahresspalten"),
        currency="CHF", scale="million",
        values=(
            PeriodValueCandidate("FY2025", "143", 143, "2025", date(2025, 12, 31), 12, (300, 90, 330, 100)),
            PeriodValueCandidate("FY2024", "150", 150, "2024", date(2024, 12, 31), 12, (450, 90, 480, 100)),
        ),
        bbox=(45, 90, 480, 100), source_priority=1,
    )


@pytest.fixture
def annual_periods() -> tuple[ConfirmedPeriodMetadata, ...]:
    return (
        ConfirmedPeriodMetadata("FY2025", date(2025, 12, 31), 12),
        ConfirmedPeriodMetadata("FY2024", date(2024, 12, 31), 12),
    )


def test_manual_correction_preserves_original_value_and_complete_provenance(ebit_candidate):
    observation, = confirm_candidate(
        ebit_candidate, values={"FY2025": "145"}, currency="CHF", scale="million",
    )
    assert observation.original_extracted_value == observation.original_value == 143
    assert observation.original_raw_value == "143"
    assert observation.confirmed_value == observation.value == 145
    assert observation.status == "changed"
    assert observation.original_canonical_metric == "ebit"
    assert observation.original_period_label == "FY2025"
    assert observation.original_currency == "CHF"
    assert observation.original_scale == "million"
    assert observation.source_document == "synthetic_2025.pdf"
    assert observation.page_number == 2
    assert observation.reported_label == "Betriebsergebnis (EBIT)"
    assert observation.source_snippet == "Betriebsergebnis (EBIT) 143 150"
    assert observation.extraction_method == "pymupdf_layout"
    assert observation.bbox == (300, 90, 330, 100)
    assert observation.candidate_id == ebit_candidate.candidate_id
    assert ebit_candidate.values[0].normalized_value == 143
    with pytest.raises(FrozenInstanceError):
        observation.confirmed_value = 1


def test_unchanged_values_confirmed_and_blank_is_missing(ebit_candidate):
    observations = confirm_candidate(
        ebit_candidate, values={"FY2025": "143.0", "FY2024": " "}, currency="CHF", scale="million",
    )
    assert len(observations) == 1
    assert observations[0].status == "confirmed"
    assert observations[0].confirmed_value == 143


def test_remapping_keeps_original_canonical_metric(ebit_candidate):
    observation, = confirm_candidate(
        ebit_candidate, canonical_metric="adjusted_ebit", values={"FY2025": "143"},
        currency="CHF", scale="million",
    )
    assert observation.original_canonical_metric == "ebit"
    assert observation.canonical_metric == "adjusted_ebit"
    assert observation.status == "changed"


def test_unknown_periods_require_explicit_original_column_assignment(ebit_candidate):
    unknown = replace(ebit_candidate, values=tuple(
        replace(value, period_label=None, period_end=None, period_months=None, column_header=None)
        for value in ebit_candidate.values
    ))
    with pytest.raises(CandidateValidationError, match="Wertespalte"):
        confirm_candidate(unknown, values={"FY2025": "143"}, currency="CHF", scale="million")
    observations = confirm_candidate(
        unknown, values={"FY2024": "150", "FY2025": "143"}, currency="CHF", scale="million",
        period_assignments={"FY2024": 1, "FY2025": 0},
    )
    assert [(item.period_label, item.original_value) for item in observations] == [("FY2024", 150), ("FY2025", 143)]
    assert all(item.original_period_label is None for item in observations)
    assert all(item.status == "changed" for item in observations)


def test_renamed_period_explicitly_preserves_original_label(ebit_candidate):
    observation, = confirm_candidate(
        ebit_candidate, values={"Jahr 2025": "143"}, currency="CHF", scale="million",
        period_assignments={"Jahr 2025": 0},
    )
    assert observation.period_label == "Jahr 2025"
    assert observation.original_period_label == "FY2025"
    assert observation.status == "changed"


def test_missing_period_can_be_explicitly_supplemented_without_pdf_source(ebit_candidate):
    candidate = replace(ebit_candidate, values=ebit_candidate.values[:1])
    observations = confirm_candidate(
        candidate, values={"FY2025": "143", "FY2024": "150"}, currency="CHF", scale="million",
        period_assignments={"FY2024": None},
    )
    extracted, manual = observations
    assert extracted.page_number == 2 and extracted.original_value == 143
    assert manual.confirmed_value == 150
    assert manual.extraction_method == "manual"
    assert manual.source_document is None and manual.page_number is None
    assert manual.original_raw_value is None and manual.original_value is None


@pytest.mark.parametrize("index", [-1, 2, True, "0"])
def test_original_column_index_must_be_valid(ebit_candidate, index):
    with pytest.raises(CandidateValidationError, match="Wertespalte"):
        confirm_candidate(
            ebit_candidate, values={"FY2025": "143"}, currency="CHF", scale="million",
            period_assignments={"FY2025": index},
        )


def test_same_source_value_cannot_be_assigned_to_two_periods(ebit_candidate):
    with pytest.raises(CandidateValidationError, match="nur einer Periode"):
        confirm_candidate(
            ebit_candidate, values={"FY2025": "143", "FY2024": "143"}, currency="CHF", scale="million",
            period_assignments={"FY2025": 0, "FY2024": 0},
        )


def test_ambiguous_duplicate_source_period_needs_explicit_assignment(ebit_candidate):
    duplicate = replace(ebit_candidate, values=tuple(
        replace(value, period_label="FY2025") for value in ebit_candidate.values
    ))
    with pytest.raises(CandidateValidationError, match="Wertespalte"):
        confirm_candidate(duplicate, values={"FY2025": "143"}, currency="CHF", scale="million")


def test_segment_cannot_be_confirmed_even_after_remapping(ebit_candidate):
    segment = replace(ebit_candidate, is_segment=True)
    with pytest.raises(CandidateValidationError, match="Segmentwerte"):
        confirm_candidate(segment, canonical_metric="revenue", values={"FY2025": "143"}, currency="CHF", scale="million")


def test_currency_and_unit_correction_have_audit_trail(ebit_candidate):
    observation, = confirm_candidate(
        ebit_candidate, values={"FY2025": "143000"}, currency="EUR", scale="thousand",
    )
    assert (observation.currency, observation.scale, observation.confirmed_value) == ("EUR", "thousand", 143000)
    assert (observation.original_currency, observation.original_scale, observation.original_value) == ("CHF", "million", 143)
    assert observation.status == "changed"


def test_manually_completed_unparsed_candidate_retains_raw_value(ebit_candidate):
    unparsed = replace(ebit_candidate, values=(replace(ebit_candidate.values[0], raw_value="–", normalized_value=None),))
    observation, = confirm_candidate(unparsed, values={"FY2025": "143"}, currency="CHF", scale="million")
    assert observation.original_value is None
    assert observation.original_raw_value == "–"
    assert observation.confirmed_value == 143
    assert observation.status == "changed"


def test_manual_observations_do_not_invent_a_pdf_source():
    observation, = confirm_manual_metric("capex", values={"FY2025": "-80", "FY2024": ""}, currency="CHF", scale="million")
    assert observation.confirmed_value == -80
    assert observation.extraction_method == "manual"
    assert observation.source_document is None
    assert observation.page_number is None
    assert observation.source_snippet is None
    assert observation.reported_label is None
    assert observation.original_raw_value is None
    assert observation.original_value is None


@pytest.mark.parametrize("text, expected", [("1’100,5", 1100.5), ("1'100.5", 1100.5), ("1 100,5", 1100.5), ("0", 0), ("-80", -80)])
def test_confirmation_uses_existing_swiss_number_parser(text, expected):
    observation, = confirm_manual_metric("revenue", values={"FY2025": text}, currency="CHF", scale="million")
    assert observation.confirmed_value == expected


@pytest.mark.parametrize("text", ["NaN", "inf", "1e309", "1,000.5", "–", "9" * 400])
def test_invalid_or_non_finite_values_are_rejected(text):
    with pytest.raises(CandidateValidationError, match="Ungültiger Wert"):
        confirm_manual_metric("revenue", values={"FY2025": text}, currency="CHF", scale="million")


@pytest.mark.parametrize("metric", SUPPORTED_METRICS)
def test_every_canonical_metric_can_be_confirmed(metric, annual_periods):
    observations = confirm_manual_metric(metric, values={"FY2025": "12"}, currency="CHF", scale="million")
    history = create_confirmed_history("Synthetic Industrial AG", "CHF", "million", annual_periods, observations)
    assert getattr(history.get_period("FY2025"), metric) == 12
    assert getattr(history.get_period("FY2024"), metric) is None


def test_confirmed_pdf_data_uses_existing_calculation_engine(ebit_candidate, annual_periods):
    revenue = replace(
        ebit_candidate, candidate_id="income-revenue", canonical_metric="revenue",
        reported_label="Nettoumsatz", display_name_de="Umsatz", source_snippet="Nettoumsatz 1100 1000",
        values=(
            replace(ebit_candidate.values[0], raw_value="1’100", normalized_value=1100),
            replace(ebit_candidate.values[1], raw_value="1’000", normalized_value=1000),
        ),
    )
    observations = (
        *confirm_candidate(revenue, values={"FY2025": "1100", "FY2024": "1000"}, currency="CHF", scale="million"),
        *confirm_candidate(ebit_candidate, values={"FY2025": "143", "FY2024": "150"}, currency="CHF", scale="million"),
    )
    history = create_confirmed_history(" Synthetic Industrial AG ", "CHF", "million", annual_periods, observations)
    assert tuple(period.period_label for period in history.periods) == ("FY2024", "FY2025")
    current, previous = history.get_period("FY2025"), history.get_period("FY2024")
    assert current.company_name == "Synthetic Industrial AG"
    assert current.revenue == 1100 and current.ebit == 143
    assert previous.revenue == 1000 and previous.ebit == 150
    assert current.ebitda is None and current.capex is None
    assert calculate_period_metrics(current).ebit_margin == pytest.approx(0.13)
    assert calculate_period_metrics(previous).ebit_margin == pytest.approx(0.15)
    comparison = compare_periods(current, previous)
    assert comparison.revenue_growth == pytest.approx(0.10)
    assert comparison.ebit_margin_change_bps == pytest.approx(-200)
    assert current.source.user_confirmed is True
    assert current.source.source_document is None
    assert current.source.source_page is None


def test_each_metric_keeps_its_own_pdf_page(ebit_candidate, annual_periods):
    balance = replace(ebit_candidate, candidate_id="balance-inventory", canonical_metric="inventory", page_number=3, statement_type="balance_sheet")
    cash_flow = replace(ebit_candidate, candidate_id="cash-flow-ocf", canonical_metric="operating_cash_flow", page_number=4, statement_type="cash_flow")
    observations = tuple(
        confirm_candidate(candidate, values={"FY2025": "143"}, currency="CHF", scale="million")[0]
        for candidate in (ebit_candidate, balance, cash_flow)
    )
    history = create_confirmed_history("Synthetic", "CHF", "million", annual_periods, observations)
    assert {item.canonical_metric: item.page_number for item in observations} == {"ebit": 2, "inventory": 3, "operating_cash_flow": 4}
    assert history.get_period("FY2025").inventory == 143


@pytest.mark.parametrize("alternative_value", [143, 145])
def test_conflicting_or_identical_sources_cannot_blindly_overwrite(ebit_candidate, annual_periods, alternative_value):
    first = confirm_candidate(ebit_candidate, values={"FY2025": "143"}, currency="CHF", scale="million")
    alternative = replace(ebit_candidate, candidate_id="alternative", page_number=5)
    second = confirm_candidate(alternative, values={"FY2025": str(alternative_value)}, currency="CHF", scale="million")
    with pytest.raises(CandidateValidationError, match="mehrere Quellen"):
        create_confirmed_history("Synthetic", "CHF", "million", annual_periods, (*first, *second))
    assert first[0].page_number == 2 and second[0].page_number == 5


def test_unconfirmed_candidates_cannot_create_financial_history(ebit_candidate, annual_periods):
    with pytest.raises(TypeError, match="Unbestätigte"):
        create_confirmed_history("Synthetic", "CHF", "million", annual_periods, (ebit_candidate,))


def test_partially_filled_data_and_manual_capex_are_allowed(ebit_candidate, annual_periods):
    observations = (
        *confirm_candidate(ebit_candidate, values={"FY2025": "143"}, currency="CHF", scale="million"),
        *confirm_manual_metric("capex", values={"FY2025": "-80"}, currency="CHF", scale="million"),
        *confirm_manual_metric("operating_cash_flow", values={"FY2025": "140"}, currency="CHF", scale="million"),
    )
    period = create_confirmed_history("Synthetic", "CHF", "million", annual_periods, observations).get_period("FY2025")
    assert period.revenue is None
    metrics = calculate_period_metrics(period)
    assert metrics.ebit_margin is None
    assert metrics.calculated_free_cash_flow == 60


def test_all_missing_values_stay_none(annual_periods):
    history = create_confirmed_history("Synthetic", "CHF", "million", annual_periods, ())
    assert all(getattr(period, metric) is None for period in history.periods for metric in SUPPORTED_METRICS)


@pytest.mark.parametrize("currency, scale", [("EUR", "million"), ("CHF", "thousand")])
def test_currency_or_scale_mismatch_prevents_history_creation(annual_periods, currency, scale):
    observations = confirm_manual_metric("revenue", values={"FY2025": "1100"}, currency=currency, scale=scale)
    with pytest.raises(CandidateValidationError, match="Einheiten"):
        create_confirmed_history("Synthetic", "CHF", "million", annual_periods, observations)


def test_eps_is_per_share_and_never_rescaled(annual_periods):
    observations = confirm_manual_metric("basic_eps", values={"FY2025": "1,25"}, currency="CHF", scale="million")
    assert observations[0].scale == "unit"
    period = create_confirmed_history("Synthetic", "CHF", "million", annual_periods, observations).get_period("FY2025")
    assert period.basic_eps == 1.25
    assert period.scale == "million"


def test_h1_history_does_not_annualize_ebitda():
    periods = (
        ConfirmedPeriodMetadata("H1 2025", date(2025, 6, 30), 6),
        ConfirmedPeriodMetadata("H1 2024", date(2024, 6, 30), 6),
    )
    observations = tuple(
        item
        for metric, value in (("gross_debt", "360"), ("cash", "90"), ("ebitda", "105"), ("reported_net_debt", "270"))
        for item in confirm_manual_metric(metric, values={"H1 2025": value}, currency="CHF", scale="million")
    )
    history = create_confirmed_history("Synthetic", "CHF", "million", periods, observations)
    metrics = calculate_period_metrics(history.get_period("H1 2025"))
    assert metrics.calculated_net_debt == 270
    assert metrics.calculated_net_debt_to_ebitda is None
    assert metrics.reported_net_debt_to_ebitda is None


def test_fy_and_h1_cannot_be_combined(annual_periods):
    periods = (annual_periods[0], ConfirmedPeriodMetadata("H1 2024", date(2024, 6, 30), 6))
    with pytest.raises(CandidateValidationError, match="Halbjahresperioden"):
        create_confirmed_history("Synthetic", "CHF", "million", periods, ())


def test_undefined_observation_period_cannot_be_imported(annual_periods):
    observations = confirm_manual_metric("revenue", values={"FY2023": "920"}, currency="CHF", scale="million")
    with pytest.raises(CandidateValidationError, match="nicht bestätigt"):
        create_confirmed_history("Synthetic", "CHF", "million", annual_periods, observations)


@pytest.mark.parametrize("bad_periods", [(), (ConfirmedPeriodMetadata("FY2025", date(2025, 12, 31), 12),)])
def test_two_confirmed_periods_required(bad_periods):
    with pytest.raises(CandidateValidationError, match="mindestens zwei"):
        create_confirmed_history("Synthetic", "CHF", "million", bad_periods, ())


def test_duplicate_period_metadata_rejected(annual_periods):
    with pytest.raises(CandidateValidationError, match="eindeutig"):
        create_confirmed_history("Synthetic", "CHF", "million", (annual_periods[0], annual_periods[0]), ())
    same_end = replace(annual_periods[1], period_end=annual_periods[0].period_end)
    with pytest.raises(CandidateValidationError, match="Stichtage"):
        create_confirmed_history("Synthetic", "CHF", "million", (annual_periods[0], same_end), ())


@pytest.mark.parametrize("label", ["", " FY2025", "FY2025 "])
def test_empty_or_unclear_period_labels_rejected(label):
    with pytest.raises(CandidateValidationError, match="Periodenbezeichnung"):
        confirm_manual_metric("revenue", values={label: "1"}, currency="CHF", scale="million")


@pytest.mark.parametrize("kwargs", [{"currency": "GBP"}, {"scale": "mio"}, {"metric": "mystery"}])
def test_invalid_metric_or_units_rejected(kwargs):
    arguments = {"metric": "revenue", "currency": "CHF", "scale": "million", "values": {"FY2025": "1"}}
    arguments.update(kwargs)
    with pytest.raises(CandidateValidationError):
        confirm_manual_metric(**arguments)


@pytest.mark.parametrize("months", [0, 3, 9, True, "12"])
def test_only_explicit_fy_or_h1_metadata_supported(months):
    with pytest.raises(CandidateValidationError, match="Halbjahresperioden"):
        ConfirmedPeriodMetadata("FY2025", date(2025, 12, 31), months)


def test_financial_period_eps_remains_optional_and_finite():
    arguments = dict(company_name="Synthetic", period_label="FY2025", period_end=date(2025, 12, 31), period_months=12, currency="CHF", scale="million")
    period = FinancialPeriod(**arguments, basic_eps=1.25, diluted_eps=1.20)
    assert period.basic_eps == 1.25 and period.diluted_eps == 1.20
    assert FinancialPeriod(**arguments).basic_eps is None
    with pytest.raises(ValueError, match="basic_eps"):
        FinancialPeriod(**arguments, basic_eps=float("nan"))


def test_nonconfirmed_status_cannot_be_used_as_observation():
    with pytest.raises(CandidateValidationError, match="Nur bestätigte"):
        ConfirmedMetricObservation("ebit", "FY2025", 143, "CHF", "million", "proposed")
