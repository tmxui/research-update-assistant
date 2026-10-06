"""Kompaktes Ergebnis-Update aus bestätigten Daten, getrennt von Detailanalyse."""

from dataclasses import replace
from datetime import date
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from phase6_samples import make_confirmed_report, make_history_pdf, report_file_name
from research_update_assistant.history import FinancialHistory
from research_update_assistant.history_workspace import HistoryWorkspace, PeriodKey
from research_update_assistant.pdf_extractor import extract_pdf_document
from research_update_assistant.models import FinancialPeriod
from research_update_assistant.validation import ConfirmedMetricObservation


def _token(year: int) -> str:
    return str(PeriodKey(date(year, 12, 31), 12))


def _workspace(*, resolved: bool = True) -> HistoryWorkspace:
    workspace = HistoryWorkspace("Synthetic Industrial AG", "CHF", "million")
    for year in range(2022, 2026):
        history, observations = make_confirmed_report(year)
        workspace = workspace.add_report(history, observations, report_file_name(year))
    if resolved:
        key = PeriodKey(date(2024, 12, 31), 12)
        resolution = workspace.get_resolution(key, "ebit")
        selected = next(item for item in resolution.observations if item.value == 148)
        workspace = workspace.resolve(key, "ebit", selected.observation_id, "Synthetischer Vergleichswert geprüft")
    return workspace


def _history_app(*, years=(2021, 2022, 2023, 2024, 2025), resolved=True, source_documents=False):
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
    app.session_state["history_workspace"] = _workspace(resolved=resolved)
    app.session_state["history_trend_periods"] = [_token(year) for year in years]
    app.session_state["history_previous_period"] = _token(2024)
    app.session_state["history_current_period"] = _token(2025)
    app.session_state["history_analysis_active"] = True
    if source_documents:
        app.session_state["history_documents"] = {
            report_file_name(year): extract_pdf_document(make_history_pdf(year), file_name=report_file_name(year))
            for year in range(2022, 2026)
        }
    app.run()
    assert not app.exception
    return app


def _view(app, prefix="history_", label="Ergebnis-Update"):
    group = app.get_by_key(prefix + "analysis_views")
    return next(tab for tab in group.tabs if tab.label == label)


def _card(app, metric, prefix="history_"):
    return app.get_by_key(f"{prefix}update_metric_{metric}").metric[0]


def _chart(app, name, prefix="history_"):
    return json.loads(app.get_by_key(f"{prefix}update_chart_{name}").proto.spec)


def _sources(app, prefix="history_"):
    return next(expander for expander in _view(app, prefix).expander if expander.label == "Quellen")


def test_update_has_compact_blocks_neutral_cards_and_preserved_details():
    app = _history_app()
    update = _view(app)
    assert any(item.value == "FY2025 Ergebnis-Update" for item in update.subheader)
    assert any("FY2024" in item.value for item in update.caption)
    assert "Wichtigste Veränderungen" in [item.value for item in update.subheader]
    assert "Research-Prüfpunkte" in [item.value for item in update.subheader]
    assert "Historischer Kontext" in [item.value for item in update.subheader]
    assert len(update.metric) <= 7
    assert len(update.get("plotly_chart")) <= 3
    assert len(app.get_by_key("history_update_changes").text) <= 7
    assert _sources(app).label == "Quellen"
    for card in update.metric:
        assert card.proto.color == card.proto.GRAY
        assert card.proto.direction == card.proto.NONE
    detail = _view(app, label="Detailanalyse")
    assert "Finanzübersicht" in [item.value for item in detail.header]
    assert "Periodenvergleich" in [item.value for item in detail.header]
    assert len(detail.get("plotly_chart")) == 7
    assert len(detail.table) == 2
    assert "1'100" in _card(app, "revenue").value
    assert "+10.0 %" in _card(app, "revenue").delta
    assert "13.0 %" in _card(app, "ebit_margin").value
    assert "-180" in _card(app, "ebit_margin").delta


