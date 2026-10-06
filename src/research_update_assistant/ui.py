"""Manuelle Erfassung und Anzeige; alle Finanzformeln liegen im Finance-Kern."""

from dataclasses import dataclass

import streamlit as st

from .calculations import PeriodCompatibilityError, calculate_period_metrics, compare_periods
from .charts import (
    create_cashflow_chart, create_leverage_chart, create_margin_chart,
    create_net_debt_chart, create_result_chart, create_revenue_chart,
    create_working_capital_chart,
)
from .flag_config import FlagConfigError, load_flag_rules
from .flags import ResearchFlag, generate_research_flags
from .expectations import ExpectationCompatibilityError, compare_actual_to_expectation
from .expectations_ui import render_expectation_entry, select_expectation
from .formatting import (
    format_amount, format_basis_points, format_currency_unit,
    format_multiple, format_percentage,
)
from .history import FinancialHistory
from .analysis_selection import HistoryAnalysisResult
from .history_ui import _open_source, render_history_addition, render_history_section
from .source_ui import render_observation_audit
from .results_update import build_results_update
from .results_update_ui import render_results_update
from .input_parsing import (
    CURRENCIES, FINANCIAL_INPUT_GROUPS, SCALE_OPTIONS,
    InputValidationError, ManualPeriodInput, create_manual_history,
)
from .models import CalculatedPeriodMetrics, PeriodComparison
from .pdf_ui import _select_page, render_pdf_section
from .sample_data import load_synthetic_history
from .validation import ConfirmedMetricObservation


# Nur Anzeigenamen, Feldzuordnung und Anzeigeformat; keine Finanzformeln.
# Die letzte Spalte blendet optionale Zeilen aus, wenn alle Werte fehlen.
_OVERVIEW_ROWS = (
    ("Umsatz", "period", "revenue", "amount", False),
    ("EBITDA", "period", "ebitda", "amount", False),
    ("Bereinigtes EBITDA", "period", "adjusted_ebitda", "amount", True),
    ("EBITDA-Marge", "metrics", "ebitda_margin", "percentage", False),
    ("Bereinigte EBITDA-Marge", "metrics", "adjusted_ebitda_margin", "percentage", True),
    ("EBIT", "period", "ebit", "amount", False),
    ("Bereinigtes EBIT", "period", "adjusted_ebit", "amount", True),
    ("EBIT-Marge", "metrics", "ebit_margin", "percentage", False),
    ("Bereinigte EBIT-Marge", "metrics", "adjusted_ebit_margin", "percentage", True),
    ("Nettoergebnis", "period", "net_income", "amount", False),
    ("Nettoergebnis-Marge", "metrics", "net_income_margin", "percentage", False),
    ("Unverwässertes Ergebnis je Aktie (Währung/Aktie)", "period", "basic_eps", "amount", True),
    ("Verwässertes Ergebnis je Aktie (Währung/Aktie)", "period", "diluted_eps", "amount", True),
    ("Geldfluss aus Geschäftstätigkeit", "period", "operating_cash_flow", "amount", False),
    ("Investitionen (Capex, normalisiert)", "metrics", "normalized_capex", "amount", False),
    ("Ausgewiesener Free Cashflow", "period", "reported_free_cash_flow", "amount", True),
    ("Berechneter Free Cashflow", "metrics", "calculated_free_cash_flow", "amount", False),
    ("Ausgewiesene FCF-Marge", "metrics", "reported_free_cash_flow_margin", "percentage", True),
    ("Berechnete FCF-Marge", "metrics", "calculated_free_cash_flow_margin", "percentage", False),
    ("Geldfluss / EBITDA", "metrics", "operating_cash_flow_to_ebitda", "multiple", False),
    ("Berechneter FCF / Nettoergebnis", "metrics", "calculated_free_cash_flow_to_net_income", "multiple", False),
    ("Flüssige Mittel", "period", "cash", "amount", False),
    ("Finanzschulden", "period", "gross_debt", "amount", False),
    ("Ausgewiesene Nettoverschuldung", "period", "reported_net_debt", "amount", True),
    ("Berechnete Nettoverschuldung", "metrics", "calculated_net_debt", "amount", False),
    ("Ausgewiesene Nettoverschuldung / EBITDA", "metrics", "reported_net_debt_to_ebitda", "multiple", True),
    ("Berechnete Nettoverschuldung / EBITDA", "metrics", "calculated_net_debt_to_ebitda", "multiple", False),
    ("Vorräte", "period", "inventory", "amount", False),
    ("Forderungen aus Lieferungen und Leistungen", "period", "receivables", "amount", False),
    ("Verbindlichkeiten aus Lieferungen und Leistungen", "period", "payables", "amount", False),
    ("Berechnetes operatives Working Capital", "metrics", "calculated_operating_working_capital", "amount", False),
    ("Operatives Working Capital / Umsatz", "metrics", "operating_working_capital_to_revenue", "percentage", False),
    ("Vorräte / Umsatz", "metrics", "inventory_to_revenue", "percentage", False),
    ("Forderungen / Umsatz", "metrics", "receivables_to_revenue", "percentage", False),
    ("Capex / Umsatz", "metrics", "capex_to_revenue", "percentage", False),
    ("Bilanzsumme", "period", "total_assets", "amount", True),
    ("Eigenkapital", "period", "equity", "amount", True),
)
_COMPARISON_ROWS = (
    ("Umsatzwachstum", "revenue_growth", "percentage"),
    ("EBITDA-Wachstum", "ebitda_growth", "percentage"),
    ("EBIT-Wachstum", "ebit_growth", "percentage"),
    ("Nettoergebnis-Wachstum", "net_income_growth", "percentage"),
    ("Geldfluss-Wachstum", "operating_cash_flow_growth", "percentage"),
    ("Berechnetes FCF-Wachstum", "calculated_free_cash_flow_growth", "percentage"),
    ("Vorräte-Wachstum", "inventory_growth", "percentage"),
    ("Forderungen-Wachstum", "receivables_growth", "percentage"),
    ("Finanzschulden-Wachstum", "gross_debt_growth", "percentage"),
    ("EBITDA-Margenänderung", "ebitda_margin_change_bps", "bps"),
    ("EBIT-Margenänderung", "ebit_margin_change_bps", "bps"),
    ("Nettoergebnis-Margenänderung", "net_income_margin_change_bps", "bps"),
    ("Berechnete FCF-Margenänderung", "calculated_free_cash_flow_margin_change_bps", "bps"),
    ("Berechnete Nettoverschuldung / EBITDA: Änderung", "calculated_net_debt_to_ebitda_change", "multiple"),
    ("Ausgewiesene Nettoverschuldung / EBITDA: Änderung", "reported_net_debt_to_ebitda_change", "multiple"),
)


