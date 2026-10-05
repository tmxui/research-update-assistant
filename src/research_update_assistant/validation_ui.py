"""Einzelprüfung von PDF-Vorschlägen, ohne Finanzformeln in der Oberfläche."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import streamlit as st

from .candidate_models import FinancialMetricCandidate
from .financial_parser import rank_financial_metric_candidates
from .history import FinancialHistory
from .input_parsing import CURRENCIES, SCALE_OPTIONS
from .metric_mapping import MetricConfig
from .validation import (
    ConfirmedMetricObservation, ConfirmedPeriodMetadata, CandidateValidationError,
    confirm_candidate, confirm_manual_metric, create_confirmed_history,
)

AcceptHistory = Callable[[FinancialHistory, tuple[ConfirmedMetricObservation, ...]], None]
_CONFIDENCE = {"high": "Hoch", "medium": "Mittel", "low": "Niedrig"}
_STATEMENTS = {
    "income_statement": "Erfolgsrechnung", "balance_sheet": "Bilanz",
    "cash_flow": "Geldflussrechnung", "other": "Weitere Quelle",
}
TOP_SOURCE_LIMIT = 5
_SOURCE_TYPES = {
    "primary_statement": "Primäres Finanzstatement",
    "notes": "Anhang / Kennzahlendefinition",
    "key_figures": "Kennzahlenübersicht / Mehrjahrestabelle",
    "apm": "APM-Tabelle",
    "highlights": "Highlights / Zusammenfassung",
    "narrative": "Fliesstext",
    "segment": "Segment / Teilbereich",
    "other": "Weitere Quelle",
}


@dataclass(frozen=True)
class _PeriodDraft:
    period_label: str
    period_end: date | None
    period_months: int | None


def _invalidate_pdf_analysis() -> None:
    """Geänderte Prüfdaten müssen erneut übernommen und analysiert werden."""
    st.session_state["pdf_ready_history"] = None
    st.session_state["pdf_ready_observations"] = ()
    st.session_state["pdf_analysis_result"] = None
    if st.session_state.get("analysis_source") == "pdf":
        st.session_state["analysis_result"] = None


def _archive_confirmation(metric: str) -> None:
    """Bewahre frühere Bestätigungen separat; sie sind keine aktiven Finanzwerte."""
    previous = st.session_state["review_records"].get(metric)
    if previous and previous[1]:
        st.session_state["review_audit_history"] = (
            *st.session_state.get("review_audit_history", ()), *previous[1],
        )


def _invalidate_metric(metric: str) -> None:
    """Eine Änderung erfordert eine neue ausdrückliche Bestätigung."""
    _archive_confirmation(metric)
    st.session_state["review_records"].pop(metric, None)
    _invalidate_pdf_analysis()


def _invalidate_all(reset_values: bool = False) -> None:
    for metric in st.session_state["review_records"]:
        _archive_confirmation(metric)
    st.session_state["review_records"] = {}
    st.session_state["review_metadata_confirmed"] = False
    _invalidate_pdf_analysis()
    # Periodenlabels können geändert worden sein: Wertfelder erneut vorbereiten.
    if reset_values:
        for key in list(st.session_state):
            if key.startswith("review_value_") or key.startswith("review_assignment_"):
                del st.session_state[key]


def _reset_editor(
    metric: str, source_id: str, candidate: FinancialMetricCandidate | None,
    periods: tuple, currency: str | None, scale: str | None,
    rejected: bool = False,
) -> None:
    """Stelle Originaldaten vor dem nächsten Aufbau der Widgets wieder her.

    Nur der aktive Kennzahlen-/Quelleneditor wird zurückgesetzt. Extraktion und
    Kandidat bleiben unverändert; frühere Bestätigungen gehören in die Historie,
    nicht zu den noch aktiven Daten. Ohne eindeutigen Header bleiben Werte leer.
    """
    _invalidate_metric(metric)
    for index, period in enumerate(periods):
        label = period.period_label.strip()
        matches = tuple(value for value in candidate.values if value.period_label == label) if candidate else ()
        original = matches[0] if len(matches) == 1 else None
        st.session_state[f"review_value_{metric}_{source_id}_{index}"] = (
            str(original.normalized_value) if original and original.normalized_value is not None else ""
        )
        st.session_state[f"review_assignment_{metric}_{source_id}_{index}"] = None
    st.session_state[f"review_mapping_{metric}_{source_id}"] = candidate.canonical_metric if candidate else metric
    st.session_state[f"review_unit_currency_{metric}_{source_id}"] = candidate.currency if candidate else currency
    st.session_state[f"review_unit_scale_{metric}_{source_id}"] = candidate.scale if candidate else scale
    if rejected:
        st.session_state["review_records"][metric] = ("Abgelehnt", ())


def _period_suggestions(candidates: tuple[FinancialMetricCandidate, ...]) -> tuple:
    """Nur erkannte Labels verwenden; widersprüchliche Metadaten bleiben offen."""
    labels = sorted({v.period_label for c in candidates for v in c.values if v.period_label})
    suggestions = []
    for label in labels:
        values = [v for c in candidates for v in c.values if v.period_label == label]
        ends = {v.period_end for v in values if v.period_end is not None}
        months = {v.period_months for v in values if v.period_months is not None}
        suggestions.append((label, next(iter(ends)) if len(ends) == 1 else None,
                            next(iter(months)) if len(months) == 1 else None))
    return tuple(suggestions[-2:])


def _render_metadata(candidates: tuple[FinancialMetricCandidate, ...]) -> tuple:
    st.subheader("Unternehmen und Vergleichsperioden prüfen")
    st.caption("Zwei Jahres- oder zwei Halbjahresperioden auswählen. Unbekannte Angaben bleiben offen; bitte ergänzen.")
    company = st.text_input("Unternehmen für PDF-Analyse", key="review_company", on_change=_invalidate_all)
    currencies = {c.currency for c in candidates if c.currency}
    scales = {c.scale for c in candidates if c.scale and c.canonical_metric not in ("basic_eps", "diluted_eps")}
    st.session_state.setdefault("review_currency", next(iter(currencies)) if len(currencies) == 1 else None)
    st.session_state.setdefault("review_scale", next(iter(scales)) if len(scales) == 1 else None)
    left, right = st.columns(2)
    with left:
        currency = st.selectbox("Währung der Analyse", CURRENCIES, key="review_currency", index=None, on_change=_invalidate_all)
    with right:
        scale = st.selectbox("Einheit der Analyse", tuple(dict(SCALE_OPTIONS)), key="review_scale", index=None,
                             format_func=lambda x: dict(SCALE_OPTIONS)[x], on_change=_invalidate_all)
    suggestions = _period_suggestions(candidates)
    metadata = []
    for index, column in enumerate(st.columns(2)):
        with column:
            prefix = f"review_period_{index}_"
            label, end, months = suggestions[index] if index < len(suggestions) else ("", None, None)
            st.session_state.setdefault(prefix + "label", label)
            st.session_state.setdefault(prefix + "end", end)
            st.session_state.setdefault(prefix + "months", months)
            st.text_input(f"Periodenbezeichnung {index + 1}", key=prefix + "label", on_change=_invalidate_all, args=(True,))
            st.date_input(f"Stichtag {index + 1}", key=prefix + "end", value=None, format="DD.MM.YYYY", on_change=_invalidate_all)
            st.number_input(f"Monate {index + 1}", key=prefix + "months", value=None, min_value=1, max_value=12, step=1,
                            on_change=_invalidate_all)
            metadata.append(_PeriodDraft(
                st.session_state[prefix + "label"], st.session_state[prefix + "end"], st.session_state[prefix + "months"],
            ))
    return company, currency, scale, tuple(metadata)


def _render_source(candidate: FinancialMetricCandidate, select_page: Callable[[int], None]) -> None:
    st.text(
        f"Originalbezeichnung: {candidate.reported_label}\n"
        f"Statement: {_STATEMENTS[candidate.statement_type]}\n"
        f"Quellentyp: {_SOURCE_TYPES[candidate.source_type]}\n"
        f"Dokument: {candidate.source_document} · PDF-Seite {candidate.page_number}\n"
        f"Erkannte Einheit: {candidate.currency or 'unbekannt'} / {candidate.scale or 'unbekannt'}\n"
        f"Zuordnung: {_CONFIDENCE[candidate.confidence]}"
    )
    for reason in candidate.confidence_reasons:
        st.caption(reason)
    st.text(candidate.source_snippet)
    st.caption("Rohwerte: " + " · ".join(
        f"{v.column_header or 'ohne Header'}: {v.raw_value}" for v in candidate.values
    ))
    st.button(f"Quelle auf Seite {candidate.page_number} prüfen", key="review_show_source",
              on_click=select_page, args=(candidate.page_number,))
    if candidate.is_segment:
        st.warning("Segment-/Regionswert: In Phase 5B für Konzernperioden gesperrt. Bitte eine andere Quelle wählen.")


def _render_values(metric: str, source_id: str, candidate: FinancialMetricCandidate | None,
                   periods: tuple) -> tuple[dict[str, str], dict[str, int | None]]:
    values, assignments = {}, {}
    for index, column in enumerate(st.columns(2)):
        label = periods[index].period_label.strip()
        key = f"review_value_{metric}_{source_id}_{index}"
        matches = tuple(v for v in candidate.values if v.period_label == label) if candidate else ()
        original = matches[0] if len(matches) == 1 else None
        st.session_state.setdefault(key, str(original.normalized_value) if original and original.normalized_value is not None else "")
        with column:
            values[label] = st.text_input(f"Wert {label or f'Periode {index + 1}'}", key=key, persist_state="session",
                                          on_change=_invalidate_metric, args=(metric,))
            if candidate and original is None:
                assignment_key = f"review_assignment_{metric}_{source_id}_{index}"
                choice = st.selectbox(
                    f"Rohwert zu {label or f'Periode {index + 1}'} zuordnen", (None, *range(len(candidate.values))),
                    format_func=lambda i: "Manuelle Ergänzung (kein extrahierter Rohwert)" if i is None else
                    f"{candidate.values[i].column_header or 'ohne Header'}: {candidate.values[i].raw_value}",
                    key=assignment_key, persist_state="session", on_change=_invalidate_metric, args=(metric,),
                )
                assignments[label] = choice
    return values, assignments


def _render_metric_editor(config: MetricConfig, candidates: tuple[FinancialMetricCandidate, ...],
                          periods: tuple, currency: str | None, scale: str | None,
                          select_page: Callable[[int], None]) -> None:
    names = {m.canonical_metric: m.display_name_de for m in config.metrics}
    metric = st.selectbox("Kennzahl prüfen oder ergänzen", tuple(names), format_func=names.get, key="review_metric")
    alternatives = rank_financial_metric_candidates(tuple(c for c in candidates if c.canonical_metric == metric))
    all_sources = {c.candidate_id: c for c in alternatives}
    show_all = False
    if len(alternatives) > TOP_SOURCE_LIMIT:
        show_all = st.checkbox("Weitere Quellen anzeigen", key=f"review_show_all_{metric}", persist_state="session")
        st.caption(f"{len(alternatives)} Quellen insgesamt. Standardmässig werden die besten {TOP_SOURCE_LIMIT} angezeigt.")
    visible = alternatives if show_all else alternatives[:TOP_SOURCE_LIMIT]
    sources = {c.candidate_id: c for c in visible}
    # Eine ausdrücklich gewählte Alternative bleibt bei eingeklappter Liste
    # sichtbar; die UI ersetzt niemals still eine geprüfte Quelle.
    selected = st.session_state.get(f"review_source_{metric}")
    if selected in all_sources and selected not in sources:
        sources[selected] = all_sources[selected]
        st.caption("Deine gewählte weitere Quelle bleibt zusätzlich sichtbar.")
    source_id = st.selectbox(
        "Quelle auswählen", (*sources, "manual"), key=f"review_source_{metric}", persist_state="session",
        format_func=lambda key: "Manuell ergänzen" if key == "manual" else
        f"Quelle {tuple(all_sources).index(key) + 1} · Seite {sources[key].page_number} · {_SOURCE_TYPES[sources[key].source_type]} · {_CONFIDENCE[sources[key].confidence]}",
        on_change=_invalidate_metric, args=(metric,),
    )
    candidate = sources.get(source_id)
    if candidate:
        _render_source(candidate, select_page)
    else:
        st.caption("Manuelle Ergänzung ohne PDF-Herkunft. Leere Felder bleiben fehlend.")
    canonical = st.selectbox("Kennzahl-Zuordnung", tuple(names), index=tuple(names).index(metric),
                             format_func=names.get, key=f"review_mapping_{metric}_{source_id}", persist_state="session",
                             on_change=_invalidate_metric, args=(metric,))
    left, right = st.columns(2)
    ckey, skey = f"review_unit_currency_{metric}_{source_id}", f"review_unit_scale_{metric}_{source_id}"
    st.session_state.setdefault(ckey, candidate.currency if candidate else currency)
    st.session_state.setdefault(skey, candidate.scale if candidate else scale)
    with left:
        selected_currency = st.selectbox("Währung dieser Werte", CURRENCIES, key=ckey, index=None, persist_state="session",
                                         on_change=_invalidate_metric, args=(metric,))
    with right:
        selected_scale = st.selectbox("Einheit dieser Werte", tuple(dict(SCALE_OPTIONS)), key=skey, index=None,
                                     format_func=lambda x: dict(SCALE_OPTIONS)[x], persist_state="session",
                                     on_change=_invalidate_metric, args=(metric,))
    if canonical in ("basic_eps", "diluted_eps"):
        st.caption("EPS ist ein Betrag je Aktie in Währungseinheiten, unabhängig von der Skalierung der übrigen Beträge.")
    elif selected_currency != currency or selected_scale != scale:
        st.caption("Die Einheit dieser Werte weicht von der Analyse ab oder ist noch offen. Bitte Werte und Einheit prüfen; es erfolgt keine Umrechnung.")
    values, assignments = _render_values(metric, source_id, candidate, periods)
    with st.container(border=True, key="review_metric_actions"):
        st.caption("Aktionen für die gesamte Kennzahl (beide Perioden)")
        with st.container(horizontal=True):
            confirmed = st.button("Kennzahl bestätigen", key="review_confirm_metric", disabled=bool(candidate and candidate.is_segment))
            st.button("Änderungen zurücksetzen", key="review_reset_metric", on_click=_reset_editor,
                      args=(metric, source_id, candidate, periods, currency, scale))
            st.button("Kandidat ablehnen", key="review_reject_metric", on_click=_reset_editor,
                      args=(metric, source_id, candidate, periods, currency, scale, True))
    records = st.session_state["review_records"]
    if confirmed:
        try:
            if candidate:
                observations = confirm_candidate(candidate, canonical_metric=canonical, values=values,
                                                 currency=selected_currency, scale=selected_scale,
                                                 period_assignments=assignments)
            else:
                observations = confirm_manual_metric(canonical, values=values, currency=selected_currency, scale=selected_scale)
            status = "Geändert" if any(o.status == "changed" for o in observations) else "Bestätigt"
            if records.get(metric, (None, ()))[1] != observations:
                _archive_confirmation(metric)
            records[metric] = (status if observations else "Fehlend", observations)
            _invalidate_pdf_analysis()
        except CandidateValidationError as error:
            st.error(str(error))
    st.text("Status: " + records.get(metric, ("Vorgeschlagen" if alternatives else "Fehlend", ()))[0])


def render_validation_section(config: MetricConfig, candidates: tuple[FinancialMetricCandidate, ...],
                              select_page: Callable[[int], None], on_accept: AcceptHistory) -> None:
    """Einzelbestätigung und abschliessende Übernahme sind zwei getrennte Schritte."""
    st.session_state.setdefault("review_records", {})
    st.session_state.setdefault("review_audit_history", ())
    st.header("Extrahierte Finanzdaten prüfen")
    st.caption("Vorschläge sind ungeprüft. Auch ‚Hoch‘ garantiert keine korrekten Zahlen. Bestätige jede gewünschte Kennzahl einzeln.")
    st.caption(f"{len(candidates)} Kandidaten. Alternative Quellen bleiben auswählbar. Fehlende Kennzahlen können manuell ergänzt werden.")
    company, currency, scale, periods = _render_metadata(candidates)
    _render_metric_editor(config, candidates, periods, currency, scale, select_page)
    records = st.session_state["review_records"]
    summary = []
    names = {m.canonical_metric: m.display_name_de for m in config.metrics}
    for metric in config.metrics:
        proposed = any(c.canonical_metric == metric.canonical_metric for c in candidates)
        status, observations = records.get(metric.canonical_metric, ("Vorgeschlagen" if proposed else "Fehlend", ()))
        summary.append({
            "Kennzahl": metric.display_name_de, "Status": status,
            "Bestätigte Zuordnung": names[observations[0].canonical_metric] if observations else "–",
        })
    st.dataframe(summary, hide_index=True, alt="Prüfstatus je Kennzahl")
    approved = st.checkbox("Unternehmen, Perioden, Währung und Einheit sind von mir geprüft", key="review_metadata_confirmed",
                           on_change=_invalidate_pdf_analysis)
    st.caption("Nur einzeln bestätigte Werte werden übernommen. Vorgeschlagene, abgelehnte oder fehlende Werte bleiben None. Es erfolgt keine automatische Umrechnung.")
    if st.button("Bestätigte Daten übernehmen", key="review_accept"):
        if not approved:
            st.error("Bitte zuerst Unternehmen, Perioden und Einheiten bestätigen.")
            return
        observations = tuple(o for _, items in records.values() for o in items)
        try:
            if not observations:
                raise CandidateValidationError("Bitte mindestens eine Kennzahl bestätigen.")
            checked_periods = tuple(ConfirmedPeriodMetadata(p.period_label.strip(), p.period_end, p.period_months) for p in periods)
            history = create_confirmed_history(company, currency, scale, checked_periods, observations)
            on_accept(history, observations)
            st.success("Bestätigte PDF-Prüfdaten sind bereit. Starte die Analyse mit dem PDF-Analyse-Button.")
        except (CandidateValidationError, ValueError) as error:
            st.error(str(error))
