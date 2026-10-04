"""Plotly-Darstellungen vorhandener Periodenwerte und berechneter Kennzahlen.

Keine Finanzformeln und keine Streamlit-Abhängigkeit. Kennzahlen werden ihrem
FinancialPeriod-Objekt zugeordnet, statt über Labels oder Eingabepositionen.
FinancialHistory liefert die chronologische Reihenfolge. Für Quellenkonflikte
muss vorher ausdrücklich eine normalisierte Periodenauswahl getroffen werden.
"""

from collections.abc import Mapping, Sequence
from typing import Literal

import plotly.graph_objects as go

from .formatting import format_currency_unit, format_money, format_multiple
from .history import AmbiguousPeriodError, FinancialHistory
from .models import CalculatedPeriodMetrics, FinancialPeriod


PeriodMetrics = Mapping[FinancialPeriod, CalculatedPeriodMetrics]
ValueKind = Literal["amount", "percentage", "multiple"]
_COLORS = ("#334e68", "#468faf", "#756c95", "#868e96")


def _validate_history(history: FinancialHistory) -> None:
    if not history.periods:
        raise ValueError("Für die Diagramme wird mindestens eine Periode benötigt.")
    first = history.periods[0]
    for name in ("company_name", "currency", "scale"):
        if any(getattr(period, name) != getattr(first, name) for period in history.periods):
            raise ValueError("Diagramme benötigen dasselbe Unternehmen, dieselbe Währung und Einheit.")
    labels = {period.period_label for period in history.periods}
    dates = {period.period_end for period in history.periods}
    if len(labels) != len(history.periods) or len(dates) != len(history.periods):
        raise AmbiguousPeriodError(
            "Für Diagramme muss zuerst ein eindeutiger Datensatz je Periode ausgewählt werden."
        )


def _period_values(history: FinancialHistory, name: str) -> list[float | None]:
    return [getattr(period, name) for period in history.periods]


def _metric_values(history: FinancialHistory, metrics: PeriodMetrics, name: str) -> list[float | None]:
    values = []
    for period in history.periods:
        if period not in metrics:
            raise ValueError(f"Berechnete Kennzahlen für {period.period_label} fehlen.")
        values.append(getattr(metrics[period], name))
    return values


def _figure(history: FinancialHistory, title: str, kind: ValueKind = "amount") -> go.Figure:
    _validate_history(history)
    first = history.periods[0]
    axis_title = (
        f"Werte in {format_currency_unit(first.currency, first.scale)}" if kind == "amount"
        else "Marge / Verhältnis" if kind == "percentage" else "Multiplikator"
    )
    figure = go.Figure()
    figure.update_layout(
        title=dict(text=title, x=0), template="plotly_white", height=350,
        separators=".'",
        barmode="group", hovermode="closest",
        margin=dict(l=35, r=15, t=60, b=75),
        legend=dict(orientation="h", y=-0.2, x=0, font=dict(size=12)),
        xaxis=dict(
            title=None, type="category", categoryorder="array",
            categoryarray=[period.period_label for period in history.periods],
        ),
        yaxis=dict(
            title=axis_title, rangemode="tozero", zeroline=True,
            tickformat=".0%" if kind == "percentage" else ",.2f" if kind == "multiple" else ",~g",
            ticksuffix="x" if kind == "multiple" else "",
        ),
    )
    return figure


def _hover_value(value: float | None, period: FinancialPeriod, kind: ValueKind) -> str:
    if value is None:
        return "–"
    if kind == "percentage":
        return f"{value:.2%}".replace(".", ",").replace("%", " %")
    if kind == "multiple":
        return format_multiple(value)
    return format_money(value, period.currency, period.scale)


def _add_series(
    figure: go.Figure, periods: Sequence[FinancialPeriod], values: Sequence[float | None],
    name: str, *, kind: ValueKind = "amount", line: bool = False, reported: bool = False,
) -> None:
    """Übernehme Rohwerte unverändert; formatiere nur Hover-Texte."""
    color = _COLORS[len(figure.data) % len(_COLORS)]
    common = dict(
        x=[period.period_label for period in periods], y=list(values), name=name,
        customdata=[_hover_value(value, period, kind) for period, value in zip(periods, values, strict=True)],
        hovertemplate=f"%{{x}}<br>{name}: %{{customdata}}<extra></extra>",
    )
    if line:
        figure.add_trace(go.Scatter(
            **common, mode="lines+markers", connectgaps=False,
            line=dict(color=color, width=2, dash="dash" if reported else "solid"),
            marker=dict(size=7),
        ))
    else:
        figure.add_trace(go.Bar(**common, marker_color=color))