@dataclass(frozen=True)
class AnalysisResult:
    """Letzter erfolgreich bestätigter Stand dieser Browser-Sitzung."""

    history: FinancialHistory
    metrics: tuple[CalculatedPeriodMetrics, ...]
    comparisons: tuple[PeriodComparison, ...]
    research_flags: tuple[tuple[ResearchFlag, ...], ...]
    flag_error: str | None = None
    observations: tuple[ConfirmedMetricObservation, ...] = ()


def _clear_analysis() -> None:
    """Verwerfe nur das manuelle Ergebnis; PDF-Prüfdaten bleiben erhalten."""
    st.session_state["manual_analysis_result"] = None
    if st.session_state.get("analysis_source") == "manual":
        st.session_state["analysis_result"] = None


def _prefill_examples() -> None:
    """Fülle die gewählte Anzahl Felder, ohne die Analyse auszulösen."""
    count = st.session_state["period_count"]
    periods = load_synthetic_history().periods[-count:]
    first = periods[0]
    st.session_state["company_name"] = first.company_name
    st.session_state["currency"] = first.currency
    st.session_state["scale"] = first.scale
    for index, period in enumerate(periods):
        prefix = f"period_{index}_"
        for name in ("period_label", "period_end", "period_months"):
            st.session_state[prefix + name] = getattr(period, name)
        for _, definitions in FINANCIAL_INPUT_GROUPS:
            for name, _ in definitions:
                value = getattr(period, name)
                st.session_state[prefix + name] = "" if value is None else str(value)
    _clear_analysis()


