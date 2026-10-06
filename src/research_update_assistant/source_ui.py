"""Gemeinsame Anzeige des unveränderten Observation-Audit-Trails."""

from collections.abc import Sequence

import streamlit as st

from .validation import ConfirmedMetricObservation


def render_observation_audit(observations: Sequence[ConfirmedMetricObservation]) -> None:
    """Zeige Herkunft und Analystenkorrekturen für Einzelreport und Historie."""
    st.dataframe([
        {
            "Kennzahl": item.canonical_metric,
            "Periode": item.period_label,
            "Extrahiert": item.original_value,
            "Rohwert": item.original_raw_value,
            "Bestätigt": item.confirmed_value,
            "Prüfstatus": item.status,
            "Ursprüngliche Kennzahl": item.original_canonical_metric,
            "Ursprüngliche Periode": item.original_period_label,
            "Ursprüngliche Einheit": f"{item.original_currency or 'unbekannt'} / {item.original_scale or 'unbekannt'}",
            "Bestätigte Einheit": f"{item.currency} / {item.scale}",
            "Quelle": item.source_document or "Manuelle Ergänzung",
            "PDF-Seite": item.page_number,
            "Originalbezeichnung": item.reported_label,
            "Methode": item.extraction_method,
            "Quelltext": item.source_snippet,
            "Position": str(item.bbox) if item.bbox else None,
        } for item in observations
    ], hide_index=True, alt="Herkunft und Korrekturen der bestätigten Finanzwerte")