@pytest.mark.parametrize("years", [(2024, 2025), (2023, 2024, 2025), (2021, 2022, 2023, 2024, 2025)])
def test_compact_trend_has_two_three_or_five_periods_but_one_comparison(years):
    app = _history_app(years=years)
    assert _chart(app, "revenue")["data"][0]["x"] == [f"FY{year}" for year in years]
    result = app.session_state["history_result"]
    assert len(result.comparisons) == len(result.research_flags) == 1
    assert result.comparisons[0].current_period.period_label == "FY2025"
    assert result.comparisons[0].previous_period.period_label == "FY2024"
    assert any(item.value == "FY2025 Ergebnis-Update" for item in _view(app).subheader)


def test_older_comparison_drives_headline_cards_flags_and_sources_not_latest_trend():
    app = _history_app()
    app.selectbox(key="history_previous_period").select(_token(2023)).run()
    app.selectbox(key="history_current_period").select(_token(2024)).run()
    update = _view(app)
    assert any(item.value == "FY2024 Ergebnis-Update" for item in update.subheader)
    assert not any(item.value == "FY2025 Ergebnis-Update" for item in update.subheader)
    assert "1'000" in _card(app, "revenue").value
    assert "+8.7 %" in _card(app, "revenue").delta
    assert _chart(app, "revenue")["data"][0]["x"][-1] == "FY2025"
    assert app.session_state["history_result"].comparisons[0].current_period.period_label == "FY2024"
    active_text = "\n".join(item.value for item in _sources(app).text)
    assert "FY2024" in active_text and "FY2023" in active_text
    assert "FY2025" not in active_text
    assert not app.exception


def test_comparison_selection_replaces_old_flags_without_stale_session_values():
    app = _history_app()
    old_flags = {flag.rule_id for flag in app.session_state["history_result"].research_flags[0]}
    app.selectbox(key="history_previous_period").select(_token(2023)).run()
    app.selectbox(key="history_current_period").select(_token(2024)).run()
    new_flags = {flag.rule_id for flag in app.session_state["history_result"].research_flags[0]}
    assert old_flags != new_flags
    flag_containers = [node for node in _view(app).get("flex_container")
                       if node.key and node.key.startswith("history_update_flag_")]
    displayed_ids = {node.key.split("_", 4)[-1] for node in flag_containers}
    assert displayed_ids == new_flags
    assert displayed_ids <= new_flags
    assert not displayed_ids.intersection(old_flags - new_flags)
    assert not app.exception


def test_unresolved_base_margin_remains_missing_and_conflict_is_visible():
    app = _history_app(resolved=False)
    update = _view(app)
    assert "13.0 %" in _card(app, "ebit_margin").value
    assert _card(app, "ebit_margin").delta == ""
    conflict_text = "\n".join(item.value for item in update.warning)
    assert "Historischer Wert ungeklärt" in conflict_text
    assert "FY2024" in conflict_text and "EBIT" in conflict_text
    assert app.session_state["history_result"].comparisons[0].previous_metrics.ebit_margin is None
    assert not app.exception


def test_unresolved_current_margin_is_not_replaced_by_later_trend_value():
    app = _history_app(resolved=False)
    app.selectbox(key="history_previous_period").select(_token(2023)).run()
    app.selectbox(key="history_current_period").select(_token(2024)).run()
    update = _view(app)
    assert "EBIT-Marge" not in [card.label for card in update.metric]
    assert any(item.value == "FY2024 Ergebnis-Update" for item in update.subheader)
    assert any("Historischer Wert ungeklärt" in item.value and "FY2024" in item.value for item in update.warning)
    assert _chart(app, "revenue")["data"][0]["x"][-1] == "FY2025"
    assert not app.exception


