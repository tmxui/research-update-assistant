"""Kompakte Streamlit-Erfassung und Auswahl manueller Erwartungs-Snapshots."""

from collections.abc import Sequence
from datetime import date

import streamlit as st

from .expectation_models import ExpectationSnapshot
from .expectations import parse_expectation_values
from .history_workspace import PeriodKey, period_key_for
from .input_parsing import NumberParsingError, SCALE_OPTIONS
from .models import FinancialPeriod


_SOURCE_LABELS = {
    "consensus": "Consensus",
    "internal": "Eigene Schätzung",
    "other": "Sonstige Erwartung",
}
_INPUT_FIELDS = (
    ("revenue", "Umsatz"),
    ("ebitda", "EBITDA"),
    ("ebit", "EBIT"),
    ("ebit_margin", "EBIT-Marge in %"),
    ("net_income", "Nettoergebnis"),
    ("basic_eps", "Unverwässertes EPS"),
    ("diluted_eps", "Verwässertes EPS"),
    ("operating_cash_flow", "Geldfluss aus Geschäftstätigkeit"),
    ("reported_free_cash_flow", "Ausgewiesener Free Cashflow"),
    ("reported_net_debt", "Ausgewiesene Nettoverschuldung"),
    ("calculated_net_debt_to_ebitda", "Net Debt / EBITDA (berechnet, x)"),
)


def _period_token(period: FinancialPeriod) -> str:
    return "|".join((
        period.company_name,
        period.period_end.isoformat(),
        str(period.period_months),
        period.currency,
        period.scale,
    ))


def unique_periods(periods: Sequence[FinancialPeriod]) -> tuple[FinancialPeriod, ...]:
    """Entferne nur identische wirtschaftliche/UI-Ziele, nicht Quellenobservations."""
    by_token = {_period_token(period): period for period in periods}
    return tuple(sorted(by_token.values(), key=lambda item: (item.company_name, item.period_end, item.period_months)))


def render_expectation_entry(periods: Sequence[FinancialPeriod]) -> None:
    """Erfasse Snapshots für bereits bekannte Perioden in der Browser-Sitzung."""
    available = unique_periods(periods)
    st.markdown("### Erwartungen erfassen")
    if not available:
        st.caption("Sobald Finanzperioden analysiert wurden, können hier Erwartungen erfasst werden.")
        return

    by_token = {_period_token(period): period for period in available}
    tokens = tuple(by_token)
    with st.form("expectation_entry", enter_to_submit=False):
        target_token = st.selectbox(
            "Zielperiode",
            tokens,
            format_func=lambda token: (
                f"{by_token[token].company_name} · {by_token[token].period_label} · "
                f"{by_token[token].period_months} Monate · {by_token[token].currency} "
                f"{dict(SCALE_OPTIONS).get(by_token[token].scale, by_token[token].scale)}"
            ),
            key="expectation_target_period",
        )
        left, middle, right = st.columns(3)
        with left:
            label = st.text_input(
                "Bezeichnung", key="expectation_label", placeholder="z. B. Eigene Schätzung vor Publikation",
            )
        with middle:
            source_type = st.selectbox(
                "Erwartungstyp", tuple(_SOURCE_LABELS),
                format_func=lambda value: _SOURCE_LABELS[value], key="expectation_source_type",
            )
        with right:
            as_of_date = st.date_input(
                "Stand der Erwartung", value=date.today(), format="DD.MM.YYYY",
                key="expectation_as_of_date",
            )
        target = by_token[target_token]
        st.caption(
            f"Unternehmen und Einheit aus der Zielperiode: {target.company_name} · "
            f"{target.currency} · {dict(SCALE_OPTIONS).get(target.scale, target.scale)}"
        )
        raw_values: dict[str, str] = {}
        columns = st.columns(2)
        for index, (metric, label_de) in enumerate(_INPUT_FIELDS):
            with columns[index % 2]:
                raw_values[metric] = st.text_input(label_de, key=f"expectation_value_{metric}")
        notes = st.text_area("Notizen (optional)", key="expectation_notes")
        submitted = st.form_submit_button("Erwartung speichern", key="expectation_save")

    if submitted:
        try:
            if not label.strip():
                raise ValueError("Bitte eine Bezeichnung für den Erwartungs-Snapshot eingeben.")
            if type(as_of_date) is not date:
                raise ValueError("Bitte einen gültigen Stand der Erwartung wählen.")
            values = parse_expectation_values(raw_values)
            snapshot = ExpectationSnapshot(
                company=target.company_name,
                target_period=period_key_for(target),
                as_of_date=as_of_date,
                label=label.strip(),
                source_type=source_type,
                currency=target.currency,
                scale=target.scale,
                metric_expectations=values,
                notes=notes.strip() or None,
            )
            existing = tuple(st.session_state.get("expectation_snapshots", ()))
            st.session_state["expectation_snapshots"] = existing + (snapshot,)
            st.session_state["expectation_saved_message"] = (
                f"Erwartung ‚{snapshot.label}‘ für {target.period_label} gespeichert."
            )
            st.rerun()
        except (NumberParsingError, ValueError) as error:
            st.error(f"Erwartung konnte nicht gespeichert werden: {error}")

    message = st.session_state.pop("expectation_saved_message", None)
    if message:
        st.success(message)
    snapshots = tuple(st.session_state.get("expectation_snapshots", ()))
    if snapshots:
        st.dataframe(
            [
                {
                    "Bezeichnung": item.label,
                    "Zielperiode": str(item.target_period),
                    "Stand": item.as_of_date.isoformat(),
                    "Typ": _SOURCE_LABELS[item.source_type],
                    "Kennzahlen": sum(value is not None for _, value in item.metric_expectations),
                }
                for item in snapshots
            ],
            hide_index=True,
            alt="Gespeicherte Erwartungs-Snapshots dieser Sitzung",
        )


def select_expectation(
    actual: FinancialPeriod,
    *,
    key_prefix: str,
) -> ExpectationSnapshot | None:
    """Wähle höchstens einen passenden Snapshot; explizites Abwählen bleibt erhalten."""
    snapshots = tuple(st.session_state.get("expectation_snapshots", ()))
    eligible = tuple(
        item for item in snapshots
        if item.company.strip() == actual.company_name.strip()
        and item.target_period == period_key_for(actual)
    )
    if not eligible:
        return None

    selection_key = f"{key_prefix}expectation_snapshot"
    context_key = f"{selection_key}_context"
    context = (str(period_key_for(actual)), tuple(item.snapshot_id for item in eligible))
    options: tuple[str | None, ...] = (None,) + tuple(item.snapshot_id for item in eligible)
    if st.session_state.get(context_key) != context:
        st.session_state[context_key] = context
        st.session_state[selection_key] = eligible[0].snapshot_id if len(eligible) == 1 else None
    elif st.session_state.get(selection_key) not in options:
        st.session_state[selection_key] = None

    by_id = {item.snapshot_id: item for item in eligible}
    selected_id = st.selectbox(
        "Erwartung auswählen",
        options,
        format_func=lambda value: (
            "Keine Erwartung"
            if value is None
            else f"{by_id[value].label} · {_SOURCE_LABELS[by_id[value].source_type]} · "
                 f"Stand {by_id[value].as_of_date.strftime('%d.%m.%Y')}"
        ),
        key=selection_key,
    )
    return None if selected_id is None else by_id[selected_id]


def expectation_source_label(source_type: str) -> str:
    """Deutscher Anzeigename ohne Einfluss auf die Business-Logik."""
    return _SOURCE_LABELS.get(source_type, source_type)
