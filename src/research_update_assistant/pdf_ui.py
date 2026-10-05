"""PDF-Dokumentbrowser; der manuelle Finance-Workflow bleibt unabhängig."""

from hashlib import sha256

import streamlit as st

from .document_models import ExtractedDocument
from .pdf_extractor import PdfExtractionError, extract_pdf_document, search_document
from .financial_parser import extract_financial_metric_candidates
from .metric_mapping import MetricConfigError, load_metric_config
from .validation_ui import AcceptHistory, render_validation_section


def _reset_document(signature: tuple[str, str] | None) -> None:
    if st.session_state.get("analysis_source") == "pdf":
        st.session_state["analysis_result"] = None
    for key in list(st.session_state):
        if key.startswith("review_"):
            del st.session_state[key]
    st.session_state.update(
        pdf_signature=signature, pdf_document=None, pdf_error=None,
        pdf_page_number=1, pdf_search_query="",
        pdf_candidates=(), pdf_metric_config=None, pdf_candidate_error=None,
        pdf_ready_history=None, pdf_ready_observations=(), pdf_analysis_result=None,
    )


def _select_page(page_number: int) -> None:
    st.session_state["pdf_page_number"] = page_number


def _render_document_summary(document: ExtractedDocument) -> None:
    st.subheader("Dokumentübersicht")
    st.text(f"Dokument: {document.file_name}")
    quality = {
        "good": "Gut", "limited": "Eingeschränkt",
        "possibly_scanned": "Möglicherweise gescannt",
    }[document.extraction_quality]
    st.text(
        f"Seiten: {document.page_count}\n"
        f"Seiten mit extrahierbarem Text: {document.text_page_count} / {document.page_count}\n"
        f"Gefundene Tabellen: {document.total_tables} auf {document.pages_with_tables} Seiten\n"
        f"Dateigrösse: {document.file_size_bytes:,} Bytes\n"
        f"Extraktionsqualität: {quality}"
    )
    if document.metadata_title:
        st.text(f"PDF-Metadaten – Titel: {document.metadata_title}")
    if document.metadata_author:
        st.text(f"PDF-Metadaten – Autor: {document.metadata_author}")
    st.caption(
        "Die Qualität beschreibt nur die technische Extraktion, nicht die Richtigkeit der Inhalte. "
        "PDF-Seitennummern beginnen bei 1 und können von gedruckten Seitenzahlen abweichen."
    )
    with st.expander("Wie entsteht die Qualitätsdiagnose?"):
        st.text(
            "Eine Seite mit weniger als 40 Nicht-Leerzeichen gilt als textarm. "
            "Mindestens 80 % textarme Seiten und weniger als 80 Zeichen je Seite im Mittel "
            "ergeben einen Scan-Verdacht. Mindestens 25 % textarme Seiten, weniger als "
            "200 Zeichen im Mittel oder Parser-Warnungen ergeben eingeschränkte Qualität. "
            "Auch kurze oder leere Dokumente können diese Heuristik auslösen. Es erfolgt keine OCR."
        )
        st.caption(f"Textarme Seiten in diesem Dokument: {document.low_text_page_count} / {document.page_count}")
    for warning in document.extraction_warnings:
        st.warning(warning)


def _render_search(document: ExtractedDocument) -> None:
    st.subheader("Textsuche")
    query = st.text_input("Dokument durchsuchen", key="pdf_search_query", placeholder="z. B. EBIT oder Vorräte")
    if not query.strip():
        return
    matches = search_document(document, query)
    if not matches:
        st.caption("Keine Treffer im extrahierten Text gefunden.")
        return
    st.caption(f"{sum(match.match_count for match in matches)} Treffer auf {len(matches)} Seiten.")
    for match in matches[:100]:
        with st.container(border=True):
            st.text(f"PDF-Seite {match.page_number} · {match.match_count} Treffer")
            st.text(match.snippet)
            st.button(
                f"PDF-Seite {match.page_number} anzeigen", key=f"pdf_search_page_{match.page_number}",
                on_click=_select_page, args=(match.page_number,),
            )
    if len(matches) > 100:
        st.caption("Die ersten 100 Trefferseiten werden angezeigt. Grenze den Suchbegriff bei Bedarf ein.")


