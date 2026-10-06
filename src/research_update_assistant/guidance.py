"""Deterministische Guidance-Vergleiche ohne Streamlit oder Texterkennung."""

from collections.abc import Mapping

from .guidance_models import (
    ActualGuidanceComparison,
    ActualGuidanceItemComparison,
    GuidanceItem,
    GuidanceItemChange,
    GuidanceSnapshot,
    GuidanceSnapshotComparison,
    PERCENTAGE_GUIDANCE_METRICS,
    SUPPORTED_GUIDANCE_METRICS,
)
from .history_workspace import period_key_for
from .input_parsing import parse_optional_number
from .models import CalculatedPeriodMetrics, FinancialPeriod, PeriodComparison


class GuidanceCompatibilityError(ValueError):
    """Guidance-Snapshots oder Actuals beschreiben inkompatible Einheiten."""


def create_guidance_item(
    canonical_metric: str,
    guidance_type: str,
    *,
    raw_value: str = "",
    raw_minimum: str = "",
    raw_maximum: str = "",
    qualitative_direction: str | None = None,
) -> GuidanceItem | None:
    """Übersetze ein kompaktes Formularfeld in eine kanonische Guidance-Aussage."""
    if guidance_type == "none":
        return None
    if canonical_metric not in SUPPORTED_GUIDANCE_METRICS:
        raise ValueError(f"Nicht unterstützte Guidance-Kennzahl: {canonical_metric}.")
    exact = parse_optional_number(raw_value)
    minimum = parse_optional_number(raw_minimum)
    maximum = parse_optional_number(raw_maximum)
    if canonical_metric in PERCENTAGE_GUIDANCE_METRICS:
        exact = None if exact is None else exact / 100
        minimum = None if minimum is None else minimum / 100
        maximum = None if maximum is None else maximum / 100
    return GuidanceItem(
        canonical_metric=canonical_metric,
        guidance_type=guidance_type,
        exact_value=exact,
        minimum=minimum,
        maximum=maximum,
        qualitative_direction=qualitative_direction if guidance_type == "qualitative" else None,
    )


def _validate_snapshots(current: GuidanceSnapshot, previous: GuidanceSnapshot) -> None:
    for name, label in (
        ("company", "Unternehmen"),
        ("target_period", "Zielperiode"),
        ("currency", "Währung"),
        ("scale", "Skalierung"),
    ):
        if getattr(current, name) != getattr(previous, name):
            raise GuidanceCompatibilityError(
                f"Guidance-Vergleich verhindert: {label} unterscheiden sich."
            )
    if current.as_of_date <= previous.as_of_date:
        raise GuidanceCompatibilityError(
            "Die aktuelle Guidance muss einen späteren Stand als die vorherige Guidance haben."
        )


def _numeric_direction(current: float, previous: float) -> tuple[str, ...]:
    if current > previous:
        return ("raised",)
    if current < previous:
        return ("lowered",)
    return ("unchanged",)


def _compare_items(current: GuidanceItem, previous: GuidanceItem) -> tuple[str, ...]:
    if current == previous:
        return ("unchanged",)
    if current.guidance_type != previous.guidance_type:
        return ("changed",)
    if current.guidance_type in ("exact", "approximate"):
        return _numeric_direction(current.exact_value, previous.exact_value)
    if current.guidance_type in ("min", "above"):
        return _numeric_direction(current.minimum, previous.minimum)
    if current.guidance_type in ("max", "below"):
        return _numeric_direction(current.maximum, previous.maximum)
    if current.guidance_type == "qualitative":
        return ("changed",)

    changes: list[str] = []
    if current.minimum >= previous.minimum and current.maximum >= previous.maximum:
        if current.minimum > previous.minimum or current.maximum > previous.maximum:
            changes.append("raised")
    elif current.minimum <= previous.minimum and current.maximum <= previous.maximum:
        if current.minimum < previous.minimum or current.maximum < previous.maximum:
            changes.append("lowered")
    current_width = current.maximum - current.minimum
    previous_width = previous.maximum - previous.minimum
    if current_width < previous_width:
        changes.append("narrowed")
    elif current_width > previous_width:
        changes.append("widened")
    return tuple(changes) or ("changed",)


