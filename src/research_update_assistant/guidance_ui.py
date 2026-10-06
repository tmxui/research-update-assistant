"""Manuelle Streamlit-Erfassung und Auswahl von Guidance-Snapshots."""

from collections.abc import Sequence
from datetime import date

import streamlit as st

from .guidance import guidance_items_from_form
from .guidance_models import GuidanceSnapshot, SUPPORTED_GUIDANCE_METRICS
from .history_workspace import period_key_for
from .input_parsing import NumberParsingError, SCALE_OPTIONS
from .models import FinancialPeriod


_SOURCE_LABELS = {
    "annual_report": "Geschäftsbericht",
    "half_year_report": "Halbjahresbericht",
    "results_presentation": "Ergebnispräsentation",
    "other": "Andere Unternehmensquelle",
}
_TYPE_LABELS = {
    "none": "Keine Guidance",
    "exact": "Exakter Wert",
    "min": "Mindestens (≥)",
    "above": "Über (>)",
    "max": "Höchstens (≤)",
    "below": "Unter (<)",
    "range": "Range",
    "approximate": "Ungefährer Wert",
    "qualitative": "Qualitative Richtung",
}
_DIRECTION_LABELS = {
    "increase": "Steigend",
    "decrease": "Sinkend",
    "stable": "Stabil",
    "around": "In etwa / ungefähr",
}
_METRIC_LABELS = {
    "revenue_growth": "Umsatzwachstum",
    "ebitda_margin": "EBITDA-Marge",
    "ebit_margin": "EBIT-Marge",
    "revenue": "Umsatz",
    "ebitda": "EBITDA",
    "ebit": "EBIT",
    "reported_free_cash_flow": "Ausgewiesener Free Cashflow",
    "reported_net_debt": "Ausgewiesene Nettoverschuldung",
}
_PERCENTAGE_METRICS = {"revenue_growth", "ebitda_margin", "ebit_margin"}


def _period_token(period: FinancialPeriod) -> str:
    return "|".join((
        period.company_name, period.period_end.isoformat(), str(period.period_months),
        period.currency, period.scale,
    ))


def _unique_periods(periods: Sequence[FinancialPeriod]) -> tuple[FinancialPeriod, ...]:
    by_token = {_period_token(period): period for period in periods}
    return tuple(sorted(
        by_token.values(), key=lambda item: (item.company_name, item.period_end, item.period_months),
    ))


def _render_item(metric: str) -> tuple[str, str, str, str, str | None]:
    unit = "%" if metric in _PERCENTAGE_METRICS else "Betrag in der gewählten Einheit"
    with st.expander(f"{_METRIC_LABELS[metric]} (optional)"):
        guidance_type = st.selectbox(
            "Guidance-Form", tuple(_TYPE_LABELS),
            format_func=lambda value: _TYPE_LABELS[value], key=f"guidance_type_{metric}",
        )
        st.caption(
            f"Numerische Eingabe: {unit}. Verwende Wert für exakt/ungefähr und die Grenzen für eine Range."
        )
        first, second, third = st.columns(3)
        with first:
            raw_value = st.text_input(
                "Wert", key=f"guidance_value_{metric}",
                placeholder="z. B. 5 oder 650",
            )
        with second:
            raw_minimum = st.text_input(
                "Untergrenze", key=f"guidance_minimum_{metric}", placeholder="z. B. 4",
            )
        with third:
            raw_maximum = st.text_input(
                "Obergrenze", key=f"guidance_maximum_{metric}", placeholder="z. B. 6",
            )
        direction = st.selectbox(
            "Qualitative Richtung", tuple(_DIRECTION_LABELS), index=None,
            format_func=lambda value: _DIRECTION_LABELS[value],
            key=f"guidance_direction_{metric}",
            placeholder="Nur für qualitative Guidance auswählen",
        )
    return guidance_type, raw_value, raw_minimum, raw_maximum, direction