def _render_period_input(index: int) -> ManualPeriodInput:
    """Erfasse Metadaten und Zahlentexte, noch keine Finanzkennzahlen."""
    prefix = f"period_{index}_"
    label = st.text_input(
        "Periodenbezeichnung", key=prefix + "period_label",
        placeholder="z. B. FY2025", persist_state="session",
    )
    left, right = st.columns(2)
    with left:
        end = st.date_input(
            "Stichtag", value=None, format="DD.MM.YYYY",
            key=prefix + "period_end", persist_state="session",
        )
    with right:
        st.session_state.setdefault(prefix + "period_months", 12)
        months = st.number_input(
            "Periodendauer in Monaten", min_value=1, value=None, step=1,
            key=prefix + "period_months", persist_state="session",
        )
    values: dict[str, str] = {}
    for group_label, definitions in FINANCIAL_INPUT_GROUPS:
        st.markdown(f"**{group_label}**")
        columns = st.columns(2)
        for position, (name, display_label) in enumerate(definitions):
            with columns[position % 2]:
                values[name] = st.text_input(
                    display_label, key=prefix + name, persist_state="session",
                )
    return ManualPeriodInput(label, end, months, values)


def _submit_analysis(
    company_name: str, currency: str, scale: str, raw_periods: list[ManualPeriodInput]
) -> None:
    """Validiere und delegiere die gesamte Finanzanalyse an die Phase-1-Funktionen."""
    _clear_analysis()
    st.session_state["analysis_result"] = None
    st.session_state["analysis_source"] = "manual"
    try:
        history = create_manual_history(company_name, currency, scale, raw_periods)
        result = _analyse_history(history)
        st.session_state["manual_analysis_result"] = result
        st.session_state["analysis_result"] = result
    except (InputValidationError, PeriodCompatibilityError) as error:
        st.error(str(error))


def _analyse_history(
    history: FinancialHistory, observations: tuple[ConfirmedMetricObservation, ...] = ()
) -> AnalysisResult | None:
    """Gemeinsame Analyse für manuelle und ausdrücklich bestätigte PDF-Daten."""
    try:
        metrics = tuple(calculate_period_metrics(period) for period in history.periods)
        comparisons = tuple(
            compare_periods(current, previous)
            for previous, current in zip(history.periods, history.periods[1:])
        )
    except (InputValidationError, PeriodCompatibilityError) as error:
        st.error(str(error))
        return None
    flag_error = None
    research_flags = ()
    try:
        rules = load_flag_rules()
        research_flags = tuple(tuple(generate_research_flags(c, rules)) for c in comparisons)
    except FlagConfigError as error:
        # Finanzübersicht bleibt verfügbar; keine stillen Ersatzregeln.
        flag_error = str(error)
    return AnalysisResult(
        history, metrics, comparisons, research_flags, flag_error, observations
    )


def _prepare_pdf_analysis(
    history: FinancialHistory, observations: tuple[ConfirmedMetricObservation, ...]
) -> None:
    """Bewahre bestätigte Prüfdaten, ohne die Analyse bereits auszulösen."""
    st.session_state["pdf_ready_history"] = history
    st.session_state["pdf_ready_observations"] = observations
    st.session_state["pdf_analysis_result"] = None
    if st.session_state.get("analysis_source") == "pdf":
        st.session_state["analysis_result"] = None


def _render_pdf_analysis() -> None:
    history = st.session_state["pdf_ready_history"]
    if history is None:
        return
    first = history.periods[0]
    observations = st.session_state["pdf_ready_observations"]
    with st.container(border=True):
        st.subheader("PDF-Daten bereit für Analyse")
        st.text(
            f"Unternehmen: {first.company_name}\n"
            f"Perioden: {' / '.join(p.period_label for p in history.periods)}\n"
            f"Währung: {first.currency}\n"
            f"Einheit: {dict(SCALE_OPTIONS)[first.scale]}\n"
            f"Bestätigte Kennzahlen: {len({o.canonical_metric for o in observations})}"
        )
        st.caption("Die bestätigten Daten sind bereit. Eine erneute Eingabe im manuellen Tab ist nicht nötig.")
        if st.button("Analyse aus bestätigten PDF-Daten starten", key="pdf_start_analysis", type="primary"):
            result = _analyse_history(history, observations)
            st.session_state["pdf_analysis_result"] = result
            st.session_state["analysis_result"] = result
            st.session_state["analysis_source"] = "pdf"
    render_history_addition(history, observations)
    result = st.session_state["pdf_analysis_result"]
    if result is not None:
        _render_results(result, from_pdf=True)


