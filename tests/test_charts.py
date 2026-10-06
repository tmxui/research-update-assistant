"""Prüfe Chart-Daten und Struktur, ohne Pixel-, Farb- oder Höhentests."""

from dataclasses import replace
from datetime import date
import subprocess
import sys

import plotly.graph_objects as go
import pytest

from research_update_assistant.calculations import calculate_period_metrics
from research_update_assistant.charts import (
    create_cashflow_chart, create_leverage_chart, create_margin_chart,
    create_net_debt_chart, create_result_chart, create_revenue_chart,
    create_working_capital_chart,
)
from research_update_assistant.history import AmbiguousPeriodError, FinancialHistory


@pytest.fixture
def chart_data(periods):
    # Historie und Mapping werden absichtlich unsortiert aufgebaut.
    raw = (periods["FY2025"], periods["FY2023"], periods["FY2024"])
    return FinancialHistory(raw), {period: calculate_period_metrics(period) for period in raw}


def _traces(figure):
    return {trace.name: trace for trace in figure.data}


def _all_charts(history, metrics):
    return (
        create_revenue_chart(history), create_result_chart(history),
        create_margin_chart(history, metrics), create_cashflow_chart(history, metrics),
        create_net_debt_chart(history, metrics), create_leverage_chart(history, metrics),
        create_working_capital_chart(history, metrics),
    )


def test_all_figures_show_chronological_periods(chart_data):
    history, metrics = chart_data
    for figure in _all_charts(history, metrics):
        assert isinstance(figure, go.Figure)
        for trace in figure.data:
            assert tuple(trace.x) == ("FY2023", "FY2024", "FY2025")
        assert tuple(figure.layout.xaxis.categoryarray) == ("FY2023", "FY2024", "FY2025")


def test_revenue_and_result_use_separate_grouped_amount_charts(chart_data):
    history, _ = chart_data
    revenue = create_revenue_chart(history)
    result = create_result_chart(history)
    assert revenue.data[0].name == "Umsatz"
    assert tuple(revenue.data[0].y) == (920, 1000, 1100)
    traces = _traces(result)
    assert set(traces) == {"EBITDA", "EBIT"}
    assert tuple(traces["EBITDA"].y) == (190, 200, 210)
    assert tuple(traces["EBIT"].y) == (145, 150, 143)
    assert result.layout.barmode == "group"


def test_margin_chart_uses_existing_unrounded_decimal_ratios(chart_data):
    history, metrics = chart_data
    traces = _traces(create_margin_chart(history, metrics))
    assert set(traces) == {"EBITDA-Marge", "EBIT-Marge"}
    assert tuple(traces["EBITDA-Marge"].y) == pytest.approx((190 / 920, 0.2, 210 / 1100))
    assert tuple(traces["EBIT-Marge"].y) == pytest.approx((145 / 920, 0.15, 0.13))
    assert all(trace.type == "scatter" for trace in traces.values())


def test_cashflow_chart_uses_ocf_and_calculated_fcf(chart_data):
    history, metrics = chart_data
    traces = _traces(create_cashflow_chart(history, metrics))
    assert set(traces) == {"Geldfluss aus Geschäftstätigkeit", "Berechneter Free Cashflow"}
    assert tuple(traces["Geldfluss aus Geschäftstätigkeit"].y) == (150, 160, 140)
    assert tuple(traces["Berechneter Free Cashflow"].y) == (95, 100, 60)


def test_net_debt_and_leverage_use_calculated_metrics(chart_data):
    history, metrics = chart_data
    assert tuple(create_net_debt_chart(history, metrics).data[0].y) == (185, 200, 270)
    assert tuple(create_leverage_chart(history, metrics).data[0].y) == pytest.approx((185 / 190, 1, 270 / 210))


def test_working_capital_chart_uses_precalculated_ratios(chart_data):
    history, metrics = chart_data
    traces = _traces(create_working_capital_chart(history, metrics))
    assert set(traces) == {"Vorräte / Umsatz", "Forderungen / Umsatz", "Operatives Working Capital / Umsatz"}
    assert tuple(traces["Vorräte / Umsatz"].y) == pytest.approx((140 / 920, 0.15, 190 / 1100))
    assert tuple(traces["Forderungen / Umsatz"].y) == pytest.approx((110 / 920, 0.12, 150 / 1100))
    assert tuple(traces["Operatives Working Capital / Umsatz"].y) == pytest.approx((155 / 920, 0.17, 230 / 1100))


