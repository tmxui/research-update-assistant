"""PDF- und manuelle Analyse behalten getrennte Eingaben und Ergebnisse."""

from datetime import date
from pathlib import Path
import re
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from pdf_samples import make_financial_pdf
from research_update_assistant import pdf_ui, ui


def _app(*, upload: bool = True) -> AppTest:
    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15,
    ).run()
    if upload:
        app.file_uploader(key="pdf_upload").set_value(
            ("synthetic.pdf", make_financial_pdf(), "application/pdf"),
        ).run()
    assert not app.exception
    return app


def _tab(app: AppTest, label: str):
    return next(tab for tab in app.tabs if tab.label == label)


def _text(block) -> str:
    return "\n".join(
        str(element.value) for kind in ("header", "subheader", "text", "caption", "markdown", "success")
        for element in block.get(kind)
    )


def _values(app: AppTest, metric: str):
    return [widget for widget in app.text_input if widget.key.startswith(f"review_value_{metric}_")]


def _confirm(app: AppTest, metric: str) -> None:
    app.selectbox(key="review_metric").select(metric).run()
    app.button(key="review_confirm_metric").click().run()
    assert not app.exception and not app.error


def _prepare_pdf(app: AppTest, metrics: tuple[str, ...] = ("revenue", "ebit")) -> None:
    app.text_input(key="review_company").set_value("PDF Company AG").run()
    for metric in metrics:
        _confirm(app, metric)
    app.checkbox(key="review_metadata_confirmed").check().run()
    app.button(key="review_accept").click().run()
    assert not app.exception and not app.error


def _start_pdf(app: AppTest) -> None:
    app.button(key="pdf_start_analysis").click().run()
    assert not app.exception and not app.error


def _calculate_manual(app: AppTest, count: int = 2) -> None:
    app.selectbox(key="period_count").select(count).run()
    app.button(key="load_examples").click().run()
    app.text_input(key="company_name").set_value("Manual Company AG")
    app.button(key="calculate_analysis").click().run()
    assert not app.exception and not app.error


def test_workflow_tabs_keep_pdf_controls_and_manual_form_separate():
    app = _app(upload=False)
    assert [tab.label for tab in app.tabs[:2]] == ["PDF-gestützte Analyse", "Manuelle Eingabe"]
    pdf = _tab(app, "PDF-gestützte Analyse")
    manual = _tab(app, "Manuelle Eingabe")
    assert pdf.file_uploader(key="pdf_upload")
    assert manual.button(key="calculate_analysis").label == "Analyse berechnen"
    assert not any(widget.key == "company_name" for widget in pdf.text_input)
    assert not manual.file_uploader
    assert "1. Unternehmensdaten" in _text(manual)
    assert "2. Finanzperioden erfassen" in _text(manual)
    assert "3. Daten prüfen" in _text(manual)


def test_pdf_acceptance_displays_summary_without_running_analysis(monkeypatch):
    calculator = Mock(wraps=ui.calculate_period_metrics)
    comparator = Mock(wraps=ui.compare_periods)
    monkeypatch.setattr(ui, "calculate_period_metrics", calculator)
    monkeypatch.setattr(ui, "compare_periods", comparator)
    app = _app()
    _prepare_pdf(app)
    ready = app.session_state["pdf_ready_history"]
    assert ready.periods[-1].company_name == "PDF Company AG"
    assert [period.period_label for period in ready.periods] == ["FY2024", "FY2025"]
    assert {observation.canonical_metric for observation in app.session_state["pdf_ready_observations"]} == {"revenue", "ebit"}
    assert app.session_state["pdf_analysis_result"] is None
    assert app.session_state["manual_analysis_result"] is None
    assert calculator.call_count == comparator.call_count == 0
    assert not app.get("plotly_chart")
    summary = _text(_tab(app, "PDF-gestützte Analyse"))
    for phrase in ("PDF-Daten bereit für Analyse", "PDF Company AG", "FY2024", "FY2025", "CHF", "Millionen"):
        assert phrase in summary
    assert re.search(r"(?:Bestätigte Kennzahlen:\s*2|2 bestätigte Kennzahlen)", summary)
    assert app.button(key="pdf_start_analysis").label == "Analyse aus bestätigten PDF-Daten starten"
    assert app.text_input(key="company_name").value == ""
    assert app.text_input(key="period_1_revenue").value == ""