def _format_value(value: float | None, kind: str, *, signed: bool = False) -> str:
    if kind == "percentage":
        return format_percentage(value, signed=signed)
    if kind == "multiple":
        return format_multiple(value, signed=signed)
    if kind == "bps":
        return format_basis_points(value)
    return format_amount(value)


def _table_data(labels: list[str], columns: dict[str, list[str]]) -> dict[str, list[str]]:
    """Ergänze Zeilenbeschriftungen, auch bei einer Periode namens 'Kennzahl'."""
    label_column = "Kennzahl"
    while label_column in columns:
        label_column += " "
    return {label_column: labels, **columns}


def _render_overview(result: AnalysisResult | HistoryAnalysisResult) -> None:
    """Zeige Eingabewerte und bereits berechnete Kennzahlen chronologisch."""
    pairs = tuple(zip(result.history.periods, result.metrics))
    rows = tuple(
        row for row in _OVERVIEW_ROWS
        if not row[4] or any(
            getattr(period if row[1] == "period" else metrics, row[2]) is not None
            for period, metrics in pairs
        )
    )
    columns: dict[str, list[str]] = {}
    for period, metrics in pairs:
        columns[period.period_label] = [
            _format_value(getattr(period if source == "period" else metrics, name), kind)
            for _, source, name, kind, _ in rows
        ]
    st.table(
        _table_data([row[0] for row in rows], columns),
        hide_index=True, hide_header=False, border="horizontal",
        alt="Finanzkennzahlen je Periode in chronologischer Reihenfolge",
    )


def _render_comparisons(result: AnalysisResult | HistoryAnalysisResult) -> None:
    """Zeige ausschliesslich Felder der bestehenden PeriodComparison-Objekte."""
    columns: dict[str, list[str]] = {}
    for comparison in result.comparisons:
        label = f"{comparison.current_period.period_label} vs {comparison.previous_period.period_label}"
        columns[label] = [
            _format_value(getattr(comparison, name), kind, signed=True)
            for _, name, kind in _COMPARISON_ROWS
        ]
    st.table(
        _table_data([row[0] for row in _COMPARISON_ROWS], columns),
        hide_index=True, hide_header=False, border="horizontal",
        alt="Wachstumsraten und Veränderungen ausgewählter Perioden",
    )


def _format_flag_threshold(flag: ResearchFlag) -> str:
    if flag.threshold_unit == "bps":
        value = f"{flag.threshold:.0f} bps"
    elif flag.threshold_unit == "multiple":
        value = f"{flag.threshold:.2f}x"
    elif flag.threshold_unit == "percentage_points":
        value = f"{flag.threshold * 100:.1f} Prozentpunkte"
    else:
        value = f"{flag.threshold:.1%}".replace("%", " %")
    return f"{flag.threshold_operator} {value.replace('.', ',')}"


def _render_research_flags(result: AnalysisResult | HistoryAnalysisResult, *, key_prefix: str = "") -> None:
    """Zeige fertige Prüfpunkte mit Zahlen und Schwellen; keine Regelauswertung."""
    st.header("Research-Prüfpunkte")
    st.caption(
        "Einzelne Auffälligkeiten zur Prüfung durch einen Analysten; keine Anlageempfehlungen. "
        "Die Schwellenwerte sind generische Research-Heuristiken."
    )
    st.caption(
        "Rot: deutliche Veränderung · Gelb: prüfen · Grün: Verbesserung. "
        "Fehlende Kennzahlen lösen keine Regel aus."
    )
    if result.flag_error is not None:
        st.error(f"Research-Prüfpunkte konnten nicht erstellt werden: {result.flag_error}")
        return
    labels = {"red": "Deutliche Veränderung", "yellow": "Prüfen", "green": "Verbesserung"}
    pairs = tuple(zip(result.comparisons, result.research_flags))
    for index, (comparison, flags) in reversed(tuple(enumerate(pairs))):
        st.subheader(f"{comparison.current_period.period_label} vs {comparison.previous_period.period_label}")
        if not flags:
            st.caption("Für diesen Vergleich wurde keine Regel ausgelöst. Fehlende Kennzahlen werden nicht bewertet.")
        for flag in flags:
            with st.container(border=True, key=f"{key_prefix}research_flag_{index}_{flag.rule_id}"):
                st.badge(labels[flag.severity], color=flag.severity)
                st.markdown(f"**{flag.title}**")
                st.text(flag.message)
                st.caption(
                    f"{flag.category} · Regel: {flag.rule_id} · "
                    f"Auslöseschwelle: {_format_flag_threshold(flag)}"
                )