def test_sources_keep_selected_and_equivalent_reports_and_derived_input_provenance():
    app = _history_app(source_documents=True)
    sources = _sources(app)
    text = "\n".join(item.value for item in sources.text)
    captions = "\n".join(item.value for item in sources.caption)
    assert report_file_name(2025) in text and report_file_name(2024) in text
    assert "Originalbezeichnung: Nettoumsatz" in text
    assert "PDF-Seite 1" in text
    assert "Betriebsergebnis (EBIT)" in text
    assert "Geldfluss aus Geschäftstätigkeit" in text
    assert "Investitionen in Sachanlagen" in text
    assert "Berechnet aus bestätigten Eingangsgrössen" in captions
    assert "Durch mehrere Quellen bestätigt" in captions
    # Eine echte dokumentbezogene Referenz öffnet den archivierten Bericht.
    source_button = next(button for button in sources.button if report_file_name(2025) in button.label)
    source_button.click().run()
    assert app.session_state["history_source_view"] == report_file_name(2025)
    assert app.session_state["history_documents"][report_file_name(2025)].file_name == report_file_name(2025)
    assert not app.exception


def test_confirmed_pdf_reported_fcf_preference_and_existing_calculated_details():
    history, observations = make_confirmed_report(2025)
    adjusted = []
    for observation in observations:
        corrected = observation.canonical_metric == "operating_cash_flow" and observation.period_label == "FY2025"
        adjusted.append(replace(observation, confirmed_value=782, status="changed") if corrected else observation)
    adjusted.extend(ConfirmedMetricObservation(
        "reported_free_cash_flow", label, value, "CHF", "million", "confirmed",
        original_extracted_value=value, original_raw_value=str(value),
        original_canonical_metric="reported_free_cash_flow", original_period_label=label,
        original_currency="CHF", original_scale="million", source_document=report_file_name(2025),
        page_number=3, reported_label="Free Cashflow", source_snippet=f"Free Cashflow {value}",
        extraction_method="pymupdf_layout",
    ) for label, value in (("FY2025", 658.6), ("FY2024", 95)))
    periods = tuple(replace(period,
        operating_cash_flow=782 if period.period_label == "FY2025" else period.operating_cash_flow,
        reported_free_cash_flow=658.6 if period.period_label == "FY2025" else 95,
    ) for period in history.periods)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
    app.session_state["pdf_ready_history"] = FinancialHistory(periods)
    app.session_state["pdf_ready_observations"] = tuple(adjusted)
    app.run()
    app.button(key="pdf_start_analysis").click().run()
    assert not app.exception and not app.error
    update = _view(app, "pdf_")
    labels = [card.label for card in update.metric]
    assert "Ausgewiesener FCF" in labels and "Berechneter FCF" not in labels
    fcf = next(card for card in update.metric if card.label == "Ausgewiesener FCF")
    assert "658.6" in fcf.value and "702" not in fcf.value
    assert app.session_state["pdf_analysis_result"].metrics[-1].calculated_free_cash_flow == 702
    detail = _view(app, "pdf_", "Detailanalyse")
    assert len(detail.get("plotly_chart")) == 7
    assert app.text_input(key="company_name").value == ""
    assert any(item.value == "FY2025 Ergebnis-Update" for item in update.subheader)


def test_calculated_fcf_is_explicit_when_reported_is_missing_and_manual_remains_separate():
    app = _history_app()
    assert "Berechneter FCF" in [card.label for card in _view(app).metric]
    assert "Ausgewiesener FCF" not in [card.label for card in _view(app).metric]
    before_workspace = app.session_state["history_workspace"]
    app.button(key="load_examples").click().run()
    app.button(key="calculate_analysis").click().run()
    assert app.session_state["manual_analysis_result"].metrics[-1].calculated_free_cash_flow == 60
    assert app.session_state["history_workspace"] is before_workspace
    assert any(item.value == "FY2025 Ergebnis-Update" for item in _view(app).subheader)
    assert not app.exception and not app.error


