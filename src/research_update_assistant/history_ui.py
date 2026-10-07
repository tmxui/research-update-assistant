"""Session-Workspace und explizite Quellenauswahl; keine Finanzformeln."""

from collections.abc import Callable

import streamlit as st

from .analysis_selection import (
    HistoryAnalysisResult, SelectionValidationError, analyse_selection,
    default_comparison_keys, period_key,
)
from .calculations import calculate_period_metrics
from .export_ui import render_export_section
from .history import FinancialHistory
from .history_workspace import HistoryWorkspace, infer_reported_precision
from .input_parsing import SCALE_OPTIONS
from .pdf_ui import _render_page_browser, _reset_document
from .source_ui import render_observation_audit
from .validation import ConfirmedMetricObservation


def _clear_history_selection() -> None:
    for key in ("history_trend_periods", "history_previous_period", "history_current_period"):
        st.session_state.pop(key, None)
    st.session_state["history_result"] = None


def _next_report() -> None:
    """Leere nur den PDF-Entwurf; archivierte Quellen und Historie bleiben."""
    _reset_document(None)
    st.session_state["pdf_upload_generation"] = st.session_state.get("pdf_upload_generation", 0) + 1
    st.session_state["history_company_confirm"] = False


def _report_id(observations: tuple[ConfirmedMetricObservation, ...]) -> str:
    signature = st.session_state.get("pdf_signature")
    if signature:
        return f"pdf:{signature[0]}:{signature[1]}"
    # Auch unabhängig vom Uploader bestätigte Daten können hinzugefügt werden.
    return "confirmed:" + "|".join(sorted({o.source_document or "manual" for o in observations}))


def render_history_addition(
    history: FinancialHistory, observations: tuple[ConfirmedMetricObservation, ...],
) -> None:
    """Übernimm einen bestätigten Report als weiteren, unveränderten Snapshot."""
    first = history.periods[0]
    workspace = st.session_state.get("history_workspace")
    company = workspace.company_name if workspace is not None else first.company_name
    with st.container(border=True):
        st.subheader("Mehrere Berichte zusammenführen")
        st.caption(f"Finanzhistorie für: {company}. Unternehmensnamen müssen ausdrücklich übereinstimmen.")
        approved = st.checkbox(
            f"Dieser Bericht gehört zur Finanzhistorie von {company}", key="history_company_confirm",
        )
        if st.button("Zur Finanzhistorie hinzufügen", key="history_add_report"):
            if not approved:
                st.error("Bitte die Zugehörigkeit zum Unternehmen der Finanzhistorie bestätigen.")
            else:
                try:
                    existing = workspace or HistoryWorkspace(first.company_name, first.currency, first.scale)
                    precisions = {
                        (o.period_label, o.canonical_metric): precision
                        for o in observations if (precision := infer_reported_precision(o)) is not None
                    }
                    candidates = {c.candidate_id: c for c in st.session_state.get("pdf_candidates", ())}
                    priorities = {
                        (o.period_label, o.canonical_metric): candidates[o.candidate_id].source_priority
                        for o in observations if o.candidate_id in candidates
                    }
                    report_id = _report_id(observations)
                    updated = existing.add_report(
                        history, observations, report_id,
                        precisions=precisions, source_priorities=priorities,
                    )
                    st.session_state["history_workspace"] = updated
                    if updated is not existing:
                        _clear_history_selection()
                    document = st.session_state.get("pdf_document")
                    if document is not None:
                        documents = dict(st.session_state.get("history_documents", {}))
                        documents[report_id] = document
                        st.session_state["history_documents"] = documents
                    st.session_state["history_added_report"] = report_id
                    st.success("Bestätigte Daten sind in der Finanzhistorie. Alle Quellen bleiben erhalten.")
                except ValueError as error:
                    st.error(str(error))
        if st.session_state.get("history_added_report") == _report_id(observations):
            st.caption("Die Historie ist im Tab ‚Finanzhistorie‘ verfügbar.")
            st.button("Weiteren Bericht hinzufügen", key="history_next_report", on_click=_next_report)


def _open_source(report_id: str, page: int) -> None:
    st.session_state["history_source_view"] = report_id
    st.session_state["history_source_page_number"] = page