@pytest.mark.parametrize("factory, field, trace_name, value", [
    (create_margin_chart, "ebit_margin", "EBIT-Marge", 0.123456789),
    (create_margin_chart, "ebitda_margin", "EBITDA-Marge", 0.234567891),
    (create_cashflow_chart, "calculated_free_cash_flow", "Berechneter Free Cashflow", 123.456789),
    (create_net_debt_chart, "calculated_net_debt", "Berechnete Nettoverschuldung", 456.789123),
    (create_leverage_chart, "calculated_net_debt_to_ebitda", "Berechnete Nettoverschuldung / EBITDA", 2.34567891),
    (create_working_capital_chart, "inventory_to_revenue", "Vorräte / Umsatz", 0.512345678),
    (create_working_capital_chart, "receivables_to_revenue", "Forderungen / Umsatz", 0.412345678),
    (create_working_capital_chart, "operating_working_capital_to_revenue", "Operatives Working Capital / Umsatz", 0.612345678),
])
def test_chart_does_not_recalculate_or_round_supplied_metrics(chart_data, factory, field, trace_name, value):
    history, metrics = chart_data
    latest = history.periods[-1]
    supplied = {**metrics, latest: replace(metrics[latest], **{field: value})}
    figure = factory(history, supplied)
    assert _traces(figure)[trace_name].y[-1] == value
    assert getattr(metrics[latest], field) != value


def test_leverage_skips_missing_and_half_year_observations(periods):
    middle = replace(periods["FY2024"], period_months=6)
    history = FinancialHistory((periods["FY2025"], middle, periods["FY2023"]))
    metrics = {period: calculate_period_metrics(period) for period in history.periods}
    assert metrics[middle].calculated_net_debt_to_ebitda is None
    figure = create_leverage_chart(history, metrics)
    assert tuple(figure.data[0].x) == ("FY2023", "FY2025")
    assert tuple(figure.data[0].y) == pytest.approx((185 / 190, 270 / 210))
    assert tuple(figure.layout.xaxis.categoryarray) == ("FY2023", "FY2025")
    assert figure.data[0].type == "bar"  # Keine interpolierte Linie über die Lücke.


def test_all_half_year_leverage_has_no_invented_points(periods):
    history = FinancialHistory(tuple(replace(period, period_months=6) for period in periods.values()))
    metrics = {period: calculate_period_metrics(period) for period in history.periods}
    figure = create_leverage_chart(history, metrics)
    assert tuple(figure.data[0].x) == ()
    assert tuple(figure.data[0].y) == ()
    assert "Keine verfügbaren Werte" in figure.layout.annotations[0].text


def test_missing_values_remain_none_and_lines_do_not_bridge_gaps(periods):
    middle = replace(periods["FY2024"], revenue=None, ebitda=None, capex=None, gross_debt=None)
    history = FinancialHistory((periods["FY2025"], middle, periods["FY2023"]))
    metrics = {period: calculate_period_metrics(period) for period in history.periods}
    assert create_revenue_chart(history).data[0].y[1] is None
    assert _traces(create_result_chart(history))["EBITDA"].y[1] is None
    assert _traces(create_cashflow_chart(history, metrics))["Berechneter Free Cashflow"].y[1] is None
    assert create_net_debt_chart(history, metrics).data[0].y[1] is None
    for figure in (create_margin_chart(history, metrics), create_working_capital_chart(history, metrics)):
        for trace in figure.data:
            assert trace.y[1] is None
            assert trace.connectgaps is False


def test_zero_is_a_real_value_not_an_empty_chart(periods):
    history = FinancialHistory((replace(periods["FY2024"], revenue=0),))
    figure = create_revenue_chart(history)
    assert tuple(figure.data[0].y) == (0,)
    assert not figure.layout.annotations
    assert "CHF 0 Mio." in figure.data[0].customdata


def test_all_missing_values_have_neutral_empty_chart_note(periods):
    history = FinancialHistory((replace(periods["FY2024"], revenue=None),))
    figure = create_revenue_chart(history)
    assert tuple(figure.data[0].y) == (None,)
    assert "Keine verfügbaren Werte" in figure.layout.annotations[0].text


def test_reported_cashflow_and_debt_are_separate_series(periods):
    latest = replace(periods["FY2025"], reported_free_cash_flow=75, reported_net_debt=250)
    history = FinancialHistory((periods["FY2024"], latest))
    metrics = {period: calculate_period_metrics(period) for period in history.periods}
    cash = _traces(create_cashflow_chart(history, metrics))
    assert tuple(cash["Berechneter Free Cashflow"].y) == (100, 60)
    assert tuple(cash["Ausgewiesener Free Cashflow"].y) == (None, 75)
    debt = _traces(create_net_debt_chart(history, metrics))
    assert tuple(debt["Berechnete Nettoverschuldung"].y) == (200, 270)
    assert tuple(debt["Ausgewiesene Nettoverschuldung"].y) == (None, 250)


def test_reported_values_do_not_fill_missing_calculated_values(periods):
    period = replace(periods["FY2025"], capex=None, gross_debt=None, reported_free_cash_flow=75, reported_net_debt=250)
    history = FinancialHistory((period,))
    metrics = {period: calculate_period_metrics(period)}
    assert _traces(create_cashflow_chart(history, metrics))["Berechneter Free Cashflow"].y[0] is None
    assert _traces(create_net_debt_chart(history, metrics))["Berechnete Nettoverschuldung"].y[0] is None
    assert tuple(create_leverage_chart(history, metrics).data[0].y) == ()