def test_partial_confirmed_pdf_has_ebit_fallback_and_no_invented_cash_or_debt_cards():
    complete, observations = make_confirmed_report(2025)
    partial = FinancialHistory(tuple(FinancialPeriod(
        company_name=period.company_name, period_label=period.period_label,
        period_end=period.period_end, period_months=period.period_months,
        currency=period.currency, scale=period.scale, revenue=period.revenue, ebit=period.ebit,
    ) for period in complete.periods))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
    app.session_state["pdf_ready_history"] = partial
    app.session_state["pdf_ready_observations"] = tuple(item for item in observations if item.canonical_metric in ("revenue", "ebit"))
    app.run()
    app.button(key="pdf_start_analysis").click().run()
    update = _view(app, "pdf_")
    assert [card.label for card in update.metric] == ["Umsatz", "EBIT", "EBIT-Marge"]
    assert len(update.get("plotly_chart")) <= 3
    assert app.session_state["pdf_analysis_result"].metrics[-1].calculated_free_cash_flow is None
    assert not app.exception and not app.error


def test_zero_deltas_keep_units_and_neutral_direction():
    """Unveränderte Beträge, Margen und Leverage behalten ihre Delta-Einheit."""
    def script():
        from dataclasses import replace
        from datetime import date
        from research_update_assistant.sample_data import load_synthetic_history
        from research_update_assistant.history import FinancialHistory
        from research_update_assistant.calculations import calculate_period_metrics, compare_periods
        from research_update_assistant.results_update import build_results_update
        from research_update_assistant.results_update_ui import render_results_update
        previous = load_synthetic_history().get_period('FY2024')
        current = replace(previous, period_label='FY2025', period_end=date(2025, 12, 31))
        history = FinancialHistory((previous, current))
        snapshot = build_results_update(history, tuple(calculate_period_metrics(p) for p in history.periods),
                                        compare_periods(current, previous), ())
        render_results_update(snapshot, key_prefix='zero_')
    app = AppTest.from_function(script, default_timeout=20).run()
    assert not app.exception
    for label, unit in (('Umsatz', '%'), ('EBIT-Marge', 'bps'), ('Net Debt / EBITDA (berechnet)', 'x')):
        card = next(item for item in app.metric if item.label == label)
        assert card.delta == '0'
        assert card.proto.delta_description == f'{unit} · ggü. FY2024'
        assert card.proto.color == card.proto.GRAY
        assert card.proto.direction == card.proto.NONE


def test_reported_only_debt_keeps_amount_card_without_leverage_card():
    """Keine 0.83x-Karte aus 769 ausgewiesener Nettoverschuldung und 930.6 EBITDA."""
    def script():
        from dataclasses import replace
        from research_update_assistant.sample_data import load_synthetic_history
        from research_update_assistant.history import FinancialHistory
        from research_update_assistant.calculations import calculate_period_metrics, compare_periods
        from research_update_assistant.results_update import build_results_update
        from research_update_assistant.results_update_ui import render_results_update
        previous, current = load_synthetic_history().periods[-2:]
        previous = replace(previous, reported_net_debt=965.4, ebitda=912.6, gross_debt=None)
        current = replace(current, reported_net_debt=769, ebitda=930.6, gross_debt=None)
        history = FinancialHistory((previous, current))
        comparison = compare_periods(current, previous)
        snapshot = build_results_update(history, tuple(calculate_period_metrics(p) for p in history.periods),
                                        comparison, ())
        render_results_update(snapshot, key_prefix='reported_only_')
    app = AppTest.from_function(script, default_timeout=20).run()
    assert not app.exception
    debt = next(card for card in app.metric if card.label == 'Ausgewiesene Nettoverschuldung')
    assert debt.value == 'CHF 769 Mio.'
    assert not any('EBITDA' in card.label and 'Net Debt' in card.label for card in app.metric)
    assert not any(card.value == '0.83x' for card in app.metric)
