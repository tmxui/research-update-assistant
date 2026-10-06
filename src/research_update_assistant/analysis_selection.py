"""Flexible Trendauswahl und genau ein explizites Paar aus einer Finanzhistorie.

Die vollständige Historie bleibt unverändert. Dieses Modul wählt bereits
aufgelöste FinancialPeriods und verwendet ausschliesslich bestehende Formeln
und Research-Regeln. Quellenkonflikte müssen vorher in der History-Schicht
aufgelöst oder als fehlende Werte dargestellt werden.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from .calculations import PeriodCompatibilityError, calculate_period_metrics, compare_periods
from .flag_config import FlagConfigError, FlagRules, load_flag_rules
from .flags import ResearchFlag, generate_research_flags
from .history import FinancialHistory
from .models import CalculatedPeriodMetrics, FinancialPeriod, PeriodComparison
from .validation import ConfirmedMetricObservation


class SelectionValidationError(ValueError):
    """Eine Analyseauswahl ist unvollständig, mehrdeutig oder inkompatibel."""


@dataclass(frozen=True)
class HistoryAnalysisResult:
    """Trendkennzahlen und ein unabhängig gewählter Vergleich samt Prüfpunkten.

    history und metrics enthalten nur die Trendperioden. comparisons und
    research_flags enthalten jeweils genau einen Eintrag für das gewählte Paar,
    das auch ausserhalb des Trendfensters liegen darf.
    """

    history: FinancialHistory
    metrics: tuple[CalculatedPeriodMetrics, ...]
    comparisons: tuple[PeriodComparison, ...]
    research_flags: tuple[tuple[ResearchFlag, ...], ...]
    flag_error: str | None = None
    observations: tuple[ConfirmedMetricObservation, ...] = ()


def period_key(period: FinancialPeriod) -> str:
    """Stabile wirtschaftliche Identität aus Stichtag und Dauer, nicht Label."""
    return f"{period.period_end.isoformat()}:{period.period_months}"


def _period_index(history: FinancialHistory) -> dict[str, FinancialPeriod]:
    periods: dict[str, FinancialPeriod] = {}
    for period in history.periods:
        key = period_key(period)
        if key in periods:
            raise SelectionValidationError(
                f"Für {period.period_label} ({key}) gibt es mehrere Datensätze. "
                "Bitte zuerst eine aufgelöste Finanzhistorie verwenden."
            )
        periods[key] = period
    return periods


def _compatible(current: FinancialPeriod, previous: FinancialPeriod) -> bool:
    return current.period_end > previous.period_end and all(
        getattr(current, name) == getattr(previous, name)
        for name in ("company_name", "currency", "scale", "period_months")
    )


def default_comparison_keys(history: FinancialHistory) -> tuple[str, str] | None:
    """Bevorzuge die zwei neuesten kompatiblen Jahres-, danach Halbjahresperioden.

    Eine einzelne Jahresperiode erzwingt keinen Vergleich mit einem Halbjahr.
    Bei zu wenigen kompatiblen Perioden ist keine sichere Standardauswahl da.
    """
    periods = tuple(sorted(
        _period_index(history).values(),
        key=lambda period: (period.period_end, period.period_months), reverse=True,
    ))
    for months in (12, 6):
        candidates = tuple(period for period in periods if period.period_months == months)
        for index, current in enumerate(candidates):
            for previous in candidates[index + 1:]:
                if _compatible(current, previous):
                    return period_key(previous), period_key(current)
    return None


def _get_period(index: dict[str, FinancialPeriod], key: str) -> FinancialPeriod:
    try:
        return index[key]
    except KeyError as error:
        raise SelectionValidationError(
            f"Die ausgewählte Periode {key!r} ist in der Finanzhistorie nicht vorhanden."
        ) from error


def _validate_trend(periods: tuple[FinancialPeriod, ...]) -> None:
    first = periods[0]
    for name, display in (
        ("company_name", "Unternehmen"), ("currency", "Währung"),
        ("scale", "Einheit"), ("period_months", "Periodenlänge"),
    ):
        if any(getattr(period, name) != getattr(first, name) for period in periods):
            raise SelectionValidationError(
                f"Die Trendperioden müssen bei {display} übereinstimmen. "
                "Jahres- und Halbjahresperioden bitte getrennt auswählen."
            )
    if len({period.period_label for period in periods}) != len(periods):
        raise SelectionValidationError(
            "Die ausgewählten Trendperioden benötigen eindeutige Anzeigenamen. "
            "Die wirtschaftliche Identität bleibt Stichtag und Periodenlänge."
        )


def analyse_selection(
    history: FinancialHistory, trend_period_keys: Sequence[str],
    previous_key: str, current_key: str, *, rules: FlagRules | None = None,
    observations: tuple[ConfirmedMetricObservation, ...] = (),
) -> HistoryAnalysisResult:
    """Analysiere beliebig viele kompatible Trendperioden und genau ein Paar.

    Fehlende Werte bleiben unverändert None. Keine zusätzlichen Perioden,
    Interpolation, Annualisierung oder benachbarten Vergleiche werden erzeugt.
    Ein Konfigurationsfehler lässt Finanzkennzahlen verfügbar, erzeugt aber
    keine Ersatzregeln. Optional übergebene Herkunft bleibt beim Aufrufer
    ausgewählt und wird unverändert mit dem Ergebnis aufbewahrt.
    """
    if isinstance(trend_period_keys, (str, bytes)) or len(trend_period_keys) < 2:
        raise SelectionValidationError("Bitte mindestens zwei Trendperioden auswählen.")
    if len(set(trend_period_keys)) != len(trend_period_keys):
        raise SelectionValidationError("Eine Trendperiode darf nur einmal ausgewählt werden.")
    index = _period_index(history)
    trend = tuple(_get_period(index, key) for key in trend_period_keys)
    _validate_trend(trend)
    previous, current = _get_period(index, previous_key), _get_period(index, current_key)
    # Der Vergleich darf ausserhalb des Trendfensters liegen, aber nicht zu
    # einem anderen Unternehmen oder zu abweichenden Betragseinheiten gehören.
    for name in ("company_name", "currency", "scale"):
        if any(getattr(period, name) != getattr(trend[0], name) for period in (previous, current)):
            raise SelectionValidationError(
                "Vergleich und Trend müssen dasselbe Unternehmen, dieselbe Währung und Einheit verwenden."
            )
    try:
        comparison = compare_periods(current, previous)
    except PeriodCompatibilityError as error:
        raise SelectionValidationError(str(error)) from error
    selected_history = FinancialHistory(trend)
    metrics = tuple(calculate_period_metrics(period) for period in selected_history.periods)
    flag_error = None
    flags: tuple[ResearchFlag, ...] = ()
    try:
        selected_rules = rules if rules is not None else load_flag_rules()
        flags = tuple(generate_research_flags(comparison, selected_rules))
    except FlagConfigError as error:
        flag_error = str(error)
    return HistoryAnalysisResult(
        selected_history, metrics, (comparison,), (flags,), flag_error, observations,
    )