def _render_key_metrics(result: AnalysisResult | HistoryAnalysisResult) -> None:
    """Fünf aktuelle Kennzahlen und vorhandene Vergleichswerte neutral anzeigen."""
    period = result.history.periods[-1]
    metrics = result.metrics[-1]
    comparison = result.comparisons[-1]
    st.header("Kennzahlenüberblick")
    st.caption(
        f"{period.period_label} · Geldbeträge in {format_currency_unit(period.currency, period.scale)} · "
        f"Nettoverschuldung berechnet · Vergleich: {comparison.current_period.period_label} vs {comparison.previous_period.period_label}"
    )
    delta_matches = period == comparison.current_period
    if not delta_matches:
        st.caption(
            f"Karten zeigen {period.period_label}; keine Deltas, weil das gewählte Vergleichspaar "
            f"{comparison.current_period.period_label} vs {comparison.previous_period.period_label} eine andere aktuelle Periode hat."
        )
    definitions = (
        ("Umsatz", format_amount(period.revenue), comparison.revenue_growth, "percentage"),
        ("EBIT-Marge", format_percentage(metrics.ebit_margin), comparison.ebit_margin_change_bps, "bps"),
        ("Berechneter FCF", format_amount(metrics.calculated_free_cash_flow), comparison.calculated_free_cash_flow_growth, "percentage"),
        ("Nettoverschuldung", format_amount(metrics.calculated_net_debt), None, "amount"),
        ("Net Debt / EBITDA", format_multiple(metrics.calculated_net_debt_to_ebitda), comparison.calculated_net_debt_to_ebitda_change, "multiple"),
    )
    with st.container(horizontal=True):
        for label, value, change, kind in definitions:
            delta = None if change is None or not delta_matches else 0 if change == 0 else _format_value(change, kind, signed=True)
            st.metric(label, value, delta, delta_color="off", delta_arrow="off", border=True, height="stretch")


def _render_trend_analysis(result: AnalysisResult | HistoryAnalysisResult, *, key_prefix: str = "") -> None:
    """Binde unabhängige Plotly-Figures ein; keine Finanzformeln in der Darstellung."""
    history = result.history
    metrics = dict(zip(history.periods, result.metrics, strict=True))
    st.header("Trendanalyse")
    st.caption("Erfasste Perioden in chronologischer Reihenfolge. Fehlende Werte werden nicht ergänzt.")
    income, cashflow, balance, working_capital = st.tabs([
        "Ergebnis & Margen", "Cashflow", "Bilanz & Verschuldung", "Working Capital",
    ], key=f"{key_prefix}trend_tabs")
    config = {"scrollZoom": False, "displaylogo": False}
    with income:
        st.caption("Umsatz separat, damit EBITDA und EBIT auf einer eigenen Betragsachse lesbar bleiben.")
        left, right = st.columns(2)
        with left:
            st.plotly_chart(create_revenue_chart(history), key=f"{key_prefix}chart_revenue", config=config, alt="Umsatz je erfasster Periode")
        with right:
            st.plotly_chart(create_result_chart(history), key=f"{key_prefix}chart_result", config=config, alt="EBITDA und EBIT je erfasster Periode")
        st.plotly_chart(create_margin_chart(history, metrics), key=f"{key_prefix}chart_margins", config=config, alt="EBITDA- und EBIT-Marge über die erfassten Perioden")
    with cashflow:
        st.plotly_chart(create_cashflow_chart(history, metrics), key=f"{key_prefix}chart_cashflow", config=config, alt="Geldfluss und getrennte Free-Cashflow-Werte über die Perioden")
    with balance:
        st.plotly_chart(create_net_debt_chart(history, metrics), key=f"{key_prefix}chart_net_debt", config=config, alt="Berechnete und gegebenenfalls ausgewiesene Nettoverschuldung je Stichtag")
        st.caption("Net Debt / EBITDA zeigt nur vorhandene Jahreswerte. Halbjahreswerte werden nicht annualisiert.")
        st.plotly_chart(create_leverage_chart(history, metrics), key=f"{key_prefix}chart_leverage", config=config, alt="Berechnete Nettoverschuldung im Verhältnis zum EBITDA für verfügbare Jahresperioden")
    with working_capital:
        st.plotly_chart(create_working_capital_chart(history, metrics), key=f"{key_prefix}chart_working_capital", config=config, alt="Vorräte, Forderungen und operatives Working Capital im Verhältnis zum Umsatz")


