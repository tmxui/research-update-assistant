"""Kompaktes Ergebnis-Update aus einem vorbereiteten Präsentations-Snapshot.

Keine Finanzformeln, Quellenauswahl oder Session-State-Snapshots: alle Werte,
Veränderungen und Prüfpunkte kommen aus dem testbaren Results-Update-Builder.
"""

from collections.abc import Callable

import streamlit as st

from .charts import create_cashflow_chart, create_margin_chart, create_revenue_chart
from .flags import ResearchFlag
from .formatting import format_currency_unit, format_money
from .results_update import ResultsUpdateSnapshot, SourceReference


SourceCallback = Callable[[str | None, int], None]
_INPUT_LABELS = {
    "revenue": "Umsatz", "ebitda": "EBITDA", "adjusted_ebitda": "Bereinigtes EBITDA",
    "ebit": "EBIT", "adjusted_ebit": "Bereinigtes EBIT", "net_income": "Nettoergebnis",
    "operating_cash_flow": "Geldfluss aus Geschäftstätigkeit", "capex": "Investitionen (Capex)",
    "reported_free_cash_flow": "Ausgewiesener FCF", "cash": "Flüssige Mittel",
    "gross_debt": "Finanzverbindlichkeiten", "reported_net_debt": "Ausgewiesene Nettoverschuldung",
    "inventory": "Vorräte", "receivables": "Forderungen", "payables": "Verbindlichkeiten aus Lieferungen und Leistungen",
    "total_assets": "Bilanzsumme", "equity": "Eigenkapital",
    "basic_eps": "Unverwässertes Ergebnis je Aktie", "diluted_eps": "Verwässertes Ergebnis je Aktie",
}
_DERIVED_METRICS = (
    "ebit_margin", "calculated_free_cash_flow", "calculated_net_debt",
    "calculated_net_debt_to_ebitda",
)


def _render_headlines(snapshot: ResultsUpdateSnapshot, key_prefix: str) -> None:
    if not snapshot.headline_metrics:
        st.caption("Für das gewählte Vergleichspaar sind keine Headline-Kennzahlen verfügbar.")
        return
    with st.container(horizontal=True, wrap=True, gap="small"):
        for metric in snapshot.headline_metrics[:7]:
            # Feste Kartenbreite erzwingt auch auf breiten Bildschirmen eine
            # lesbare Grösse; auf schmalen Geräten begrenzt der Elterncontainer.
            with st.container(width=260, key=f"{key_prefix}update_metric_{metric.metric_id}"):
                delta = 0 if metric.delta == 0 else metric.formatted_delta
                delta_unit = {"percentage": "%", "bps": "bps", "multiple": "x"}[metric.change_type]
                description = (
                    f"{delta_unit} · ggü. {metric.base_period_label}" if metric.delta == 0 else
                    f"ggü. {metric.base_period_label}" if metric.delta is not None else None
                )
                st.metric(
                    metric.label_de, metric.formatted_value, delta,
                    delta_color="off", delta_arrow="off", border=True,
                    delta_description=description,
                )
                st.caption(metric.current_period_label)


def _render_changes(snapshot: ResultsUpdateSnapshot, key_prefix: str) -> None:
    st.subheader("Wichtigste Veränderungen")
    with st.container(key=f"{key_prefix}update_changes", gap="xxsmall"):
        for change in snapshot.key_changes[:7]:
            st.text(change.text)
        if not snapshot.key_changes:
            st.caption("Keine berechenbaren Veränderungen für das gewählte Vergleichspaar.")


def _render_flag(flag: ResearchFlag, index: int, key_prefix: str) -> None:
    labels = {"red": "Deutliche Veränderung", "yellow": "Prüfen", "green": "Verbesserung"}
    with st.container(border=True, key=f"{key_prefix}update_flag_{index}_{flag.rule_id}", gap="xxsmall"):
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.badge(labels[flag.severity], color=flag.severity)
            st.markdown(f"**{flag.title}**")
        st.caption(flag.message)


def _render_flags(snapshot: ResultsUpdateSnapshot, key_prefix: str) -> None:
    st.subheader("Research-Prüfpunkte")
    if snapshot.flag_error is not None:
        st.error(f"Research-Prüfpunkte konnten nicht erstellt werden: {snapshot.flag_error}")
        return
    for index, flag in enumerate(snapshot.flags[:5]):
        _render_flag(flag, index, key_prefix)
    if len(snapshot.flags) > 5:
        with st.expander("Alle Prüfpunkte anzeigen"):
            st.caption(f"Weitere {len(snapshot.flags) - 5} Prüfpunkte zum selben Vergleichspaar.")
            for index, flag in enumerate(snapshot.flags[5:], start=5):
                _render_flag(flag, index, key_prefix)
    if not snapshot.flags:
        st.caption("Für diesen Vergleich wurde keine Regel ausgelöst. Fehlende Kennzahlen werden nicht bewertet.")


