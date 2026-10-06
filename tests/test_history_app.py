"""Mehrere bestätigte Reports, Quellenentscheidung und unabhängige Analysefenster."""

from datetime import date
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from phase6_samples import make_confirmed_report, make_history_pdf, report_file_name
from research_update_assistant import ui
from research_update_assistant.history_workspace import PeriodKey


def _app() -> AppTest:
    return AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()


def _seed_report(app: AppTest, year: int, **kwargs) -> None:
    history, observations = make_confirmed_report(year, **kwargs)
    app.session_state["pdf_ready_history"] = history
    app.session_state["pdf_ready_observations"] = observations
    app.run()
    assert not app.exception


def _add_report(app: AppTest, year: int, **kwargs) -> None:
    _seed_report(app, year, **kwargs)
    app.checkbox(key="history_company_confirm").check().run()
    app.button(key="history_add_report").click().run()
    assert not app.exception


def _key(year: int) -> PeriodKey:
    return PeriodKey(date(year, 12, 31), 12)


def _resolve_ebit_2024(app: AppTest, value: float = 148) -> None:
    workspace = app.session_state["history_workspace"]
    resolution = workspace.get_resolution(_key(2024), "ebit")
    chosen = next(item for item in resolution.observations if item.value == value)
    app.selectbox(key=f"history_resolution_{_key(2024)}_ebit").select(chosen.observation_id).run()
    app.text_input(key=f"history_reason_{_key(2024)}_ebit").set_value("Späterer Vergleichswert geprüft").run()
    app.button(key=f"history_apply_resolution_{_key(2024)}_ebit").click().run()
    assert not app.exception and not app.error


def _chart(app: AppTest, name: str) -> dict:
    return json.loads(app.get_by_key(f"history_chart_{name}").proto.spec)


def test_report_addition_requires_explicit_company_confirmation():
    app = _app()
    _seed_report(app, 2025)
    assert app.session_state["history_workspace"] is None
    app.button(key="history_add_report").click().run()
    assert app.session_state["history_workspace"] is None
    assert any("Zugehörigkeit" in error.value for error in app.error)
    app.checkbox(key="history_company_confirm").check().run()
    app.button(key="history_add_report").click().run()
    workspace = app.session_state["history_workspace"]
    assert [period.period_label for period in workspace.periods] == ["FY2024", "FY2025"]
    assert len(workspace.reports) == 1
    assert app.session_state["history_result"] is None
    assert app.text_input(key="company_name").value == ""


def test_overlapping_reports_preserve_equivalent_sources_and_unresolved_values():
    app = _app()
    _add_report(app, 2025)
    _add_report(app, 2024)
    workspace = app.session_state["history_workspace"]
    assert [period.period_label for period in workspace.periods] == ["FY2023", "FY2024", "FY2025"]
    assert len(workspace.reports) == 2
    revenue = workspace.get_resolution(_key(2024), "revenue")
    assert revenue.status == "equivalent" and revenue.resolved_value == 1000
    assert len(revenue.observations) == 2
    assert {item.source_document for item in revenue.observations} == {report_file_name(2024), report_file_name(2025)}
    ebit = workspace.get_resolution(_key(2024), "ebit")
    assert ebit.status == "unresolved" and ebit.resolved_value is None
    assert {item.value for item in ebit.observations} == {148, 150}
    assert workspace.to_financial_history().get_period("FY2024").ebit is None
    assert any("Offene Konflikte: 1" in item.value for item in app.text)
    assert any("FY2024" in item.value and "EBIT" in item.value for item in app.warning)
    assert app.selectbox(key=f"history_resolution_{_key(2024)}_ebit").value is None
    assert not app.exception


def test_conflict_resolution_is_explicit_keeps_alternatives_and_updates_analysis():
    app = _app()
    _add_report(app, 2025)
    _add_report(app, 2024)
    app.button(key="history_analyse").click().run()
    unresolved_result = app.session_state["history_result"]
    assert unresolved_result.history.get_period("FY2024").ebit is None
    assert unresolved_result.comparisons[0].previous_metrics.ebit_margin is None
    _resolve_ebit_2024(app)
    workspace = app.session_state["history_workspace"]
    ebit = workspace.get_resolution(_key(2024), "ebit")
    assert ebit.status == "resolved" and ebit.resolved_value == 148
    assert {item.value for item in ebit.observations} == {148, 150}
    assert ebit.reason == "Späterer Vergleichswert geprüft"
    result = app.session_state["history_result"]
    assert result.history.get_period("FY2024").ebit == 148
    assert result.comparisons[0].ebit_margin_change == pytest.approx(0.13 - 0.148)
    assert workspace.events
    assert not app.exception