def _render_page_browser(document: ExtractedDocument) -> None:
    st.subheader("Seitenbrowser")
    number = st.number_input(
        "PDF-Seite auswählen", min_value=1, max_value=document.page_count,
        step=1, key="pdf_page_number",
    )
    if not isinstance(number, int) or not 1 <= number <= document.page_count:
        st.error("Bitte wähle eine gültige PDF-Seitennummer.")
        return
    page = document.pages[number - 1]
    st.caption(
        f"PDF-Seite {page.page_number} · {page.text_length} extrahierte Zeichen · "
        f"{len(page.tables)} erkannte Tabellen"
        + (f" · PDF-Seitenlabel: {page.printed_page_label}" if page.printed_page_label else "")
    )
    if page.has_text:
        st.caption("Extrahierter Seitentext")
        with st.container(height=260, border=True, key="pdf_page_text"):
            st.text(page.text)
    else:
        st.caption("Kein maschinenlesbarer Text auf dieser Seite verfügbar.")
    st.caption("Tabellen sind rohe Parser-Ergebnisse. Es werden keine Spaltenüberschriften oder Finanzwerte interpretiert.")
    if not page.has_tables:
        st.caption("Keine Tabellen erkannt. Das bedeutet nicht, dass im PDF keine Tabelle vorhanden ist.")
    for table in page.tables:
        st.text(f"Tabelle {table.table_index} · PDF-Seite {table.page_number} · {table.row_count} Zeilen · {table.column_count} Spalten")
        columns = {
            f"Spalte {index + 1}": [row[index] if index < len(row) else None for row in table.rows]
            for index in range(table.column_count)
        }
        st.dataframe(
            columns, hide_index=True, key=f"pdf_table_{number}_{table.table_index}",
            alt=f"Rohe Tabelle {table.table_index} auf PDF-Seite {number}",
        )
        if table.bbox:
            st.caption(f"Tabellenposition in PDF-Punkten (links, oben, rechts, unten): {table.bbox}")


def render_pdf_section(on_accept: AcceptHistory) -> None:
    """Extrahiere einmal je Upload, speichere nur in dieser Browser-Sitzung."""
    st.session_state.setdefault("pdf_signature", None)
    st.session_state.setdefault("pdf_document", None)
    st.session_state.setdefault("pdf_error", None)
    st.header("Geschäftsbericht einlesen")
    st.caption("PDF-Vorschläge werden erst nach deiner Prüfung und Bestätigung in die Finanzanalyse übernommen.")
    uploaded = st.file_uploader(
        "Geschäfts- oder Ergebnisbericht als PDF hochladen", type=["pdf"], key="pdf_upload",
    )
    if uploaded is None:
        if st.session_state["pdf_signature"] is not None:
            _reset_document(None)
        return
    data = uploaded.getvalue()
    signature = (uploaded.name, sha256(data).hexdigest())
    if signature != st.session_state["pdf_signature"]:
        _reset_document(signature)
        try:
            with st.spinner("PDF-Text und Tabellen werden eingelesen …"):
                st.session_state["pdf_document"] = extract_pdf_document(data, file_name=uploaded.name)
        except PdfExtractionError as error:
            st.session_state["pdf_error"] = str(error)
        if st.session_state["pdf_document"] is not None:
            try:
                config = load_metric_config()
                with st.spinner("Finanzstatements und Kennzahl-Kandidaten werden geprüft …"):
                    st.session_state["pdf_candidates"] = extract_financial_metric_candidates(st.session_state["pdf_document"], config)
                st.session_state["pdf_metric_config"] = config
            except MetricConfigError as error:
                st.session_state["pdf_candidate_error"] = str(error)
    if st.session_state["pdf_error"]:
        st.error(st.session_state["pdf_error"])
        return  # Der aufrufende manuelle Workflow läuft trotzdem weiter.
    document = st.session_state["pdf_document"]
    if document is not None:
        _render_document_summary(document)
        _render_search(document)
        _render_page_browser(document)
        if st.session_state.get("pdf_candidate_error"):
            st.error(st.session_state["pdf_candidate_error"])
        elif st.session_state.get("pdf_metric_config"):
            render_validation_section(st.session_state["pdf_metric_config"], st.session_state["pdf_candidates"], _select_page, on_accept)
