"""Deterministische Präsentation vorhandener Resultate, ohne neue Finanzformeln.

Headline-Werte stammen immer aus dem ausdrücklich gewählten Vergleichspaar.
Die Trendperioden bleiben ein unabhängiger Kontext. Quellen und offene
historische Abweichungen werden getrennt von den numerischen Karten bewahrt.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .calculations import percentage_change
from .flags import ResearchFlag
from .formatting import format_basis_points, format_currency_unit, format_money, format_multiple, format_percentage
from .history import FinancialHistory
from .history_workspace import PeriodMetricResolution, period_key_for
from .models import CalculatedPeriodMetrics, FinancialPeriod, PeriodComparison
from .validation import ConfirmedMetricObservation

ChangeType = Literal["percentage", "bps", "multiple"]


class ResultsUpdateError(ValueError):
    """Vergleich, Trend oder Prüfpunkte passen nicht zum angezeigten Stand."""


@dataclass(frozen=True)
class SourceReference:
    """Eine originale Eingangskennzahl; berechnete Karten behaupten keine PDF-Zahl."""

    headline_metric_id: str
    input_metric: str
    period_label: str
    value: float
    confirmed: ConfirmedMetricObservation
    is_active: bool
    role: Literal["current", "base"]
    observation_id: str | None = None
    report_id: str | None = None
    resolution_status: str | None = None

    @property
    def source_document(self) -> str | None:
        return self.confirmed.source_document

    @property
    def page_number(self) -> int | None:
        return self.confirmed.page_number

    @property
    def reported_label(self) -> str | None:
        return self.confirmed.reported_label


@dataclass(frozen=True)
class HeadlineMetric:
    metric_id: str
    label_de: str
    current_value: float
    formatted_value: str
    delta: float | None
    formatted_delta: str | None
    unit: str
    change_type: ChangeType
    current_period_label: str
    base_period_label: str
    source_references: tuple[SourceReference, ...] = ()


@dataclass(frozen=True)
class KeyChange:
    metric_id: str
    label_de: str
    change: float
    formatted_change: str
    text: str
    change_type: ChangeType
    priority: int


@dataclass(frozen=True)
class ConflictNotice:
    period_label: str
    canonical_metric: str
    status: str
    message: str
    affected_metrics: tuple[str, ...]
    role: Literal["current", "base"]


@dataclass(frozen=True)
class ResultsUpdateSnapshot:
    company_name: str
    current_period: FinancialPeriod
    base_period: FinancialPeriod
    headline_metrics: tuple[HeadlineMetric, ...]
    key_changes: tuple[KeyChange, ...]
    flags: tuple[ResearchFlag, ...]
    trend_periods: tuple[FinancialPeriod, ...]
    trend_metrics: tuple[CalculatedPeriodMetrics, ...]
    source_summary: tuple[SourceReference, ...]
    conflicts: tuple[ConflictNotice, ...] = ()
    flag_error: str | None = None

    @property
    def history(self) -> FinancialHistory:
        """Eigenständiger Adapter für die bestehenden Chart-Funktionen."""
        return FinancialHistory(self.trend_periods)

    @property
    def trend_history(self) -> FinancialHistory:
        return self.history

    @property
    def notices(self) -> tuple[str, ...]:
        return tuple(f"{item.period_label} · {item.canonical_metric}: {item.message}" for item in self.conflicts)


@dataclass(frozen=True)
class _MetricView:
    metric_id: str
    label: str
    current: float | None
    previous: float | None
    delta: float | None
    change_type: ChangeType
    dependencies: tuple[str, ...]


def _format_delta(value: float, kind: ChangeType) -> str:
    if kind == "bps":
        return format_basis_points(value)
    if kind == "multiple":
        return format_multiple(value, signed=True)
    return format_percentage(value, signed=True)


def _positive_base_change(current: float | None, previous: float | None) -> float | None:
    """Bereits bestehende Wachstumsfunktion; negative Basen werden nicht interpretiert."""
    return None if previous is None or previous <= 0 else percentage_change(current, previous)


def _open_metrics(period: FinancialPeriod, resolutions: Sequence[PeriodMetricResolution]) -> set[str]:
    return {item.canonical_metric for item in resolutions if item.period_key == period_key_for(period)
            and item.status in ("unresolved", "rounding_difference")}


def _metric_views(comparison: PeriodComparison, current_open: set[str]) -> tuple[_MetricView, ...]:
    current, previous = comparison.current_period, comparison.previous_period
    current_metrics, previous_metrics = comparison.current_metrics, comparison.previous_metrics
    result_metric = "ebitda" if current.ebitda is not None or "ebitda" in current_open else "ebit"
    reported_fcf = current.reported_free_cash_flow is not None or "reported_free_cash_flow" in current_open
    fcf_metric = "reported_free_cash_flow" if reported_fcf else "calculated_free_cash_flow"
    fcf_current = current.reported_free_cash_flow if reported_fcf else current_metrics.calculated_free_cash_flow
    fcf_previous = previous.reported_free_cash_flow if reported_fcf else previous_metrics.calculated_free_cash_flow
    reported_debt = current.reported_net_debt is not None or "reported_net_debt" in current_open
    debt_metric = "reported_net_debt" if reported_debt else "calculated_net_debt"
    debt_current = current.reported_net_debt if reported_debt else current_metrics.calculated_net_debt
    debt_previous = previous.reported_net_debt if reported_debt else previous_metrics.calculated_net_debt
    # Leverage übernimmt ausschliesslich die kanonische vorberechnete Kennzahl.
    # Die ausgewiesene Nettoverschuldung ist kein Ersatz für deren Eingangsgrössen.
    leverage_metric = "calculated_net_debt_to_ebitda"
    debt_dependencies = ("reported_net_debt",) if reported_debt else ("gross_debt", "cash")
    leverage_current = current_metrics.calculated_net_debt_to_ebitda if current.period_months == 12 else None
    leverage_previous = previous_metrics.calculated_net_debt_to_ebitda if previous.period_months == 12 else None
    return (
        _MetricView("revenue", "Umsatz", current.revenue, previous.revenue, comparison.revenue_growth, "percentage", ("revenue",)),
        _MetricView(result_metric, "EBITDA" if result_metric == "ebitda" else "EBIT",
                    getattr(current, result_metric), getattr(previous, result_metric),
                    getattr(comparison, f"{result_metric}_growth"), "percentage", (result_metric,)),
        _MetricView("ebit_margin", "EBIT-Marge", current_metrics.ebit_margin, previous_metrics.ebit_margin,
                    comparison.ebit_margin_change_bps, "bps", ("ebit", "revenue")),
        _MetricView("operating_cash_flow", "Operativer Cashflow", current.operating_cash_flow, previous.operating_cash_flow,
                    comparison.operating_cash_flow_growth, "percentage", ("operating_cash_flow",)),
        _MetricView(fcf_metric, "Ausgewiesener FCF" if reported_fcf else "Berechneter FCF", fcf_current, fcf_previous,
                    _positive_base_change(fcf_current, fcf_previous) if reported_fcf else comparison.calculated_free_cash_flow_growth,
                    "percentage", ("reported_free_cash_flow",) if reported_fcf else ("operating_cash_flow", "capex")),
        _MetricView(debt_metric, "Ausgewiesene Nettoverschuldung" if reported_debt else "Berechnete Nettoverschuldung",
                    debt_current, debt_previous, _positive_base_change(debt_current, debt_previous), "percentage", debt_dependencies),
        _MetricView(leverage_metric, "Net Debt / EBITDA (berechnet)",
                    leverage_current, leverage_previous, comparison.calculated_net_debt_to_ebitda_change,
                    "multiple", ("gross_debt", "cash", "ebitda")),
    )


def _available_delta(view: _MetricView, current_open: set[str], base_open: set[str]) -> float | None:
    if view.current is None or view.previous is None:
        return None
    if any(metric in current_open or metric in base_open for metric in view.dependencies):
        return None
    if view.change_type == "percentage" and view.previous <= 0:
        return None
    return view.delta


def _source_references(
    view: _MetricView, period: FinancialPeriod, role: Literal["current", "base"],
    resolutions: Sequence[PeriodMetricResolution], observations: Sequence[ConfirmedMetricObservation],
) -> tuple[SourceReference, ...]:
    references = []
    for metric in view.dependencies:
        resolution = next((item for item in resolutions if item.period_key == period_key_for(period)
                           and item.canonical_metric == metric), None)
        if resolution is not None:
            for item in resolution.observations:
                active = resolution.status == "equivalent" or (
                    resolution.status == "resolved" and item.observation_id == resolution.selected_observation_id
                )
                references.append(SourceReference(view.metric_id, metric, period.period_label, item.value, item.confirmed,
                                                   active, role, item.observation_id, item.report_id, resolution.status))
        else:
            for item in observations:
                if item.canonical_metric == metric and item.period_label == period.period_label:
                    references.append(SourceReference(view.metric_id, metric, period.period_label, item.value, item,
                                                       item.value == getattr(period, metric), role, resolution_status="confirmed"))
    return tuple(references)


def _headline_metrics(
    views: tuple[_MetricView, ...], comparison: PeriodComparison, current_open: set[str], base_open: set[str],
    resolutions: Sequence[PeriodMetricResolution], observations: Sequence[ConfirmedMetricObservation],
) -> tuple[HeadlineMetric, ...]:
    cards = []
    current, previous = comparison.current_period, comparison.previous_period
    for view in views:
        if view.current is None or any(metric in current_open for metric in view.dependencies):
            continue
        delta = _available_delta(view, current_open, base_open)
        if view.change_type == "bps":
            value, unit = format_percentage(view.current), "%"
        elif view.change_type == "multiple":
            value, unit = format_multiple(view.current), "x"
        else:
            value, unit = format_money(view.current, current.currency, current.scale), format_currency_unit(current.currency, current.scale)
        sources = (*_source_references(view, current, "current", resolutions, observations),
                   *_source_references(view, previous, "base", resolutions, observations))
        cards.append(HeadlineMetric(view.metric_id, view.label, view.current, value, delta,
                                    _format_delta(delta, view.change_type) if delta is not None else None,
                                    unit, view.change_type, current.period_label, previous.period_label, sources))
    return tuple(cards)


def _key_changes(
    views: tuple[_MetricView, ...], comparison: PeriodComparison, flags: tuple[ResearchFlag, ...],
    current_open: set[str], base_open: set[str],
) -> tuple[KeyChange, ...]:
    current, previous = comparison.current_period, comparison.previous_period
    ebit = _MetricView("ebit", "EBIT", current.ebit, previous.ebit, comparison.ebit_growth, "percentage", ("ebit",))
    result = ebit if _available_delta(ebit, current_open, base_open) is not None else views[1]
    leverage = views[6] if _available_delta(views[6], current_open, base_open) is not None else views[5]
    candidates = (views[0], result, views[2], views[3], views[4], leverage,
                  _MetricView("inventory", "Vorräte", current.inventory, previous.inventory, comparison.inventory_growth, "percentage", ("inventory",)),
                  _MetricView("receivables", "Forderungen", current.receivables, previous.receivables, comparison.receivables_growth, "percentage", ("receivables",)))
    changes = []
    for priority, view in enumerate(candidates):
        delta = _available_delta(view, current_open, base_open)
        if delta is not None:
            formatted = _format_delta(delta, view.change_type)
            changes.append(KeyChange(view.metric_id, view.label, delta, formatted, f"{view.label} {formatted}", view.change_type, priority))
    def flagged(change: KeyChange) -> bool:
        fields = {f"{change.metric_id}_growth", f"{change.metric_id}_growth_minus_revenue_growth",
                  f"{change.metric_id}_change", f"{change.metric_id}_change_bps", change.metric_id}
        return any(flag.metric_name in fields for flag in flags)
    return tuple(sorted(changes, key=lambda change: (not flagged(change), change.priority))[:7])


def _validate_flags(
    comparison: PeriodComparison, flags: tuple[ResearchFlag, ...],
    current_open: set[str], base_open: set[str],
) -> None:
    for flag in flags:
        if flag.period_current != comparison.current_period.period_label or flag.period_previous != comparison.previous_period.period_label:
            raise ResultsUpdateError("Research-Prüfpunkte gehören nicht zum ausgewählten Vergleichspaar.")
        name = flag.metric_name
        for suffix in ("_growth_minus_revenue_growth", "_growth", "_change_bps", "_change"):
            if name.endswith(suffix):
                name = name.removesuffix(suffix)
                break
        dependencies = {
            "calculated_free_cash_flow": ("operating_cash_flow", "capex"),
            "calculated_net_debt_to_ebitda": ("gross_debt", "cash", "ebitda"),
        }.get(name, (name,))
        if name.endswith("_margin"):
            dependencies = (name.removesuffix("_margin"), "revenue")
        elif flag.metric_name.endswith("_growth_minus_revenue_growth"):
            dependencies = (*dependencies, "revenue")
        if flag.rule_id == "cashflow_ebit_divergence":
            dependencies = (*dependencies, "ebit")
        if any(metric in current_open or metric in base_open for metric in dependencies):
            raise ResultsUpdateError("Research-Prüfpunkte verwenden einen ungeklärten historischen Wert; Analyse erneut erstellen.")
        container = "period" if hasattr(comparison.current_period, name) else "metrics"
        current = comparison.current_period if container == "period" else comparison.current_metrics
        previous = comparison.previous_period if container == "period" else comparison.previous_metrics
        if hasattr(current, name) and (
            flag.current_value != getattr(current, name) or flag.previous_value != getattr(previous, name)
        ):
            raise ResultsUpdateError("Research-Prüfpunkte enthalten einen veralteten Kennzahlenstand.")
        if hasattr(comparison, flag.metric_name) and flag.change_value != getattr(comparison, flag.metric_name):
            raise ResultsUpdateError("Research-Prüfpunkte enthalten eine veraltete Vergleichsveränderung.")


def build_results_update(
    history: FinancialHistory, metrics: Sequence[CalculatedPeriodMetrics], comparison: PeriodComparison,
    flags: Sequence[ResearchFlag], *, resolutions: Sequence[PeriodMetricResolution] = (),
    observations: Sequence[ConfirmedMetricObservation] = (), flag_error: str | None = None,
) -> ResultsUpdateSnapshot:
    """Ordne vorhandene Zahlen kompakt; berechne keine Finanzkennzahlen erneut."""
    trend = tuple(history.periods)
    metric_values, flag_values = tuple(metrics), tuple(flags)
    current, previous = comparison.current_period, comparison.previous_period
    if len(trend) != len(metric_values) or not trend:
        raise ResultsUpdateError("Trendperioden und berechnete Kennzahlen müssen zusammenpassen.")
    for name in ("company_name", "currency", "scale"):
        if any(getattr(period, name) != getattr(current, name) for period in (*trend, previous)):
            raise ResultsUpdateError("Vergleich und Trend benötigen dasselbe Unternehmen und dieselben Einheiten.")
    if current.period_end <= previous.period_end or current.period_months != previous.period_months:
        raise ResultsUpdateError("Bitte zwei chronologische, gleich lange Vergleichsperioden wählen.")
    for period in (current, previous):
        for resolution in resolutions:
            if (
                resolution.period_key == period_key_for(period)
                and resolution.status in ("resolved", "equivalent")
                and getattr(period, resolution.canonical_metric) != resolution.resolved_value
            ):
                raise ResultsUpdateError("Aufgelöste Quellenwerte passen nicht zum aktuellen Vergleichsstand; Analyse erneut erstellen.")
    current_open, base_open = _open_metrics(current, resolutions), _open_metrics(previous, resolutions)
    _validate_flags(comparison, flag_values, current_open, base_open)
    severity = {"red": 0, "yellow": 1, "green": 2}
    ordered_flags = tuple(sorted(flag_values, key=lambda flag: severity[flag.severity]))
    views = _metric_views(comparison, current_open)
    cards = _headline_metrics(views, comparison, current_open, base_open, resolutions, observations)
    notices = []
    for role, period, unresolved in (("current", current, current_open), ("base", previous, base_open)):
        for metric in sorted(unresolved):
            resolution = next(item for item in resolutions if item.period_key == period_key_for(period) and item.canonical_metric == metric)
            affected = tuple(view.metric_id for view in views if metric in view.dependencies)
            notices.append(ConflictNotice(period.period_label, metric, resolution.status,
                                           "Historischer Wert ungeklärt – Konflikt zuerst auflösen.", affected, role))
    return ResultsUpdateSnapshot(
        current.company_name, current, previous, cards,
        _key_changes(views, comparison, ordered_flags, current_open, base_open), ordered_flags,
        trend, metric_values, tuple(reference for card in cards for reference in card.source_references),
        tuple(notices), flag_error,
    )