def _render_detail_results(
    result: AnalysisResult | HistoryAnalysisResult, *, from_pdf: bool = False, from_history: bool = False,
) -> None:
    first = result.history.periods[0]
    stand = (
        "Stand: aufgelöste Finanzhistorie und aktuelle Periodenauswahl." if from_history else
        "Stand: zuletzt analysierte PDF-Prüfdaten. Änderungen erneut übernehmen und die PDF-Analyse starten."
        if from_pdf else
        "Stand: zuletzt berechnete Eingaben. Änderungen mit ‚Analyse berechnen‘ übernehmen."
    )
    if result.observations:
        st.caption("Analyse aus bestätigten PDF-/Prüfeingaben. Änderungen im Prüfbereich erst erneut übernehmen.")
        with st.expander("Quellen und bestätigte Korrekturen"):
            render_observation_audit(result.observations)
    st.caption(
        f"{first.company_name} · {stand}"
    )
    key_prefix = "history_" if from_history else "pdf_" if from_pdf else ""
    _render_research_flags(result, key_prefix=key_prefix)
    _render_key_metrics(result)
    st.header("Finanzübersicht")
    st.caption(
        f"{first.company_name} · {first.currency} · {dict(SCALE_OPTIONS)[first.scale]} · "
        f"{stand}"
    )
    st.caption("– bedeutet: nicht verfügbar oder nicht berechenbar. Beträge sind in der gewählten Einheit.")
    if any(p.basic_eps is not None or p.diluted_eps is not None for p in result.history.periods):
        st.caption(f"EPS-Werte sind {first.currency} je Aktie; die Skalierung der übrigen Beträge gilt dafür nicht.")
    _render_overview(result)
    _render_trend_analysis(result, key_prefix=key_prefix)
    st.header("Periodenvergleich")
    st.caption("Margenänderungen in Basispunkten; Leverage-Änderungen als Differenz der Multiplikatoren.")
    _render_comparisons(result)
    if any(period.period_months != 12 for period in result.history.periods):
        st.caption("Net Debt / EBITDA wird für Perioden ohne zwölf Monate nicht berechnet.")


def _render_results(
    result: AnalysisResult | HistoryAnalysisResult, *, from_pdf: bool = False, from_history: bool = False,
) -> None:
    """Kompaktes Ergebnis-Update und unveränderte Detailanalyse getrennt zeigen."""
    if not (from_pdf or from_history):
        _render_detail_results(result)
        return
    prefix = "history_" if from_history else "pdf_"
    compact, detail = st.tabs(
        ["Ergebnis-Update", "Detailanalyse"], key=f"{prefix}analysis_views", on_change="rerun",
    )
    with compact:
        workspace = st.session_state.get("history_workspace") if from_history else None
        comparison = result.comparisons[-1]
        flags = result.research_flags[-1] if result.research_flags else ()
        try:
            snapshot = build_results_update(
                result.history, result.metrics, comparison, flags,
                resolutions=workspace.resolutions if workspace is not None else (),
                observations=result.observations, flag_error=result.flag_error,
            )
            def open_source(report_id: str | None, page_number: int) -> None:
                if report_id is None:
                    _select_page(page_number)
                else:
                    _open_source(report_id, page_number)
            expectation_comparison = None
            expectation = select_expectation(comparison.current_period, key_prefix=prefix)
            if expectation is not None:
                try:
                    expectation_comparison = compare_actual_to_expectation(
                        comparison.current_period, comparison.current_metrics, expectation,
                    )
                except ExpectationCompatibilityError as error:
                    st.error(f"Erwartung konnte nicht verglichen werden: {error}")
            render_results_update(
                snapshot, key_prefix=prefix, on_source=open_source,
                expectation_comparison=expectation_comparison,
            )
        except ValueError as error:
            st.error(f"Ergebnis-Update konnte nicht erstellt werden: {error}")
    with detail:
        _render_detail_results(result, from_pdf=from_pdf, from_history=from_history)