def _render_source_browser() -> None:
    report_id = st.session_state.get("history_source_view")
    if report_id is None:
        return
    document = st.session_state.get("history_documents", {}).get(report_id)
    if document is None:
        st.info("Für diese Quelle liegt in dieser Sitzung kein PDF-Seitentext vor. Der Audit-Trail bleibt verfügbar.")
        return
    with st.expander(f"Quelle prüfen: {document.file_name}", expanded=True):
        st.caption("Archivierte Quelle der Observation; unabhängig vom aktuell hochgeladenen Bericht.")
        _render_page_browser(document, key_prefix="history_source_")


def _apply_resolution(period, metric: str, selection_key: str, reason_key: str) -> None:
    workspace = st.session_state["history_workspace"]
    selected = st.session_state.get(selection_key)
    try:
        st.session_state["history_workspace"] = workspace.resolve(
            period, metric, selected, reason=st.session_state.get(reason_key, ""),
        )
        st.session_state["history_result"] = None
        if selected is None:
            st.info("Dieser Wert bleibt offen und wird in Berechnungen als fehlend behandelt.")
    except ValueError as error:
        st.error(str(error))


def _render_conflicts(workspace: HistoryWorkspace, labels: dict[str, str]) -> None:
    open_items = [r for r in workspace.resolutions if r.resolved_value is None]
    if not open_items:
        return
    st.subheader("Abweichende historische Werte prüfen")
    st.caption("Abweichung bedeutet noch kein bestätigtes Restatement. Ohne Quellenauswahl bleibt der Wert fehlend.")
    names = _metric_names()
    for resolution in open_items:
        token = str(resolution.period_key)
        metric = resolution.canonical_metric
        key = f"history_resolution_{token}_{metric}"
        reason_key = f"history_reason_{token}_{metric}"
        with st.container(border=True):
            st.markdown(f"**{labels[token]} – {names.get(metric, metric)} · ⚠ Konflikt**")
            if resolution.status == "rounding_difference":
                st.caption("Mögliche Rundungsdifferenz / unterschiedliche Präzision. Beide Werte passen zur dokumentierten Rundung; keine automatische Auswahl.")
            options = {o.observation_id: o for o in resolution.observations}
            for observation in options.values():
                item = observation.confirmed
                st.text(
                    f"{item.source_document or 'Manuelle Eingabe'} · {item.value:.15g} {item.currency} / {item.scale}"
                    f" · PDF-Seite {item.page_number or '—'} · {item.reported_label or metric}"
                )
                if item.page_number is not None:
                    st.button(
                        f"Quelle prüfen · {item.source_document} · Seite {item.page_number}",
                        key=f"history_source_{observation.observation_id}",
                        on_click=_open_source, args=(observation.report_id, item.page_number),
                    )
            if resolution.status == "rounding_difference":
                proposal = min(options.values(), key=lambda o: (o.source_priority, -(o.decimal_places or 0)))
                st.caption(
                    f"Prüfvorschlag nach Quellenrang und Präzision: {proposal.confirmed.source_document or 'Manuelle Eingabe'}"
                    f" · {proposal.value:.15g}. Die Entscheidung liegt bei dir."
                )
            st.selectbox(
                "Historischen Wert auswählen", (None, *options), key=key,
                format_func=lambda oid: "Noch nicht entscheiden" if oid is None else
                f"{options[oid].value:.15g} · {options[oid].confirmed.source_document or 'Manuelle Eingabe'} · Seite {options[oid].confirmed.page_number or '—'}",
            )
            st.text_input("Grund der Quellenauswahl (optional)", key=reason_key)
            st.button(
                "Quellenauswahl übernehmen", key=f"history_apply_resolution_{token}_{metric}",
                on_click=_apply_resolution, args=(resolution.period_key, metric, key, reason_key),
            )


def _metric_names() -> dict[str, str]:
    # Statische Anzeigenamen aus der bereits vorhandenen Formulardefinition.
    from .input_parsing import FINANCIAL_INPUT_GROUPS
    return {name: label for _, definitions in FINANCIAL_INPUT_GROUPS for name, label in definitions}


