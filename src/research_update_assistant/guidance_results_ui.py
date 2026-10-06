"""Kompakte, neutrale Darstellung vorberechneter Guidance-Vergleiche."""

import streamlit as st

from .formatting import format_money, format_percentage
from .guidance_models import (
    ActualGuidanceComparison,
    GuidanceItem,
    GuidanceSnapshot,
    GuidanceSnapshotComparison,
    PERCENTAGE_GUIDANCE_METRICS,
)
from .guidance_ui import (
    guidance_direction_label, guidance_metric_label, guidance_source_label,
)


_STATUS_LABELS = {
    "within": "innerhalb Guidance",
    "above": "über Guidance",
    "below": "unter Guidance",
    "not_assessable": "nicht numerisch beurteilbar",
    "missing_actual": "Actual nicht verfügbar",
}
_CHANGE_LABELS = {
    "raised": "angehoben",
    "lowered": "gesenkt",
    "narrowed": "Range eingeengt",
    "widened": "Range ausgeweitet",
    "unchanged": "unverändert",
    "changed": "geändert",
}


def _format_value(value: float | None, metric: str, snapshot: GuidanceSnapshot) -> str:
    if value is None:
        return "–"
    if metric in PERCENTAGE_GUIDANCE_METRICS:
        return format_percentage(value)
    return format_money(value, snapshot.currency, snapshot.scale)


def format_guidance_item(item: GuidanceItem | None, snapshot: GuidanceSnapshot) -> str:
    """Formatiere die Aussage, ohne Range, Grenze oder Näherung zu verlieren."""
    if item is None:
        return "–"
    metric = item.canonical_metric
    if item.guidance_type == "exact":
        return _format_value(item.exact_value, metric, snapshot)
    if item.guidance_type == "approximate":
        return f"ca. {_format_value(item.exact_value, metric, snapshot)}"
    if item.guidance_type == "min":
        return f"≥ {_format_value(item.minimum, metric, snapshot)}"
    if item.guidance_type == "above":
        return f"> {_format_value(item.minimum, metric, snapshot)}"
    if item.guidance_type == "max":
        return f"≤ {_format_value(item.maximum, metric, snapshot)}"
    if item.guidance_type == "below":
        return f"< {_format_value(item.maximum, metric, snapshot)}"
    if item.guidance_type == "range":
        return (
            f"{_format_value(item.minimum, metric, snapshot)}–"
            f"{_format_value(item.maximum, metric, snapshot)}"
        )
    return guidance_direction_label(item.qualitative_direction)


def render_guidance_block(
    actual_comparison: ActualGuidanceComparison,
    history_comparison: GuidanceSnapshotComparison | None,
    *,
    key_prefix: str,
) -> None:
    """Zeige Actual-vs-Guidance und optional den eindeutig früheren Stand."""
    snapshot = actual_comparison.guidance_snapshot
    change_by_metric = (
        {} if history_comparison is None
        else {item.canonical_metric: item for item in history_comparison.item_changes}
    )
    rows = []
    for result in actual_comparison.item_comparisons:
        row = {
            "Kennzahl": guidance_metric_label(result.canonical_metric),
            "Guidance": format_guidance_item(result.guidance_item, snapshot),
            "Actual": _format_value(result.actual_value, result.canonical_metric, snapshot),
            "Status": _STATUS_LABELS[result.status],
        }
        if history_comparison is not None:
            change = change_by_metric.get(result.canonical_metric)
            row["Vorherige Guidance"] = format_guidance_item(
                None if change is None else change.previous_item,
                history_comparison.previous_snapshot,
            )
            row["Änderung"] = (
                "–" if change is None
                else " / ".join(_CHANGE_LABELS[item] for item in change.changes)
            )
        rows.append(row)

    st.subheader("Guidance")
    st.caption(
        f"{snapshot.label} · {guidance_source_label(snapshot.source_type)} · "
        f"Stand {snapshot.as_of_date.strftime('%d.%m.%Y')}"
    )
    st.dataframe(
        rows, hide_index=True, key=f"{key_prefix}guidance_table",
        alt="Unternehmens-Guidance, Actuals und mathematisch eindeutige Änderungen",
    )
    with st.expander("Guidance-Quelle"):
        st.text(f"Label / Anlass: {snapshot.label}")
        st.text(f"Quelle: {guidance_source_label(snapshot.source_type)}")
        st.text(f"Stand: {snapshot.as_of_date.isoformat()}")
        st.text(f"Dokument: {snapshot.source_document or '–'}")
        st.text(f"PDF-Seite: {snapshot.source_page or '–'}")
        st.text(f"Notizen: {snapshot.notes or '–'}")