def test_three_five_and_two_period_trends_keep_one_independent_comparison(monkeypatch):
    flags = Mock(wraps=ui.generate_research_flags)
    # The history adapter loads its own reference to the same existing engine.
    from research_update_assistant import analysis_selection
    monkeypatch.setattr(analysis_selection, "generate_research_flags", flags)
    app = _app()
    _add_report(app, 2025)
    _add_report(app, 2024)
    _resolve_ebit_2024(app)
    assert app.multiselect(key="history_trend_periods").value == [str(_key(2024)), str(_key(2025))]
    app.multiselect(key="history_trend_periods").set_value([str(_key(year)) for year in (2023, 2024, 2025)]).run()
    app.button(key="history_analyse").click().run()
    result = app.session_state["history_result"]
    assert len(result.history.periods) == 3
    assert len(result.comparisons) == len(result.research_flags) == 1
    assert result.comparisons[0].current_period.period_label == "FY2025"
    assert result.comparisons[0].previous_period.period_label == "FY2024"
    assert len(_chart(app, "revenue")["data"][0]["x"]) == 3
    _add_report(app, 2023)
    _add_report(app, 2022)
    workspace = app.session_state["history_workspace"]
    assert [period.period_label for period in workspace.periods] == [f"FY{year}" for year in range(2021, 2026)]
    assert len(app.multiselect(key="history_trend_periods").options) == 5
    flags.reset_mock()
    app.multiselect(key="history_trend_periods").set_value([str(_key(year)) for year in range(2021, 2026)]).run()
    result = app.session_state["history_result"]
    assert len(result.history.periods) == 5
    assert len(result.comparisons) == len(result.research_flags) == 1
    assert flags.call_count == 1
    comparison = flags.call_args.args[0]
    assert comparison.current_period.period_label == "FY2025" and comparison.previous_period.period_label == "FY2024"
    assert _chart(app, "revenue")["data"][0]["x"] == [f"FY{year}" for year in range(2021, 2026)]
    app.multiselect(key="history_trend_periods").set_value([str(_key(2024)), str(_key(2025))]).run()
    assert len(app.session_state["history_result"].history.periods) == 2
    assert len(_chart(app, "revenue")["data"][0]["x"]) == 2
    assert len(app.session_state["history_workspace"].periods) == 5
    assert not app.exception


def test_missing_cashflow_is_a_chart_gap_not_zero_or_interpolation():
    app = _app()
    for year in (2025, 2024, 2023, 2022):
        _add_report(app, year)
    _resolve_ebit_2024(app)
    app.multiselect(key="history_trend_periods").set_value([str(_key(year)) for year in range(2021, 2026)]).run()
    app.button(key="history_analyse").click().run()
    result = app.session_state["history_result"]
    assert result.history.get_period("FY2022").operating_cash_flow is None
    assert result.metrics[1].calculated_free_cash_flow is None
    cashflow = _chart(app, "cashflow")
    fcf = next(trace for trace in cashflow["data"] if trace["name"] == "Berechneter Free Cashflow")
    assert fcf["y"] == [100, None, 110, 100, 60]
    assert fcf["type"] == "bar"  # Fehlender Balken, keine interpolierende Linie.
    assert not app.exception


@pytest.mark.parametrize("kwargs", [
    {"company_name": "Other Industrial AG"}, {"currency": "EUR"}, {"scale": "thousand"},
])
def test_report_identity_or_units_mismatch_do_not_modify_workspace(kwargs):
    app = _app()
    _add_report(app, 2025)
    previous = app.session_state["history_workspace"]
    _seed_report(app, 2024, **kwargs)
    app.checkbox(key="history_company_confirm").check().run()
    app.button(key="history_add_report").click().run()
    assert app.error and not app.exception
    assert app.session_state["history_workspace"] is previous
    assert len(previous.reports) == 1


def test_readding_same_report_is_idempotent():
    app = _app()
    _add_report(app, 2025)
    workspace = app.session_state["history_workspace"]
    app.button(key="history_add_report").click().run()
    assert app.session_state["history_workspace"] is workspace
    assert len(workspace.reports) == 1
    assert len(workspace.observations) == 22
    assert not app.exception