def _render_history_audit(workspace: HistoryWorkspace, labels: dict[str, str]) -> None:
    with st.expander("Quellen, aktive Werte und Auflösungsverlauf"):
        names = _metric_names()
        st.dataframe([
            {
                "Periode": labels[str(r.period_key)], "Kennzahl": names.get(r.canonical_metric, r.canonical_metric),
                "Status": r.status, "Aktiver Wert": r.resolved_value,
                "Quellen": len(r.observations), "Auswahl": next((
                    f"{o.source_document or 'Manuelle Eingabe'} · Seite {o.page_number or '—'}"
                    for o in r.observations if o.observation_id == r.selected_observation_id
                ), "Alle gleichen Quellen" if r.status == "equivalent" else "Noch offen"),
                "Grund": r.reason,
            } for r in workspace.resolutions
        ], hide_index=True, alt="Aktive Werte und offene Quellenkonflikte je Kennzahl und Periode")
        st.caption("equivalent: durch mehrere Quellen mit exakt gleichem Wert bestätigt. Offene Werte bleiben None.")
        render_observation_audit([o.confirmed for o in workspace.observations])
        actions = {"report_added": "Bericht hinzugefügt", "source_selected": "Quelle ausgewählt",
                   "resolution_deferred": "Entscheidung offen", "resolution_reopened": "Abweichung erneut prüfen"}
        observation_index = {o.observation_id: o for o in workspace.observations}
        def source_name(observation_id: str | None) -> str:
            observation = observation_index.get(observation_id)
            return observation.source_document or "Manuelle Eingabe" if observation else "—"
        st.dataframe([
            {"Schritt": index + 1, "Aktion": actions[event.action],
             "Periode": labels.get(str(event.period_key), "—"),
             "Kennzahl": names.get(event.canonical_metric, event.canonical_metric or "—"),
             "Gewählte Quelle": source_name(event.selected_observation_id),
             "Frühere Quelle": source_name(event.previous_selected_observation_id), "Grund": event.reason}
            for index, event in enumerate(workspace.events)
        ], hide_index=True, alt="Chronologischer Verlauf der Berichtsübernahmen und Quellenentscheidungen")
        for observation in workspace.observations:
            item = observation.confirmed
            if item.page_number is not None:
                st.button(
                    f"Quelle prüfen · {item.period_label} · {item.canonical_metric} · {item.source_document} · Seite {item.page_number}",
                    key=f"history_audit_source_{observation.observation_id}",
                    on_click=_open_source, args=(observation.report_id, item.page_number),
                )


def _reset_history() -> None:
    if not st.session_state.get("history_reset_confirm"):
        return
    st.session_state["history_workspace"] = None
    st.session_state["history_documents"] = {}
    st.session_state["history_source_view"] = None
    st.session_state["history_added_report"] = None
    st.session_state["history_analysis_active"] = False
    _clear_history_selection()
    st.session_state["history_reset_confirm"] = False


def _render_selection(history: FinancialHistory) -> HistoryAnalysisResult | None:
    periods = {period_key(p): p for p in history.periods}
    labels = {key: f"{p.period_label} · {p.period_months} Monate" for key, p in periods.items()}
    defaults = default_comparison_keys(history)
    if defaults is None:
        st.info("Für eine Analyse werden mindestens zwei vergleichbare Perioden benötigt.")
        return None
    st.subheader("Analysezeitraum wählen")
    st.caption("Trendperioden bestimmen die Charts. Vergleichsperioden bestimmen genau einen Vergleich und dessen Research-Prüfpunkte.")
    st.session_state.setdefault("history_trend_periods", list(defaults))
    st.session_state.setdefault("history_previous_period", defaults[0])
    st.session_state.setdefault("history_current_period", defaults[1])
    trend = st.multiselect(
        "Perioden für Analyse auswählen (Trendperioden)", tuple(periods),
        format_func=labels.get, key="history_trend_periods",
        help="Beliebig viele Perioden gleicher Dauer; keine feste Obergrenze. Die vollständige Historie bleibt gespeichert.",
    )
    st.markdown("**Vergleichsperioden**")
    left, right = st.columns(2)
    with left:
        previous = st.selectbox("Basisperiode", tuple(periods), format_func=labels.get, key="history_previous_period")
    with right:
        current = st.selectbox("Aktuelle Periode", tuple(periods), format_func=labels.get, key="history_current_period")
    st.caption(f"Ausgewählter Vergleich: {labels[current]} vs {labels[previous]}.")
    if st.button("Ergebnis-Update erstellen", key="history_analyse", type="primary"):
        st.session_state["history_analysis_active"] = True
    if not st.session_state.get("history_analysis_active"):
        return None
    try:
        result = analyse_selection(history, trend, previous, current)
    except SelectionValidationError as error:
        st.session_state["history_result"] = None
        st.error(str(error))
        return None
    st.session_state["history_result"] = result
    return result