@pytest.mark.parametrize("currency, scale, unit", [
    ("CHF", "million", "CHF Mio."), ("EUR", "thousand", "EUR Tsd."),
    ("USD", "billion", "USD Mrd."), ("CHF", "unit", "CHF"),
])
def test_currency_scale_and_hover_are_human_readable(periods, currency, scale, unit):
    history = FinancialHistory((replace(periods["FY2025"], currency=currency, scale=scale),))
    figure = create_revenue_chart(history)
    assert unit in figure.layout.yaxis.title.text
    assert currency in figure.data[0].customdata[0]
    assert "1'100" in figure.data[0].customdata[0]
    assert "Umsatz" in figure.data[0].hovertemplate
    assert "revenue" not in figure.data[0].hovertemplate


def test_percentage_and_multiple_axes_keep_original_ratios(chart_data):
    history, metrics = chart_data
    margins = create_margin_chart(history, metrics)
    assert "%" in margins.layout.yaxis.tickformat
    assert "13,00 %" in _traces(margins)["EBIT-Marge"].customdata
    leverage = create_leverage_chart(history, metrics)
    assert leverage.layout.yaxis.ticksuffix == "x"
    assert leverage.data[0].y[-1] == 270 / 210


def test_two_periods_work_for_every_chart(periods):
    history = FinancialHistory((periods["FY2025"], periods["FY2024"]))
    metrics = {period: calculate_period_metrics(period) for period in history.periods}
    for figure in _all_charts(history, metrics):
        assert all(tuple(trace.x) == ("FY2024", "FY2025") for trace in figure.data)


def test_missing_metric_assignment_is_not_silently_recalculated(chart_data):
    history, metrics = chart_data
    del metrics[history.periods[0]]
    with pytest.raises(ValueError, match="Kennzahlen für FY2023 fehlen"):
        create_margin_chart(history, metrics)


def test_source_conflict_requires_explicit_period_selection(periods):
    original = periods["FY2024"]
    restated = replace(original, ebit=145)
    history = FinancialHistory((original, restated))
    with pytest.raises(AmbiguousPeriodError, match="eindeutiger Datensatz"):
        create_result_chart(history)


@pytest.mark.parametrize("change", [{"currency": "EUR"}, {"scale": "thousand"}, {"company_name": "Other AG"}])
def test_mixed_company_currency_or_scale_is_not_plotted_together(periods, change):
    history = FinancialHistory((periods["FY2024"], replace(periods["FY2025"], **change)))
    with pytest.raises(ValueError, match="Währung und Einheit"):
        create_revenue_chart(history)


def test_empty_history_has_readable_error():
    with pytest.raises(ValueError, match="mindestens eine Periode"):
        create_revenue_chart(FinancialHistory())


def test_chart_module_works_without_streamlit():
    script = (
        "import sys; sys.modules['streamlit'] = None; "
        "from research_update_assistant.charts import create_revenue_chart; "
        "from research_update_assistant.sample_data import load_synthetic_history; "
        "assert create_revenue_chart(load_synthetic_history()).data[0].y[-1] == 1100"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("count", [2, 3, 5])
def test_all_charts_support_flexible_two_three_and_five_period_trends(periods, count):
    early = tuple(
        replace(periods["FY2023"], period_label=f"FY{year}", period_end=date(year, 12, 31))
        for year in (2021, 2022)
    )
    full = FinancialHistory((*periods.values(), *early))
    history = FinancialHistory(tuple(reversed(full.periods[-count:])))
    metrics = {period: calculate_period_metrics(period) for period in history.periods}
    labels = tuple(period.period_label for period in history.periods)
    for figure in _all_charts(history, metrics):
        assert tuple(figure.layout.xaxis.categoryarray) == labels
        assert all(tuple(trace.x) == labels for trace in figure.data)
        assert all(len(trace.y) == count for trace in figure.data)
    assert len(full.periods) == 5


def test_five_year_missing_cashflow_and_margin_are_gaps_not_interpolation(periods):
    early = (
        replace(periods["FY2023"], period_label="FY2021", period_end=date(2021, 12, 31)),
        replace(periods["FY2023"], period_label="FY2022", period_end=date(2022, 12, 31),
                capex=None, ebit=None),
    )
    history = FinancialHistory((*periods.values(), *early))
    metrics = {period: calculate_period_metrics(period) for period in history.periods}
    cashflow = _traces(create_cashflow_chart(history, metrics))["Berechneter Free Cashflow"]
    margin = _traces(create_margin_chart(history, metrics))["EBIT-Marge"]
    assert tuple(cashflow.x) == tuple(margin.x) == tuple(f"FY{year}" for year in range(2021, 2026))
    assert cashflow.y[0] == 95 and cashflow.y[1] is None and cashflow.y[2] == 95
    assert margin.y[1] is None
    assert margin.y[0] == margin.y[2] == 145 / 920
    assert margin.connectgaps is False