def _render_manual_analysis() -> None:
    """Behalte die manuelle Erfassung als eigenständigen Eingabeweg."""
    st.subheader("1. Unternehmensdaten")
    count = st.selectbox(
        "Anzahl Perioden", (2, 3), key="period_count", on_change=_clear_analysis,
    )
    st.button("Synthetische Beispieldaten verwenden", key="load_examples", on_click=_prefill_examples)
    st.caption("Wähle zuerst die Anzahl Perioden. Die Beispiele laden bei zwei Perioden FY2024/FY2025, bei drei alle Jahre.")

    with st.form("manual_financial_analysis", enter_to_submit=False):
        company_name = st.text_input("Unternehmensname", key="company_name", placeholder="z. B. Synthetic Industrial AG")
        left, right = st.columns(2)
        with left:
            currency = st.selectbox("Währung", CURRENCIES, key="currency")
        with right:
            scale = st.selectbox(
                "Einheit", tuple(value for value, _ in SCALE_OPTIONS), index=None,
                format_func=lambda value: dict(SCALE_OPTIONS)[value], key="scale",
            )
        st.subheader("2. Finanzperioden erfassen")
        st.caption("Leere Finanzfelder bleiben fehlend. 0 ist ein echter Nullwert. Tausendertrenner: Apostroph oder Leerzeichen; Dezimaltrenner: Punkt oder Komma.")
        tabs = st.tabs([
            st.session_state.get(f"period_{index}_period_label") or f"Periode {index + 1}"
            for index in range(count)
        ])
        raw_periods: list[ManualPeriodInput] = []
        for index, tab in enumerate(tabs):
            with tab:
                raw_periods.append(_render_period_input(index))
        st.subheader("3. Daten prüfen")
        st.caption("Prüfe Unternehmen, Einheit, Stichtage und Zahlen. Die Analyse startet erst mit dem folgenden Button.")
        submitted = st.form_submit_button("Analyse berechnen", key="calculate_analysis")

    if submitted:
        _submit_analysis(company_name, currency, scale, raw_periods)
    result = st.session_state["manual_analysis_result"]
    if result is not None:
        _render_results(result)


def _known_expectation_periods() -> tuple:
    """Sammle analysierte Perioden dieser Sitzung für die kompakte Erfassung."""
    periods = []
    for key in ("manual_analysis_result", "pdf_analysis_result", "history_result"):
        result = st.session_state.get(key)
        if result is not None:
            periods.extend(result.history.periods)
    return tuple(periods)


def render_home_page() -> None:
    """Zwei alternative Eingabewege führen zur selben Finanzanalyse."""
    st.set_page_config(page_title="Research Update Assistant", page_icon="📊", layout="wide")
    for key, value in (
        ("analysis_result", None), ("analysis_source", None),
        ("manual_analysis_result", None), ("pdf_ready_history", None),
        ("pdf_ready_observations", ()), ("pdf_analysis_result", None),
        ("scale", "million"), ("expectation_snapshots", ()),
    ):
        st.session_state.setdefault(key, value)
    st.title("Research Update Assistant")
    st.markdown("Strukturierte Auswertung von Unternehmensresultaten")
    st.info("Aktueller Entwicklungsstand: Phase 8A – Erwartungen und Surprise-Analyse")
    st.caption("Wähle einen Eingabeweg. PDF-Prüfung und manuelle Eingabe sind Alternativen und benötigen keine doppelte Erfassung.")
    pdf_tab, manual_tab, history_tab, expectations_tab = st.tabs(
        ["PDF-gestützte Analyse", "Manuelle Eingabe", "Finanzhistorie", "Erwartungen"],
        key="analysis_workflows", on_change="rerun",
    )
    # Alle Bereiche bleiben gerendert, damit ein Tabwechsel keine Entwürfe
    # oder Bestätigungen löscht. Teure Extraktion und Berechnung sind separat
    # durch Upload-Signatur bzw. ausdrückliche Analyse-Buttons geschützt.
    with pdf_tab:
        render_pdf_section(on_accept=_prepare_pdf_analysis)
        _render_pdf_analysis()
    with manual_tab:
        _render_manual_analysis()

    with history_tab:
        render_history_section(
            render_result=lambda result: _render_results(result, from_history=True),
            render_overview=_render_overview,
        )

    with expectations_tab:
        render_expectation_entry(_known_expectation_periods())