def render_history_section(
    *, render_result: Callable[[HistoryAnalysisResult], None],
    render_overview: Callable[[HistoryAnalysisResult], None],
) -> None:
    """Zeige alle gespeicherten Perioden und ein davon unabhängiges Analysefenster."""
    st.session_state.setdefault("history_workspace", None)
    st.session_state.setdefault("history_documents", {})
    st.session_state.setdefault("history_result", None)
    st.header("Finanzhistorie")
    st.caption("Lokale Browser-Sitzung: Historie und Quellen gehen beim Schliessen der Sitzung oder Server-Neustart verloren.")
    workspace = st.session_state["history_workspace"]
    if workspace is None:
        st.info(
            "Noch keine Finanzhistorie vorhanden. Bestätige einen Bericht im "
            "PDF-Workflow und wähle ‚Zur Finanzhistorie hinzufügen‘."
        )
        st.caption(
            "Ergebnis-Update und Export werden verfügbar, sobald mindestens ein "
            "bestätigter Bericht zur Historie gehört."
        )
        return
    history = workspace.to_financial_history()
    labels = {period_key(p): p.period_label for p in history.periods}
    open_items = [r for r in workspace.resolutions if r.resolved_value is None]
    st.text(
        f"Unternehmen: {workspace.company_name}\n"
        f"Verfügbare Perioden: {' / '.join(p.period_label for p in history.periods)}\n"
        f"Währung / Einheit: {workspace.currency} / {dict(SCALE_OPTIONS)[workspace.scale]}\n"
        f"Berichte: {len(workspace.reports)}\n"
        f"Offene Konflikte: {len(open_items)}"
    )
    sources = sorted({o.confirmed.source_document or "Manuelle Eingabe" for o in workspace.observations})
    st.caption("Quellen: " + " / ".join(sources))
    conflict_periods = {str(r.period_key) for r in open_items}
    if open_items:
        st.warning("Offene Kennzahlen werden als nicht verfügbar behandelt: " + ", ".join(
            f"{labels[str(r.period_key)]} – {_metric_names().get(r.canonical_metric, r.canonical_metric)}" for r in open_items
        ))
    result = _render_selection(history)
    if result is not None:
        render_result(result)
    render_export_section(
        workspace,
        trend_period_tokens=tuple(st.session_state.get("history_trend_periods", ())),
    )
    # Vollständige Tabellen und die Historienverwaltung bleiben erreichbar,
    # stehen aber nicht vor dem kompakten Ergebnis-Update.
    with st.expander("Historientabelle – alle verfügbaren Perioden"):
        st.dataframe([
            {"Periode": p.period_label, "Stichtag": p.period_end.isoformat(), "Monate": p.period_months,
             "Status": "⚠ Konflikt" if period_key(p) in conflict_periods else "Bestätigte Werte verfügbar"}
            for p in history.periods
        ], hide_index=True, alt="Alle gespeicherten Finanzperioden mit Stichtag und Konfliktstatus")
        render_overview(HistoryAnalysisResult(
            history, tuple(calculate_period_metrics(p) for p in history.periods), (), (),
        ))
    _render_conflicts(workspace, labels)
    _render_history_audit(workspace, labels)
    _render_source_browser()
    with st.expander("Finanzhistorie zurücksetzen"):
        confirmed = st.checkbox("Ich möchte die gesamte Finanzhistorie dieser Sitzung löschen", key="history_reset_confirm")
        st.button("Finanzhistorie zurücksetzen", key="history_reset", disabled=not confirmed, on_click=_reset_history)