def test_new_pdf_and_next_report_preserve_workspace_and_manual_drafts():
    app = _app()
    _add_report(app, 2025)
    workspace = app.session_state["history_workspace"]
    # Formulare senden Entwürfe erst mit Submit; simuliere hier bereits
    # gespeicherten Widget-State, ohne eine manuelle Analyse auszulösen.
    app.session_state["company_name"] = "Manual Draft AG"
    app.session_state["period_0_revenue"] = "123"
    app.run()
    app.file_uploader(key="pdf_upload").set_value((report_file_name(2024), make_history_pdf(2024), "application/pdf")).run()
    assert app.session_state["history_workspace"] is workspace
    assert app.text_input(key="company_name").value == "Manual Draft AG"
    assert app.text_input(key="period_0_revenue").value == "123"
    # The newly uploaded report must still be validated; it is never added by upload.
    assert len(workspace.reports) == 1
    _seed_report(app, 2024)
    app.checkbox(key="history_company_confirm").check().run()
    app.button(key="history_add_report").click().run()
    updated = app.session_state["history_workspace"]
    app.button(key="history_next_report").click().run()
    assert app.session_state["history_workspace"] is updated
    assert app.session_state["pdf_ready_history"] is None
    if "review_records" in app.session_state:
        assert not app.session_state["review_records"]
    assert app.text_input(key="company_name").value == "Manual Draft AG"
    assert app.text_input(key="period_0_revenue").value == "123"
    assert not app.exception


def test_history_reset_requires_deliberate_confirmation_and_keeps_ready_pdf():
    app = _app()
    _add_report(app, 2025)
    ready = app.session_state["pdf_ready_history"]
    assert app.button(key="history_reset").disabled
    app.checkbox(key="history_reset_confirm").check().run()
    app.button(key="history_reset").click().run()
    assert app.session_state["history_workspace"] is None
    assert app.session_state["history_result"] is None
    assert app.session_state["pdf_ready_history"] is ready
    assert not app.exception


def test_manual_and_single_report_analysis_remain_independent_of_history():
    app = _app()
    _add_report(app, 2025)
    workspace = app.session_state["history_workspace"]
    app.button(key="pdf_start_analysis").click().run()
    pdf_result = app.session_state["pdf_analysis_result"]
    assert pdf_result.history.get_period("FY2024").ebit == 148
    app.button(key="load_examples").click().run()
    app.button(key="calculate_analysis").click().run()
    assert app.session_state["manual_analysis_result"].history.get_period("FY2024").ebit == 150
    assert app.session_state["pdf_analysis_result"] is pdf_result
    assert app.session_state["history_workspace"] is workspace
    assert not app.exception and not app.error


def test_actual_pdf_uploads_keep_report_sources_openable_after_replacement():
    """Vollständiger PDF-Weg statt vorbestätigter Seeds; alte Quelle bleibt lesbar."""
    app = _app()
    for year in (2025, 2024):
        app.file_uploader(key="pdf_upload").set_value((report_file_name(year), make_history_pdf(year), "application/pdf")).run()
        app.text_input(key="review_company").set_value("Synthetic Industrial AG").run()
        for metric in ("revenue", "ebit"):
            app.selectbox(key="review_metric").select(metric).run()
            app.button(key="review_confirm_metric").click().run()
        app.checkbox(key="review_metadata_confirmed").check().run()
        app.button(key="review_accept").click().run()
        app.checkbox(key="history_company_confirm").check().run()
        app.button(key="history_add_report").click().run()
        assert not app.exception and not app.error
    workspace = app.session_state["history_workspace"]
    assert [period.period_label for period in workspace.periods] == ["FY2023", "FY2024", "FY2025"]
    conflict = workspace.get_resolution(_key(2024), "ebit")
    assert {item.value for item in conflict.observations} == {148, 150}
    earlier_source = next(item for item in conflict.observations if item.source_document == report_file_name(2025))
    app.button(key=f"history_source_{earlier_source.observation_id}").click().run()
    assert app.session_state["pdf_document"].file_name == report_file_name(2024)
    assert app.session_state["history_source_view"] == earlier_source.report_id
    assert app.session_state["history_documents"][earlier_source.report_id].file_name == report_file_name(2025)
    assert app.number_input(key="history_source_page_number").value == 1
    archived_text = app.container(key="history_source_page_text").text[0].value
    assert "2025" in archived_text and "148" in archived_text
    assert any(report_file_name(2025) in item.label for item in app.expander)
    assert not app.exception