def render_guidance_entry(periods: Sequence[FinancialPeriod]) -> None:
    """Erfasse manuelle Guidance für eine bereits bekannte wirtschaftliche Periode."""
    available = _unique_periods(periods)
    st.markdown("### Guidance erfassen")
    if not available:
        st.caption("Sobald Finanzperioden analysiert wurden, kann hier Guidance erfasst werden.")
        return

    by_token = {_period_token(period): period for period in available}
    tokens = tuple(by_token)
    with st.form("guidance_entry", enter_to_submit=False):
        target_token = st.selectbox(
            "Guidance-Zielperiode", tokens,
            format_func=lambda token: (
                f"{by_token[token].company_name} · {by_token[token].period_label} · "
                f"{by_token[token].period_months} Monate · {by_token[token].currency} "
                f"{dict(SCALE_OPTIONS).get(by_token[token].scale, by_token[token].scale)}"
            ),
            key="guidance_target_period",
        )
        left, middle, right = st.columns(3)
        with left:
            label = st.text_input(
                "Label / Anlass", key="guidance_label", placeholder="z. B. FY2025 Guidance bei H1 2025",
            )
        with middle:
            source_type = st.selectbox(
                "Guidance-Quelle", tuple(_SOURCE_LABELS),
                format_func=lambda value: _SOURCE_LABELS[value], key="guidance_source_type",
            )
        with right:
            as_of_date = st.date_input(
                "Stand der Guidance", value=date.today(), format="DD.MM.YYYY",
                key="guidance_as_of_date",
            )
        target = by_token[target_token]
        st.caption(
            f"Unternehmen und Einheit aus der Zielperiode: {target.company_name} · "
            f"{target.currency} · {dict(SCALE_OPTIONS).get(target.scale, target.scale)}"
        )
        source_left, source_right = st.columns(2)
        with source_left:
            source_document = st.text_input(
                "Quelldokument (optional)", key="guidance_source_document",
                placeholder="z. B. results_presentation_2025.pdf",
            )
        with source_right:
            source_page = st.number_input(
                "PDF-Seite (optional)", min_value=1, step=1, value=None,
                key="guidance_source_page",
            )
        st.markdown("**Guidance Items**")
        st.caption("Nur ausgefüllte Aussagen werden gespeichert. Ranges und Grenzwerte bleiben unverändert erhalten.")
        forms = {metric: _render_item(metric) for metric in SUPPORTED_GUIDANCE_METRICS}
        notes = st.text_area("Guidance-Notizen (optional)", key="guidance_notes")
        submitted = st.form_submit_button("Guidance speichern", key="guidance_save")

    if submitted:
        try:
            if not label.strip():
                raise ValueError("Bitte ein Label oder einen Anlass für die Guidance eingeben.")
            if type(as_of_date) is not date:
                raise ValueError("Bitte einen gültigen Stand der Guidance wählen.")
            items = guidance_items_from_form(forms)
            if not items:
                raise ValueError("Bitte mindestens ein Guidance Item erfassen.")
            snapshot = GuidanceSnapshot(
                company=target.company_name,
                target_period=period_key_for(target),
                as_of_date=as_of_date,
                label=label.strip(),
                source_type=source_type,
                currency=target.currency,
                scale=target.scale,
                guidance_items=items,
                source_document=source_document.strip() or None,
                source_page=source_page,
                notes=notes.strip() or None,
            )
            existing = tuple(st.session_state.get("guidance_snapshots", ()))
            st.session_state["guidance_snapshots"] = existing + (snapshot,)
            st.session_state["guidance_saved_message"] = (
                f"Guidance ‚{snapshot.label}‘ für {target.period_label} gespeichert."
            )
            st.rerun()
        except (NumberParsingError, ValueError) as error:
            st.error(f"Guidance konnte nicht gespeichert werden: {error}")

    message = st.session_state.pop("guidance_saved_message", None)
    if message:
        st.success(message)
    snapshots = tuple(st.session_state.get("guidance_snapshots", ()))
    if snapshots:
        st.dataframe(
            [
                {
                    "Label": item.label,
                    "Zielperiode": str(item.target_period),
                    "Stand": item.as_of_date.isoformat(),
                    "Quelle": _SOURCE_LABELS[item.source_type],
                    "Items": len(item.guidance_items),
                }
                for item in sorted(snapshots, key=lambda value: (value.as_of_date, value.snapshot_id))
            ],
            hide_index=True,
            alt="Gespeicherte Guidance-Snapshots dieser Sitzung",
        )


def select_guidance(
    actual: FinancialPeriod,
    *,
    key_prefix: str,
) -> tuple[GuidanceSnapshot | None, GuidanceSnapshot | None]:
    """Wähle einen aktiven Snapshot und ermittle den eindeutig früheren Stand."""
    snapshots = tuple(st.session_state.get("guidance_snapshots", ()))
    eligible = tuple(sorted(
        (
            item for item in snapshots
            if item.company.strip() == actual.company_name.strip()
            and item.target_period == period_key_for(actual)
        ),
        key=lambda item: (item.as_of_date, item.snapshot_id),
    ))
    if not eligible:
        return None, None

    selection_key = f"{key_prefix}guidance_snapshot"
    context_key = f"{selection_key}_context"
    context = (str(period_key_for(actual)), tuple(item.snapshot_id for item in eligible))
    options: tuple[str | None, ...] = (None,) + tuple(item.snapshot_id for item in eligible)
    if st.session_state.get(context_key) != context:
        st.session_state[context_key] = context
        st.session_state[selection_key] = eligible[-1].snapshot_id
    elif st.session_state.get(selection_key) not in options:
        st.session_state[selection_key] = None

    by_id = {item.snapshot_id: item for item in eligible}
    selected_id = st.selectbox(
        "Guidance auswählen", options,
        format_func=lambda value: (
            "Keine Guidance"
            if value is None
            else f"{by_id[value].label} · Stand {by_id[value].as_of_date.strftime('%d.%m.%Y')}"
        ),
        key=selection_key,
    )
    if selected_id is None:
        return None, None
    selected = by_id[selected_id]
    previous = next(
        (item for item in reversed(eligible) if item.as_of_date < selected.as_of_date),
        None,
    )
    return selected, previous


def guidance_source_label(source_type: str) -> str:
    return _SOURCE_LABELS.get(source_type, source_type)


def guidance_metric_label(canonical_metric: str) -> str:
    return _METRIC_LABELS.get(canonical_metric, canonical_metric)


def guidance_direction_label(direction: str | None) -> str:
    return "–" if direction is None else _DIRECTION_LABELS.get(direction, direction)
