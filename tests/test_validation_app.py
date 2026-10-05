"""PDF-Prüfung bis zum bestehenden Dashboard mit echten synthetischen Uploads."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from pdf_samples import make_financial_pdf
from research_update_assistant import pdf_ui, ui
from research_update_assistant.candidate_models import PeriodValueCandidate


def _app(*, include_capex: bool = True) -> AppTest:
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()
    app.file_uploader(key="pdf_upload").set_value(("synthetic.pdf", make_financial_pdf(include_capex=include_capex), "application/pdf")).run()
    assert not app.exception
    return app


def _company(app: AppTest) -> None:
    app.text_input(key="review_company").set_value("Synthetic Industrial AG").run()


def _values(app: AppTest, metric: str):
    return [item for item in app.text_input if item.key.startswith(f"review_value_{metric}_")]


def _confirm(app: AppTest, metric: str) -> None:
    app.selectbox(key="review_metric").select(metric).run()
    app.button(key="review_confirm_metric").click().run()
    assert not app.exception and not app.error


def _accept(app: AppTest) -> None:
    app.checkbox(key="review_metadata_confirmed").check().run()
    app.button(key="review_accept").click().run()
    assert not app.exception
    if not app.error and app.session_state["pdf_ready_history"] is not None:
        app.button(key="pdf_start_analysis").click().run()
        assert not app.exception


def test_candidates_are_visible_but_never_create_financial_periods(monkeypatch):
    calculator = Mock(wraps=ui.calculate_period_metrics)
    monkeypatch.setattr(ui, "calculate_period_metrics", calculator)
    app = _app()
    assert "Extrahierte Finanzdaten prüfen" in [item.value for item in app.header]
    assert any("Originalbezeichnung: Nettoumsatz" in item.value for item in app.text)
    assert any("PDF-Seite 1" in item.value for item in app.text)
    assert [item.value for item in _values(app, "revenue")] == ["1000.0", "1100.0"]
    assert app.session_state["analysis_result"] is None
    assert calculator.call_count == 0
    _company(app)
    _confirm(app, "revenue")
    assert app.session_state["analysis_result"] is None
    assert calculator.call_count == 0
    _accept(app)
    assert calculator.call_count == 2
    assert app.session_state["analysis_result"].history.periods[-1].ebit is None


def test_correction_audit_and_existing_dashboard_then_manual_regression():
    app = _app()
    _company(app)
    _confirm(app, "revenue")
    app.selectbox(key="review_metric").select("ebit").run()
    assert any("Betriebsergebnis (EBIT)" in item.value for item in app.text)
    _values(app, "ebit")[1].set_value("145").run()
    app.button(key="review_confirm_metric").click().run()
    assert app.session_state["review_records"]["ebit"][0] == "Geändert"
    _accept(app)
    assert not app.error
    result = app.session_state["analysis_result"]
    assert [p.period_label for p in result.history.periods] == ["FY2024", "FY2025"]
    assert result.history.periods[-1].ebit == 145
    assert result.metrics[-1].ebit_margin == pytest.approx(145 / 1100)
    assert result.metrics[0].ebit_margin == pytest.approx(0.15)
    observation = next(o for o in result.observations if o.canonical_metric == "ebit" and o.period_label == "FY2025")
    assert observation.original_value == 143 and observation.confirmed_value == 145
    assert observation.page_number == 1 and observation.source_document == "synthetic.pdf"
    assert len(app.get("plotly_chart")) > 0
    assert app.metric[0].value == "1'100"
    app.selectbox(key="period_count").select(3).run()
    app.button(key="load_examples").click().run()
    app.button(key="calculate_analysis").click().run()
    assert not app.exception and not app.error
    assert app.session_state["analysis_result"].metrics[-1].calculated_free_cash_flow == 60
    manual_tab = next(tab for tab in app.tabs if tab.label == "Manuelle Eingabe")
    assert len(manual_tab.get("plotly_chart")) == 7
    assert app.session_state["analysis_result"].observations == ()


def test_confirmation_is_invalidated_by_value_or_metadata_changes():
    app = _app()
    _company(app)
    _confirm(app, "revenue")
    _values(app, "revenue")[1].set_value("1200").run()
    assert "revenue" not in app.session_state["review_records"]
    _accept(app)
    assert app.session_state["analysis_result"] is None
    assert any("mindestens eine Kennzahl" in item.value for item in app.error)
    _confirm(app, "revenue")
    app.text_input(key="review_company").set_value("New company AG").run()
    assert not app.session_state["review_records"]
    assert not app.checkbox(key="review_metadata_confirmed").value


def test_rejected_candidate_is_not_taken_and_metadata_requires_confirmation():
    app = _app()
    _company(app)
    _confirm(app, "revenue")
    app.button(key="review_reject_metric").click().run()
    assert app.session_state["review_records"]["revenue"] == ("Abgelehnt", ())
    app.button(key="review_accept").click().run()
    assert any("zuerst Unternehmen" in item.value for item in app.error)
    assert app.session_state["analysis_result"] is None


def test_missing_metric_can_be_added_without_invented_pdf_source():
    app = _app(include_capex=False)
    _company(app)
    _confirm(app, "revenue")
    _confirm(app, "operating_cash_flow")
    app.selectbox(key="review_metric").select("capex").run()
    assert app.selectbox(key="review_source_capex").value == "manual"
    assert [item.value for item in _values(app, "capex")] == ["", ""]
    _values(app, "capex")[0].set_value("-60")
    _values(app, "capex")[1].set_value("-80").run()
    app.button(key="review_confirm_metric").click().run()
    _accept(app)
    assert not app.error
    result = app.session_state["analysis_result"]
    assert result.metrics[-1].calculated_free_cash_flow == 60
    assert result.metrics[0].calculated_free_cash_flow == 100
    assert all(o.source_document is None and o.page_number is None
               for o in result.observations if o.canonical_metric == "capex")


def test_source_jump_uses_existing_browser_and_drafts_survive_metric_switch():
    app = _app()
    _company(app)
    app.selectbox(key="review_metric").select("inventory").run()
    _values(app, "inventory")[1].set_value("195").run()
    app.button(key="review_show_source").click().run()
    assert app.number_input(key="pdf_page_number").value == 2
    app.selectbox(key="review_metric").select("revenue").run()
    app.selectbox(key="review_metric").select("inventory").run()
    assert _values(app, "inventory")[1].value == "195"
    assert not app.exception


def test_alternative_source_selection_requires_fresh_confirmation(monkeypatch):
    original = pdf_ui.extract_financial_metric_candidates
    def with_alternative(document, config):
        candidates = original(document, config)
        revenue = next(c for c in candidates if c.canonical_metric == "revenue")
        alternative = replace(revenue, candidate_id="different-revenue", source_priority=4,
                              values=tuple(replace(v, normalized_value=1200, raw_value="1200") if v.period_label == "FY2025" else v for v in revenue.values))
        return (*candidates, alternative)
    monkeypatch.setattr(pdf_ui, "extract_financial_metric_candidates", with_alternative)
    app = _app()
    _company(app)
    _confirm(app, "revenue")
    app.selectbox(key="review_source_revenue").select("different-revenue").run()
    assert "revenue" not in app.session_state["review_records"]
    assert _values(app, "revenue")[1].value == "1200"
    _confirm(app, "revenue")
    _accept(app)
    assert app.session_state["analysis_result"].history.periods[-1].revenue == 1200


def _with_ranked_revenue_sources(monkeypatch) -> None:
    """Mehrere erhaltene Quellen mit bewusst umgekehrter Eingangsreihenfolge."""
    original = pdf_ui.extract_financial_metric_candidates

    def with_sources(document, config):
        candidates = original(document, config)
        revenue = next(c for c in candidates if c.canonical_metric == "revenue")
        sources = []
        for identifier, source_type, priority, confidence, page in (
            ("primary-exact", "primary_statement", 1, "high", 3),
            ("primary-synonym", "primary_statement", 1, "medium", 2),
            ("notes", "notes", 2, "medium", 2),
            ("key-figures", "key_figures", 3, "medium", 1),
            ("apm", "apm", 4, "medium", 1),
            ("highlights", "highlights", 5, "medium", 1),
            ("narrative", "narrative", 6, "low", 1),
        ):
            precise = identifier == "primary-exact"
            sources.append(replace(
                revenue, candidate_id=identifier, source_type=source_type,
                source_priority=priority, confidence=confidence, page_number=page,
                reported_label="Nettoumsatz \ue000 28" if precise else "Nettoumsatz",
                normalized_label="nettoumsatz",
                values=tuple(replace(
                    value, normalized_value=1099.6 if value.period_label == "FY2025" else 1000.4,
                    raw_value="1099.6" if value.period_label == "FY2025" else "1000.4",
                ) for value in revenue.values) if precise else revenue.values,
            ))
        return tuple(c for c in candidates if c.canonical_metric != "revenue") + tuple(reversed(sources))

    monkeypatch.setattr(pdf_ui, "extract_financial_metric_candidates", with_sources)


def test_best_five_sources_are_visible_and_precise_primary_value_is_selected(monkeypatch):
    _with_ranked_revenue_sources(monkeypatch)
    app = _app()
    selector = app.selectbox(key="review_source_revenue")
    assert selector.value == "primary-exact"
    assert len(selector.options) == 6  # Fünf PDF-Quellen plus manuelle Ergänzung.
    assert "Primäres Finanzstatement" in selector.options[0]
    assert "Kennzahlenübersicht / Mehrjahrestabelle" in selector.options[3]
    assert [item.value for item in _values(app, "revenue")] == ["1000.4", "1099.6"]
    assert any("Originalbezeichnung: Nettoumsatz \ue000 28" in item.value for item in app.text)
    _company(app)
    _confirm(app, "revenue")
    _accept(app)
    assert app.session_state["analysis_result"].history.periods[-1].revenue == 1099.6
    app.checkbox(key="review_show_all_revenue").check().run()
    assert len(app.selectbox(key="review_source_revenue").options) == 8
    assert app.selectbox(key="review_source_revenue").value == "primary-exact"
    assert "revenue" in app.session_state["review_records"]
    assert not app.exception


def test_collapsing_sources_preserves_selected_alternative_and_confirmation(monkeypatch):
    _with_ranked_revenue_sources(monkeypatch)
    app = _app()
    _company(app)
    _confirm(app, "revenue")
    app.checkbox(key="review_show_all_revenue").check().run()
    app.selectbox(key="review_source_revenue").select("highlights").run()
    assert "revenue" not in app.session_state["review_records"]
    _values(app, "revenue")[1].set_value("1110").run()
    _confirm(app, "revenue")
    app.checkbox(key="review_show_all_revenue").uncheck().run()
    assert app.selectbox(key="review_source_revenue").value == "highlights"
    assert len(app.selectbox(key="review_source_revenue").options) == 7
    assert _values(app, "revenue")[1].value == "1110"
    assert "revenue" in app.session_state["review_records"]
    _accept(app)
    result = app.session_state["analysis_result"]
    assert result.history.periods[-1].revenue == 1110
    observation = next(o for o in result.observations if o.period_label == "FY2025")
    assert observation.original_value == 1100
    app.selectbox(key="review_source_revenue").select("manual").run()
    app.checkbox(key="review_show_all_revenue").check().run()
    app.checkbox(key="review_show_all_revenue").uncheck().run()
    assert app.selectbox(key="review_source_revenue").value == "manual"
    assert not app.exception


def test_remapping_is_explicit_and_duplicate_target_is_blocked():
    app = _app()
    _company(app)
    _confirm(app, "revenue")
    app.selectbox(key="review_metric").select("ebit").run()
    mapping = next(item for item in app.selectbox if item.key.startswith("review_mapping_ebit_"))
    mapping.select("revenue").run()
    app.button(key="review_confirm_metric").click().run()
    _accept(app)
    assert app.session_state["analysis_result"] is None
    assert app.error


def test_unknown_headers_require_explicit_period_assignment(monkeypatch):
    original = pdf_ui.extract_financial_metric_candidates
    def without_headers(document, config):
        candidates = original(document, config)
        revenue = next(c for c in candidates if c.canonical_metric == "revenue")
        revenue = replace(revenue, confidence="low", values=(
            PeriodValueCandidate(None, "1100", 1100), PeriodValueCandidate(None, "1000", 1000),
        ))
        return tuple(c for c in candidates if c.canonical_metric != "revenue") + (revenue,)
    monkeypatch.setattr(pdf_ui, "extract_financial_metric_candidates", without_headers)
    app = _app()
    _company(app)
    assert [item.value for item in _values(app, "revenue")] == ["", ""]
    assignments = [item for item in app.selectbox if item.key.startswith("review_assignment_")]
    assignments[0].select(1).run()
    assignments = [item for item in app.selectbox if item.key.startswith("review_assignment_")]
    assignments[1].select(0).run()
    _values(app, "revenue")[0].set_value("1000")
    _values(app, "revenue")[1].set_value("1100").run()
    _confirm(app, "revenue")
    _accept(app)
    result = app.session_state["analysis_result"]
    assert result.history.periods[-1].revenue == 1100
    assert all(o.original_period_label is None and o.source_document == "synthetic.pdf" for o in result.observations)


def test_document_replacement_clears_all_review_decisions():
    app = _app()
    _company(app)
    _confirm(app, "revenue")
    _accept(app)
    app.file_uploader(key="pdf_upload").set_value(("different.pdf", make_financial_pdf(reverse_years=True), "application/pdf")).run()
    assert not app.exception
    assert not app.session_state["review_records"]
    assert app.text_input(key="review_company").value == ""
    assert not app.checkbox(key="review_metadata_confirmed").value
    assert app.session_state["pdf_ready_history"] is None
    assert app.session_state["pdf_analysis_result"] is None
    assert app.session_state["analysis_result"] is None


def test_unit_mismatch_is_blocked_without_silent_conversion():
    app = _app()
    _company(app)
    unit = next(item for item in app.selectbox if item.key.startswith("review_unit_currency_revenue_"))
    unit.select("EUR").run()
    _confirm(app, "revenue")
    _accept(app)
    assert app.session_state["analysis_result"] is None
    assert any("Währung oder Skalierung" in item.value for item in app.error)


def test_segment_candidate_cannot_be_confirmed(monkeypatch):
    original = pdf_ui.extract_financial_metric_candidates
    def only_segment_revenue(document, config):
        return tuple(replace(c, is_segment=True, reported_label="Nettoumsatz Europa")
                     if c.canonical_metric == "revenue" else c for c in original(document, config))
    monkeypatch.setattr(pdf_ui, "extract_financial_metric_candidates", only_segment_revenue)
    app = _app()
    assert app.button(key="review_confirm_metric").disabled
    assert any("Segment-/Regionswert" in item.value for item in app.warning)
    assert app.session_state["analysis_result"] is None
    app.selectbox(key="review_source_revenue").select("manual").run()
    assert not app.button(key="review_confirm_metric").disabled


def test_eps_remains_currency_per_share_in_the_same_dashboard():
    app = _app()
    _company(app)
    _confirm(app, "revenue")
    app.selectbox(key="review_metric").select("basic_eps").run()
    _values(app, "basic_eps")[0].set_value("2.00")
    _values(app, "basic_eps")[1].set_value("2.20").run()
    app.button(key="review_confirm_metric").click().run()
    _accept(app)
    assert not app.exception and not app.error
    result = app.session_state["analysis_result"]
    assert result.history.periods[-1].scale == "million"
    assert result.history.periods[-1].basic_eps == 2.2
    assert all(o.scale == "unit" for o in result.observations if o.canonical_metric == "basic_eps")
    assert any("EPS-Werte sind CHF je Aktie" in item.value for item in app.caption)