def _render_context(snapshot: ResultsUpdateSnapshot, key_prefix: str) -> None:
    st.subheader("Historischer Kontext")
    st.caption("Trendperioden: " + " / ".join(period.period_label for period in snapshot.trend_periods))
    history = snapshot.trend_history
    metrics = dict(zip(history.periods, snapshot.trend_metrics, strict=True))
    # Nur verfügbare Themen zeigen. Die bestehenden Chart-Funktionen bewahren
    # None-Lücken, ausgewiesene/berechnete Reihen und ungerundete Eingaben.
    figures = []
    if any(period.revenue is not None for period in history.periods):
        figures.append(("revenue", create_revenue_chart(history), "Umsatz über die ausgewählten Trendperioden"))
    if any(item.ebit_margin is not None or item.ebitda_margin is not None for item in snapshot.trend_metrics):
        figures.append(("margins", create_margin_chart(history, metrics), "EBIT- und EBITDA-Margen über die ausgewählten Trendperioden"))
    if any(
        period.operating_cash_flow is not None or period.reported_free_cash_flow is not None
        or item.calculated_free_cash_flow is not None
        for period, item in zip(history.periods, snapshot.trend_metrics, strict=True)
    ):
        figures.append(("cashflow", create_cashflow_chart(history, metrics), "Geldfluss sowie getrennte ausgewiesene und berechnete Free-Cashflow-Werte"))
    if not figures:
        st.caption("Für den ausgewählten Trend sind keine Werte für die kompakten Diagramme verfügbar.")
        return
    for column, (name, figure, alt) in zip(st.columns(len(figures)), figures, strict=True):
        with column:
            figure.update_layout(
                height=300, margin=dict(l=25, r=15, t=45, b=70),
                title=dict(font=dict(size=15)), legend=dict(font=dict(size=10)),
            )
            st.plotly_chart(
                figure, key=f"{key_prefix}update_chart_{name}", alt=alt,
                config={"scrollZoom": False, "displaylogo": False},
            )


def _render_reference(
    reference: SourceReference, index: int, key_prefix: str, on_source: SourceCallback | None,
) -> None:
    role = "Aktuell" if reference.role == "current" else "Basis"
    source_state = "Aktive Quelle" if reference.is_active else "Alternative, nicht aktiv"
    input_label = _INPUT_LABELS.get(reference.input_metric, reference.input_metric)
    document = reference.source_document or "Manuelle Eingabe"
    page = f" · PDF-Seite {reference.page_number}" if reference.page_number is not None else ""
    st.text(
        f"{source_state} · {role} · {reference.period_label}\n"
        f"{input_label}: {format_money(reference.value, reference.confirmed.currency, reference.confirmed.scale)}\n"
        f"{document}{page}\n"
        f"Originalbezeichnung: {reference.reported_label or '–'}"
    )
    status = "Analystenkorrektur bestätigt" if reference.confirmed.status == "changed" else "Bestätigt"
    if reference.resolution_status == "equivalent":
        status += " · Durch mehrere Quellen bestätigt"
    elif reference.resolution_status in ("unresolved", "rounding_difference"):
        status += " · Historischer Wert ungeklärt"
    elif reference.resolution_status == "resolved":
        status += " · Quelle ausdrücklich ausgewählt" if reference.is_active else " · Andere Quelle ausgewählt"
    st.caption(status)
    if on_source is not None and reference.page_number is not None:
        st.button(
            f"Quelle prüfen · {document} · Seite {reference.page_number}",
            key=f"{key_prefix}update_source_{index}_{reference.observation_id or index}",
            on_click=on_source, args=(reference.report_id, reference.page_number),
        )


def _render_sources(snapshot: ResultsUpdateSnapshot, key_prefix: str, on_source: SourceCallback | None) -> None:
    with st.expander("Quellen"):
        if not snapshot.source_summary:
            st.caption("Für diese Kennzahlen liegen keine einzelnen Quellenreferenzen vor.")
            return
        st.caption("Aktuelle und Basiswerte mit Originalbezeichnungen. Bei berechneten Kennzahlen werden ihre Eingangsgrössen gezeigt.")
        for metric in snapshot.headline_metrics:
            references = tuple(
                (index, reference) for index, reference in enumerate(snapshot.source_summary)
                if reference.headline_metric_id == metric.metric_id
            )
            if not references:
                continue
            st.markdown(f"**{metric.label_de}**")
            if metric.metric_id in _DERIVED_METRICS:
                st.caption("Berechnet aus bestätigten Eingangsgrössen; keine direkt ausgewiesene PDF-Kennzahl.")
            active = tuple(pair for pair in references if pair[1].is_active)
            alternatives = tuple(pair for pair in references if not pair[1].is_active)
            for index, reference in active:
                _render_reference(reference, index, key_prefix, on_source)
            if alternatives:
                with st.expander(f"Alternative Quellen – {metric.label_de}"):
                    for index, reference in alternatives:
                        _render_reference(reference, index, key_prefix, on_source)


def render_results_update(
    snapshot: ResultsUpdateSnapshot, *, key_prefix: str, on_source: SourceCallback | None = None,
) -> None:
    """Zeige maximal sieben Karten, sieben Änderungen und drei bestehende Charts.

    Der optionale Callback öffnet die Originalquelle. report_id=None steht für
    den aktuell geprüften Einzelbericht; archivierte History-Quellen tragen
    ihre stabile Berichts-ID. Herkunft wird niemals aus der PDF-Reihenfolge
    oder aus dem zuletzt hochgeladenen Dokument geraten.
    """
    st.header("Ergebnis-Update")
    st.subheader(f"{snapshot.current_period.period_label} Ergebnis-Update")
    st.caption(
        f"{snapshot.company_name} · Vergleich mit {snapshot.base_period.period_label} · "
        f"Geldbeträge in {format_currency_unit(snapshot.current_period.currency, snapshot.current_period.scale)}"
    )
    for conflict in snapshot.conflicts:
        label = _INPUT_LABELS.get(conflict.canonical_metric, conflict.canonical_metric)
        st.warning(f"{conflict.period_label} · {label}: {conflict.message}")
    _render_headlines(snapshot, key_prefix)
    _render_changes(snapshot, key_prefix)
    _render_flags(snapshot, key_prefix)
    _render_context(snapshot, key_prefix)
    _render_sources(snapshot, key_prefix, on_source)
