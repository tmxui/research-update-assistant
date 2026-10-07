"""Stabile AppTest-Uploads, Seiten-/Suchnavigation und manuelle Regression."""

from pathlib import Path
from unittest.mock import Mock

import pymupdf
from streamlit.testing.v1 import AppTest

from research_update_assistant import pdf_ui, ui


def _new_app() -> AppTest:
    return AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()


def _upload(app: AppTest, data: bytes) -> AppTest:
    app.file_uploader(key="pdf_upload").set_value(("synthetic.pdf", data, "application/pdf")).run()
    return app


def test_pdf_uploader_and_manual_form_coexist():
    app = _new_app()
    assert not app.exception
    assert app.file_uploader(key="pdf_upload").allowed_type == [".pdf"]
    assert app.file_uploader(key="pdf_upload").label == "Geschäfts- oder Ergebnisbericht als PDF hochladen"
    assert app.button(key="calculate_analysis").label == "Analyse berechnen"
    assert app.session_state["pdf_document"] is None
    assert app.session_state["analysis_result"] is None


def test_upload_renders_document_and_does_not_start_financial_analysis(synthetic_pdf_bytes, monkeypatch):
    finance = Mock(wraps=ui.calculate_period_metrics)
    monkeypatch.setattr(ui, "calculate_period_metrics", finance)
    app = _upload(_new_app(), synthetic_pdf_bytes)
    assert not app.exception and not app.error
    assert {"Dokumentübersicht", "Textsuche", "Seitenbrowser"} <= {element.value for element in app.subheader}
    assert any("Seiten: 3" in element.value for element in app.text)
    assert any("Extraktionsqualität: Gut" in element.value for element in app.text)
    assert "Geschäftsbericht" in app.container(key="pdf_page_text").text[0].value
    assert app.number_input(key="pdf_page_number").value == 1
    assert app.session_state["analysis_result"] is None
    assert finance.call_count == 0
    assert not app.get("plotly_chart")


def test_page_search_navigation_and_raw_table_display(synthetic_pdf_bytes):
    app = _upload(_new_app(), synthetic_pdf_bytes)
    app.number_input(key="pdf_page_number").set_value(2).run()
    assert not app.exception
    assert "Betriebsgewinn (EBIT)" in app.container(key="pdf_page_text").text[0].value
    app.text_input(key="pdf_search_query").set_value("ebit").run()
    assert any("3 Treffer auf 2 Seiten" in caption.value for caption in app.caption)
    app.button(key="pdf_search_page_3").click().run()
    assert not app.exception
    assert app.number_input(key="pdf_page_number").value == 3
    assert "Roh-Tabelle" in app.container(key="pdf_page_text").text[0].value
    assert app.dataframe[0].value.iloc[1, 1] == "1’100"
    assert app.dataframe[0].value.iloc[0, 0] == "Rohbezeichnung"
    app.text_input(key="pdf_search_query").set_value("Nettoumsatz").run()
    assert any("3 Treffer auf 2 Seiten" in caption.value for caption in app.caption)
    app.text_input(key="pdf_search_query").set_value("not found").run()
    assert any("Keine Treffer" in caption.value for caption in app.caption)


def test_pdf_is_extracted_once_per_upload_not_on_search_or_manual_rerun(synthetic_pdf_bytes, monkeypatch):
    parser = Mock(wraps=pdf_ui.extract_pdf_document)
    monkeypatch.setattr(pdf_ui, "extract_pdf_document", parser)
    app = _upload(_new_app(), synthetic_pdf_bytes)
    app.text_input(key="pdf_search_query").set_value("EBIT").run()
    app.number_input(key="pdf_page_number").set_value(3).run()
    app.selectbox(key="period_count").select(3).run()
    app.button(key="load_examples").click().run()
    app.button(key="calculate_analysis").click().run()
    assert not app.exception and not app.error
    assert parser.call_count == 1
    result = app.session_state["analysis_result"]
    assert [period.period_label for period in result.history.periods] == ["FY2023", "FY2024", "FY2025"]
    assert result.metrics[-1].calculated_free_cash_flow == 60
    assert len(app.get("plotly_chart")) == 7
    assert app.metric[0].value == "1'100"
    assert app.session_state["pdf_document"].page_count == 3


def test_pdf_removal_clears_document_but_preserves_manual_analysis(synthetic_pdf_bytes):
    app = _upload(_new_app(), synthetic_pdf_bytes)
    app.button(key="load_examples").click().run()
    app.button(key="calculate_analysis").click().run()
    app.file_uploader(key="pdf_upload").clear().run()
    assert not app.exception
    assert app.session_state["pdf_document"] is None
    assert app.session_state["pdf_signature"] is None
    assert app.session_state["analysis_result"] is not None
    assert app.metric[0].value == "1'100"
    assert "Seitenbrowser" not in [element.value for element in app.subheader]


def test_replacing_same_filename_resets_page_and_search(synthetic_pdf_bytes):
    app = _upload(_new_app(), synthetic_pdf_bytes)
    app.number_input(key="pdf_page_number").set_value(3).run()
    app.text_input(key="pdf_search_query").set_value("EBIT").run()
    with pymupdf.open() as pdf:
        pdf.new_page()
        data = pdf.tobytes()
    _upload(app, data)
    assert not app.exception
    assert app.session_state["pdf_document"].page_count == 1
    assert app.number_input(key="pdf_page_number").value == 1
    assert app.text_input(key="pdf_search_query").value == ""
    assert not any(element.key == "pdf_page_text" for element in app.container)
    assert not any(item.key and item.key.startswith("pdf_table_") for item in app.dataframe)
    assert app.session_state["pdf_candidates"] == ()
    assert app.session_state["pdf_document"].possibly_scanned
    assert any("könnte gescannt sein" in warning.value for warning in app.warning)
    assert any("keine zuverlässigen Kennzahlvorschläge" in warning.value for warning in app.warning)


def test_invalid_upload_reports_error_and_manual_analysis_still_works(synthetic_pdf_bytes):
    app = _upload(_new_app(), synthetic_pdf_bytes)
    _upload(app, b"not a pdf")
    assert not app.exception
    assert app.session_state["pdf_document"] is None
    assert "gültiges" in app.error[0].value
    assert "Dokumentübersicht" not in [element.value for element in app.subheader]
    app.selectbox(key="period_count").select(3).run()
    app.button(key="load_examples").click().run()
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert app.session_state["analysis_result"].metrics[-1].calculated_free_cash_flow == 60
    assert len(app.metric) == 5