def compare_guidance_snapshots(
    current: GuidanceSnapshot,
    previous: GuidanceSnapshot,
) -> GuidanceSnapshotComparison:
    """Vergleiche zwei Informationsstände derselben wirtschaftlichen Guidance."""
    _validate_snapshots(current, previous)
    changes = []
    for metric in SUPPORTED_GUIDANCE_METRICS:
        current_item, previous_item = current.get(metric), previous.get(metric)
        if current_item is None and previous_item is None:
            continue
        item_changes = (
            ("changed",)
            if current_item is None or previous_item is None
            else _compare_items(current_item, previous_item)
        )
        changes.append(GuidanceItemChange(metric, previous_item, current_item, item_changes))
    return GuidanceSnapshotComparison(previous, current, tuple(changes))


def _validate_actual(
    actual: FinancialPeriod,
    guidance: GuidanceSnapshot,
    period_comparison: PeriodComparison | None,
) -> None:
    if guidance.company.strip() != actual.company_name.strip():
        raise GuidanceCompatibilityError(
            "Guidance und Actuals gehören nicht zum selben Unternehmen."
        )
    if guidance.target_period != period_key_for(actual):
        raise GuidanceCompatibilityError(
            "Die Zielperiode der Guidance stimmt nicht mit der aktuellen Periode überein."
        )
    if guidance.currency != actual.currency:
        raise GuidanceCompatibilityError(
            f"Währungen unterscheiden sich ({guidance.currency} vs. {actual.currency})."
        )
    if guidance.scale != actual.scale:
        raise GuidanceCompatibilityError(
            f"Skalierungen unterscheiden sich ({guidance.scale} vs. {actual.scale})."
        )
    if period_comparison is not None and period_comparison.current_period != actual:
        raise GuidanceCompatibilityError(
            "Der Periodenvergleich gehört nicht zu den aktuellen Actuals."
        )


def _actual_value(
    metric: str,
    actual: FinancialPeriod,
    calculated: CalculatedPeriodMetrics,
    period_comparison: PeriodComparison | None,
) -> float | None:
    if metric == "revenue_growth":
        return None if period_comparison is None else period_comparison.revenue_growth
    if hasattr(actual, metric):
        return getattr(actual, metric)
    if hasattr(calculated, metric):
        return getattr(calculated, metric)
    raise ValueError(f"Keine Actual-Kennzahl für {metric} definiert.")


def _actual_status(actual: float | None, item: GuidanceItem) -> str:
    if item.guidance_type in ("qualitative", "approximate"):
        return "not_assessable"
    if actual is None:
        return "missing_actual"
    if item.guidance_type == "exact":
        if actual == item.exact_value:
            return "within"
        return "above" if actual > item.exact_value else "below"
    if item.guidance_type == "min":
        return "below" if actual < item.minimum else "within"
    if item.guidance_type == "above":
        return "below" if actual <= item.minimum else "within"
    if item.guidance_type == "max":
        return "above" if actual > item.maximum else "within"
    if item.guidance_type == "below":
        return "above" if actual >= item.maximum else "within"
    if actual < item.minimum:
        return "below"
    if actual > item.maximum:
        return "above"
    return "within"


def compare_actual_to_guidance(
    actual: FinancialPeriod,
    calculated: CalculatedPeriodMetrics,
    guidance: GuidanceSnapshot,
    *,
    period_comparison: PeriodComparison | None = None,
) -> ActualGuidanceComparison:
    """Prüfe Actuals gegen exakte, Mindest-, Höchst- oder Range-Grenzen."""
    _validate_actual(actual, guidance, period_comparison)
    comparisons = tuple(
        ActualGuidanceItemComparison(
            item.canonical_metric,
            (value := _actual_value(item.canonical_metric, actual, calculated, period_comparison)),
            item,
            _actual_status(value, item),
        )
        for item in guidance.guidance_items
    )
    return ActualGuidanceComparison(actual, calculated, guidance, comparisons)


def guidance_items_from_form(
    forms: Mapping[str, tuple[str, str, str, str, str | None]],
) -> tuple[GuidanceItem, ...]:
    """Parse mehrere UI-Zeilen, ohne fehlende Guidance als Null zu speichern."""
    items = []
    for metric in SUPPORTED_GUIDANCE_METRICS:
        guidance_type, raw_value, raw_minimum, raw_maximum, direction = forms[metric]
        item = create_guidance_item(
            metric, guidance_type, raw_value=raw_value, raw_minimum=raw_minimum,
            raw_maximum=raw_maximum, qualitative_direction=direction,
        )
        if item is not None:
            items.append(item)
    return tuple(items)
