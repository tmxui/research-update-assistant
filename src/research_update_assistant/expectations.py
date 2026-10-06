"""Testbare Actual-vs-Estimate-Logik ohne Streamlit oder Datenanbieter."""

from collections.abc import Mapping

from .calculations import margin_change, margin_change_bps, percentage_change
from .expectation_models import (
    ExpectationComparison,
    ExpectationSnapshot,
    MetricSurprise,
    SUPPORTED_EXPECTATION_METRICS,
)
from .history_workspace import period_key_for
from .input_parsing import parse_optional_number
from .models import CalculatedPeriodMetrics, FinancialPeriod


class ExpectationCompatibilityError(ValueError):
    """Actuals und Erwartungs-Snapshot beschreiben nicht dieselbe Einheit."""


_MARGIN_METRICS = {"ebit_margin"}
_MULTIPLE_METRICS = {"calculated_net_debt_to_ebitda"}


def parse_expectation_values(raw_values: Mapping[str, str]) -> dict[str, float | None]:
    """Parse Formulardaten; Margen werden von Prozent in Dezimalwerte übersetzt."""
    parsed: dict[str, float | None] = {}
    for metric in SUPPORTED_EXPECTATION_METRICS:
        value = parse_optional_number(raw_values.get(metric, ""))
        parsed[metric] = value / 100 if value is not None and metric in _MARGIN_METRICS else value
    return parsed


def _actual_value(
    metric: str,
    period: FinancialPeriod,
    calculated: CalculatedPeriodMetrics,
) -> float | None:
    if hasattr(period, metric):
        return getattr(period, metric)
    if hasattr(calculated, metric):
        return getattr(calculated, metric)
    raise ValueError(f"Keine Actual-Kennzahl für {metric} definiert.")


def _direction(actual: float | None, estimate: float | None) -> str | None:
    if actual is None or estimate is None:
        return None
    if actual > estimate:
        return "above"
    if actual < estimate:
        return "below"
    return "equal"


def _amount_surprise(actual: float | None, estimate: float | None) -> tuple[float | None, float | None]:
    if actual is None or estimate is None:
        return None, None
    absolute = actual - estimate
    # Relative Abweichungen mit Null-/Negativbasis oder negativem Actual sind
    # wirtschaftlich mehrdeutig. Der absolute Unterschied bleibt sichtbar.
    relative = percentage_change(actual, estimate) if estimate > 0 and actual >= 0 else None
    return absolute, relative


def compare_actual_to_expectation(
    actual: FinancialPeriod,
    calculated: CalculatedPeriodMetrics,
    expectation: ExpectationSnapshot,
) -> ExpectationComparison:
    """Vergleiche Actuals mit genau einem kompatiblen Erwartungs-Snapshot."""
    if expectation.company.strip() != actual.company_name.strip():
        raise ExpectationCompatibilityError(
            "Erwartung und Actuals gehören nicht zum selben Unternehmen."
        )
    if expectation.target_period != period_key_for(actual):
        raise ExpectationCompatibilityError(
            "Die Zielperiode der Erwartung stimmt nicht mit der aktuellen Periode überein."
        )
    if expectation.currency != actual.currency:
        raise ExpectationCompatibilityError(
            f"Währungen unterscheiden sich ({expectation.currency} vs. {actual.currency})."
        )
    if expectation.scale != actual.scale:
        raise ExpectationCompatibilityError(
            f"Skalierungen unterscheiden sich ({expectation.scale} vs. {actual.scale})."
        )

    surprises: list[MetricSurprise] = []
    for metric in SUPPORTED_EXPECTATION_METRICS:
        actual_value = _actual_value(metric, actual, calculated)
        estimate_value = expectation.get(metric)
        if metric in _MARGIN_METRICS:
            absolute = margin_change(actual_value, estimate_value)
            percent = None
            bps = margin_change_bps(actual_value, estimate_value)
            kind = "margin"
        elif metric in _MULTIPLE_METRICS:
            absolute = (
                None if actual_value is None or estimate_value is None
                else actual_value - estimate_value
            )
            percent, bps, kind = None, None, "multiple"
        else:
            absolute, percent = _amount_surprise(actual_value, estimate_value)
            bps, kind = None, "amount"
        surprises.append(MetricSurprise(
            metric, actual_value, estimate_value, absolute, percent, bps, kind,
            _direction(actual_value, estimate_value),
        ))
    return ExpectationComparison(actual, calculated, expectation, tuple(surprises))