def test_pdf_start_reaches_dashboard_without_manual_inputs_using_shared_engine(monkeypatch):
    calculator = Mock(wraps=ui.calculate_period_metrics)
    comparator = Mock(wraps=ui.compare_periods)
    monkeypatch.setattr(ui, "calculate_period_metrics", calculator)
    monkeypatch.setattr(ui, "compare_periods", comparator)
    app = _app()
    _prepare_pdf(app)
    _start_pdf(app)
    result = app.session_state["pdf_analysis_result"]
    assert calculator.call_count == 2
    assert comparator.call_count == 1
    assert result.history.periods[-1].revenue == 1100
    assert result.metrics[-1].ebit_margin == pytest.approx(143 / 1100)
    assert result.comparisons[0].ebit_margin_change_bps == pytest.approx(-200)
    assert result.observations and all(item.source_document == "synthetic.pdf" for item in result.observations)
    assert _tab(app, "PDF-gestützte Analyse").metric[0].value == "1'100"
    assert _tab(app, "PDF-gestützte Analyse").get("plotly_chart")
    assert "Stand: zuletzt analysierte PDF-Prüfdaten." in _text(_tab(app, "PDF-gestützte Analyse"))
    assert not _tab(app, "Manuelle Eingabe").get("plotly_chart")
    assert app.session_state["manual_analysis_result"] is None
    assert app.text_input(key="company_name").value == ""
    app.run()
    assert not app.exception
    assert app.session_state["pdf_analysis_result"] is result
    assert calculator.call_count == 2


@pytest.mark.parametrize("count", [2, 3])
def test_manual_examples_reach_only_manual_dashboard(count):
    app = _app(upload=False)
    _calculate_manual(app, count)
    result = app.session_state["manual_analysis_result"]
    assert len(result.history.periods) == count
    assert result.metrics[-1].calculated_free_cash_flow == 60
    assert result.history.periods[-1].company_name == "Manual Company AG"
    assert result.observations == ()
    assert not _tab(app, "PDF-gestützte Analyse").get("plotly_chart")
    assert len(_tab(app, "Manuelle Eingabe").get("plotly_chart")) == 7
    manual_text = _text(_tab(app, "Manuelle Eingabe"))
    assert "Stand: zuletzt berechnete Eingaben." in manual_text
    assert "zuletzt analysierte PDF-Prüfdaten" not in manual_text
    assert app.session_state["pdf_ready_history"] is None
    assert app.session_state["pdf_analysis_result"] is None
    app.run()
    assert not app.exception
    assert app.session_state["manual_analysis_result"] is result


def test_both_workflows_keep_independent_results_when_both_dashboards_render():
    app = _app()
    _calculate_manual(app, 3)
    manual = app.session_state["manual_analysis_result"]
    _prepare_pdf(app)
    _start_pdf(app)
    pdf = app.session_state["pdf_analysis_result"]
    assert app.session_state["manual_analysis_result"] is manual
    assert manual.history.periods[-1].company_name == "Manual Company AG"
    assert pdf.history.periods[-1].company_name == "PDF Company AG"
    assert len(manual.history.periods) == 3 and len(pdf.history.periods) == 2
    assert _tab(app, "PDF-gestützte Analyse").get("plotly_chart")
    assert len(_tab(app, "Manuelle Eingabe").get("plotly_chart")) == 7
    assert app.text_input(key="company_name").value == "Manual Company AG"
    # AppTest stellt für Tabs keinen Auswahlsetter bereit. Der öffentliche
    # Widget-State bildet denselben gewählten Tab beim nächsten Aufbau ab.
    for selected_tab in ("Manuelle Eingabe", "PDF-gestützte Analyse"):
        app.session_state["analysis_workflows"] = selected_tab
        app.run()
        assert not app.exception
        assert app.session_state["manual_analysis_result"] is manual
        assert app.session_state["pdf_analysis_result"] is pdf
        assert app.text_input(key="company_name").value == "Manual Company AG"
        assert app.text_input(key="review_company").value == "PDF Company AG"
    app.text_input(key="period_2_revenue").set_value("1200")
    app.button(key="calculate_analysis").click().run()
    assert not app.exception and not app.error
    assert app.session_state["manual_analysis_result"].history.periods[-1].revenue == 1200
    assert app.session_state["pdf_analysis_result"] is pdf
    assert app.session_state["pdf_ready_history"].periods[-1].revenue == 1100
    app.selectbox(key="period_count").select(2).run()
    assert not app.exception
    assert app.session_state["pdf_analysis_result"] is pdf


@pytest.mark.parametrize("change", ["value", "metadata", "reject", "reset"])
def test_pdf_edits_invalidate_ready_snapshot_and_pdf_result_only(change):
    app = _app()
    _calculate_manual(app)
    manual = app.session_state["manual_analysis_result"]
    _prepare_pdf(app)
    _start_pdf(app)
    app.selectbox(key="review_metric").select("revenue").run()
    if change == "value":
        _values(app, "revenue")[1].set_value("1200").run()
    elif change == "metadata":
        app.text_input(key="review_company").set_value("Changed PDF Company AG").run()
    elif change == "reset":
        app.button(key="review_reset_metric").click().run()
    else:
        app.button(key="review_reject_metric").click().run()
    assert not app.exception
    assert app.session_state["pdf_ready_history"] is None
    assert app.session_state["pdf_ready_observations"] == ()
    assert app.session_state["pdf_analysis_result"] is None
    assert app.session_state["manual_analysis_result"] is manual
    assert not any(button.key == "pdf_start_analysis" for button in app.button)
    assert not _tab(app, "PDF-gestützte Analyse").get("plotly_chart")
    assert len(_tab(app, "Manuelle Eingabe").get("plotly_chart")) == 7


