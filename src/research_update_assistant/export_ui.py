"""Streamlit-Downloadbereich für die unabhängige In-Memory-Export-Schicht."""

from collections.abc import Sequence
import re

import streamlit as st

from .exports import ExportValidationError, create_excel_export, create_financial_history_csv
from .history_workspace import HistoryWorkspace, PeriodKey


def _safe_filename(company_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", company_name.strip()).strip("_").lower()
    return slug or "financial_history"


def _period_label(workspace: HistoryWorkspace, key: PeriodKey) -> str:
    aliases = workspace.period_aliases(key)
    return aliases[0] if aliases else f"{key.period_end.isoformat()} ({key.period_months}M)"


def render_export_section(
    workspace: HistoryWorkspace,
    *,
    trend_period_tokens: Sequence[str] = (),
) -> None:
    """Biete Excel und CSV an, ohne Dateien dauerhaft lokal abzulegen."""
    st.subheader("Export")
    scope = st.radio(
        "Perioden für den Export",
        ("Alle verfügbaren Perioden", "Aktuell ausgewählte Trendperioden"),
        horizontal=True,
        key="history_export_scope",
    )
    available = {str(key): key for key in workspace.period_keys}
    if scope == "Aktuell ausgewählte Trendperioden":
        selected = tuple(
            available[token] for token in trend_period_tokens if token in available
        )
        if not selected:
            st.info("Wähle zuerst mindestens eine Trendperiode für den Export aus.")
            return
    else:
        selected = workspace.period_keys

    selected = tuple(sorted(selected))
    st.caption(
        "Exportierte Perioden: "
        + " / ".join(_period_label(workspace, key) for key in selected)
        + ". Fehlende Werte und offene Konflikte bleiben leer."
    )
    try:
        xlsx = create_excel_export(
            workspace,
            selected_period_keys=selected,
            expectations=tuple(st.session_state.get("expectation_snapshots", ())),
            guidance=tuple(st.session_state.get("guidance_snapshots", ())),
        )
        csv_data = create_financial_history_csv(
            workspace, selected_period_keys=selected,
        )
    except ExportValidationError as error:
        st.error(f"Export konnte nicht erstellt werden: {error}")
        return

    basename = _safe_filename(workspace.company_name)
    excel_column, csv_column = st.columns(2)
    with excel_column:
        st.download_button(
            "Excel herunterladen",
            data=xlsx,
            file_name=f"{basename}_research_export.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="history_export_excel",
            on_click="ignore",
        )
    with csv_column:
        st.download_button(
            "CSV herunterladen",
            data=csv_data,
            file_name=f"{basename}_financial_history.csv",
            mime="text/csv",
            key="history_export_csv",
            on_click="ignore",
        )