def _finish(figure: go.Figure) -> go.Figure:
    if not any(value is not None for trace in figure.data for value in trace.y):
        figure.add_annotation(
            text="Keine verfügbaren Werte für diese Darstellung.",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
        )
    return figure


def create_revenue_chart(history: FinancialHistory) -> go.Figure:
    """Wie entwickelt sich der Umsatz? Eigene Achse für den grösseren Betrag."""
    figure = _figure(history, "Umsatzentwicklung")
    _add_series(figure, history.periods, _period_values(history, "revenue"), "Umsatz")
    return _finish(figure)


def create_result_chart(history: FinancialHistory) -> go.Figure:
    """Wie entwickeln sich EBITDA und EBIT im Vergleich zueinander?"""
    figure = _figure(history, "Ergebnisentwicklung")
    for name, label in (("ebitda", "EBITDA"), ("ebit", "EBIT")):
        _add_series(figure, history.periods, _period_values(history, name), label)
    return _finish(figure)


def create_margin_chart(history: FinancialHistory, metrics: PeriodMetrics) -> go.Figure:
    """Wie verändern sich die bereits berechneten EBITDA- und EBIT-Margen?"""
    figure = _figure(history, "Margenentwicklung", "percentage")
    for name, label in (("ebitda_margin", "EBITDA-Marge"), ("ebit_margin", "EBIT-Marge")):
        _add_series(figure, history.periods, _metric_values(history, metrics, name), label, kind="percentage", line=True)
    return _finish(figure)


def create_cashflow_chart(history: FinancialHistory, metrics: PeriodMetrics) -> go.Figure:
    """Wie entwickeln sich Geldfluss und getrennte FCF-Definitionen?"""
    figure = _figure(history, "Cashflow-Entwicklung")
    _add_series(figure, history.periods, _period_values(history, "operating_cash_flow"), "Geldfluss aus Geschäftstätigkeit")
    _add_series(figure, history.periods, _metric_values(history, metrics, "calculated_free_cash_flow"), "Berechneter Free Cashflow")
    reported = _period_values(history, "reported_free_cash_flow")
    if any(value is not None for value in reported):
        _add_series(figure, history.periods, reported, "Ausgewiesener Free Cashflow")
    return _finish(figure)


def create_net_debt_chart(history: FinancialHistory, metrics: PeriodMetrics) -> go.Figure:
    """Wie entwickelt sich die Nettoverschuldung je Stichtag?"""
    figure = _figure(history, "Nettoverschuldung")
    _add_series(figure, history.periods, _metric_values(history, metrics, "calculated_net_debt"), "Berechnete Nettoverschuldung")
    reported = _period_values(history, "reported_net_debt")
    if any(value is not None for value in reported):
        _add_series(figure, history.periods, reported, "Ausgewiesene Nettoverschuldung")
    return _finish(figure)


def create_leverage_chart(history: FinancialHistory, metrics: PeriodMetrics) -> go.Figure:
    """Zeige nur vorhandene Jahres-Leverage-Werte; keine Linie über Datenlücken."""
    figure = _figure(history, "Net Debt / EBITDA", "multiple")
    values = _metric_values(history, metrics, "calculated_net_debt_to_ebitda")
    available = tuple((period, value) for period, value in zip(history.periods, values, strict=True) if value is not None)
    periods = tuple(period for period, _ in available)
    _add_series(figure, periods, [value for _, value in available], "Berechnete Nettoverschuldung / EBITDA", kind="multiple")
    figure.update_xaxes(categoryarray=[period.period_label for period in periods])
    return _finish(figure)


def create_working_capital_chart(history: FinancialHistory, metrics: PeriodMetrics) -> go.Figure:
    """Wie verändern sich Vorräte, Forderungen und operatives Working Capital relativ zum Umsatz?"""
    figure = _figure(history, "Working Capital im Verhältnis zum Umsatz", "percentage")
    for name, label in (
        ("inventory_to_revenue", "Vorräte / Umsatz"),
        ("receivables_to_revenue", "Forderungen / Umsatz"),
        ("operating_working_capital_to_revenue", "Operatives Working Capital / Umsatz"),
    ):
        _add_series(figure, history.periods, _metric_values(history, metrics, name), label, kind="percentage", line=True)
    return _finish(figure)