@pytest.mark.parametrize("replacement", ["same_filename", "remove", "invalid"])
def test_upload_changes_clear_pdf_snapshots_and_reviews_but_preserve_manual(replacement):
    app = _app()
    _calculate_manual(app)
    manual = app.session_state["manual_analysis_result"]
    _prepare_pdf(app)
    _start_pdf(app)
    if replacement == "remove":
        app.file_uploader(key="pdf_upload").clear().run()
    else:
        data = make_financial_pdf(reverse_years=True) if replacement == "same_filename" else b"not a pdf"
        app.file_uploader(key="pdf_upload").set_value(("synthetic.pdf", data, "application/pdf")).run()
    assert not app.exception
    assert app.session_state["pdf_ready_history"] is None
    assert app.session_state["pdf_ready_observations"] == ()
    assert app.session_state["pdf_analysis_result"] is None
    assert not app.session_state.get("review_records", {})
    assert app.session_state["manual_analysis_result"] is manual
    assert app.text_input(key="company_name").value == "Manual Company AG"
    assert not _tab(app, "PDF-gestützte Analyse").get("plotly_chart")
    assert len(_tab(app, "Manuelle Eingabe").get("plotly_chart")) == 7
    if replacement == "same_filename":
        assert app.text_input(key="review_company").value == ""
        assert not app.checkbox(key="review_metadata_confirmed").value


def test_pdf_reset_and_navigation_reuse_saved_extraction(monkeypatch):
    parser = Mock(wraps=pdf_ui.extract_pdf_document)
    candidates = Mock(wraps=pdf_ui.extract_financial_metric_candidates)
    monkeypatch.setattr(pdf_ui, "extract_pdf_document", parser)
    monkeypatch.setattr(pdf_ui, "extract_financial_metric_candidates", candidates)
    app = _app()
    app.text_input(key="review_company").set_value("PDF Company AG").run()
    _values(app, "revenue")[1].set_value("1200").run()
    app.button(key="review_reset_metric").click().run()
    assert [item.value for item in _values(app, "revenue")] == ["1000.0", "1100.0"]
    _prepare_pdf(app)
    ready = app.session_state["pdf_ready_history"]
    app.text_input(key="pdf_search_query").set_value("EBIT").run()
    app.number_input(key="pdf_page_number").set_value(3).run()
    app.selectbox(key="review_metric").select("inventory").run()
    assert app.session_state["pdf_ready_history"] is ready
    assert {"revenue", "ebit"} <= set(app.session_state["review_records"])
    # Die Auswahl allein verändert keine bestätigten Zahlen; erst die neue
    # Bestätigung ergänzt den Stand und macht eine erneute Übernahme notwendig.
    app.button(key="review_confirm_metric").click().run()
    assert app.session_state["pdf_ready_history"] is None
    assert ready.periods[-1].revenue == 1100
    app.run()
    assert not app.exception
    assert parser.call_count == candidates.call_count == 1


def test_manual_additions_within_pdf_review_stay_in_pdf_workflow(monkeypatch):
    monkeypatch.setattr(pdf_ui, "extract_financial_metric_candidates", lambda document, config: ())
    app = _app()
    app.text_input(key="review_company").set_value("PDF Company AG").run()
    app.selectbox(key="review_currency").select("CHF").run()
    app.selectbox(key="review_scale").select("million").run()
    for index, year in enumerate((2024, 2025)):
        app.text_input(key=f"review_period_{index}_label").set_value(f"FY{year}").run()
        app.date_input(key=f"review_period_{index}_end").set_value(date(year, 12, 31)).run()
        app.number_input(key=f"review_period_{index}_months").set_value(12).run()
    assert app.selectbox(key="review_source_revenue").value == "manual"
    app.selectbox(key="review_unit_currency_revenue_manual").select("CHF").run()
    app.selectbox(key="review_unit_scale_revenue_manual").select("million").run()
    _values(app, "revenue")[0].set_value("1000")
    _values(app, "revenue")[1].set_value("1100").run()
    app.button(key="review_confirm_metric").click().run()
    app.checkbox(key="review_metadata_confirmed").check().run()
    app.button(key="review_accept").click().run()
    assert not app.exception and not app.error
    assert app.session_state["pdf_ready_history"] is not None
    assert all(item.source_document is None for item in app.session_state["pdf_ready_observations"])
    _start_pdf(app)
    assert _tab(app, "PDF-gestützte Analyse").get("plotly_chart")
    assert not _tab(app, "Manuelle Eingabe").get("plotly_chart")
    assert app.session_state["manual_analysis_result"] is None
    assert app.text_input(key="company_name").value == ""
