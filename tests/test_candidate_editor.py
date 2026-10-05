"""Kandidateneditor: Originaldaten, aktueller Entwurf und aktive Bestätigung."""

from dataclasses import replace
from unittest.mock import Mock

import pytest

from research_update_assistant import pdf_ui
from research_update_assistant.candidate_models import PeriodValueCandidate
from test_validation_app import _app, _company, _confirm, _values


@pytest.fixture
def original_ebitda_app(monkeypatch):
    """Kontrolliertes Zahlenpaar des UX-Repros, ohne externen Geschäftsbericht."""
    extract = pdf_ui.extract_financial_metric_candidates

    def with_original_values(document, config):
        candidates = extract(document, config)
        return tuple(
            replace(candidate, values=tuple(
                replace(value, raw_value="767.2" if value.period_label == "FY2025" else "761.8",
                        normalized_value=767.2 if value.period_label == "FY2025" else 761.8)
                for value in candidate.values
            )) if candidate.canonical_metric == "ebitda" else candidate
            for candidate in candidates
        )

    parser = Mock(side_effect=with_original_values)
    monkeypatch.setattr(pdf_ui, "extract_financial_metric_candidates", parser)
    app = _app()
    _company(app)
    app.selectbox(key="review_metric").select("ebitda").run()
    return app, parser


def _editor_selectbox(app, prefix):
    return next(item for item in app.selectbox if item.key.startswith(prefix))


def test_actions_are_grouped_for_entire_metric_not_individual_periods(original_ebitda_app):
    app, _ = original_ebitda_app
    actions = app.container(key="review_metric_actions")
    assert actions.caption[0].value == "Aktionen für die gesamte Kennzahl (beide Perioden)"
    assert [item.label for item in actions.button] == [
        "Kennzahl bestätigen", "Änderungen zurücksetzen", "Kandidat ablehnen",
    ]
    assert not actions.text_input
    assert [item.value for item in _values(app, "ebitda")] == ["761.8", "767.2"]


def test_reset_restores_both_original_values_and_invalidates_current_confirmation(original_ebitda_app):
    app, parser = original_ebitda_app
    original = next(candidate for candidate in app.session_state["pdf_candidates"] if candidate.canonical_metric == "ebitda")
    _values(app, "ebitda")[1].set_value("768.2").run()
    app.button(key="review_confirm_metric").click().run()
    status, observations = app.session_state["review_records"]["ebitda"]
    assert status == "Geändert"
    observation = next(item for item in observations if item.period_label == "FY2025")
    assert observation.original_value == 767.2 and observation.confirmed_value == 768.2
    app.button(key="review_reset_metric").click().run()
    assert not app.exception and not app.error
    assert [item.value for item in _values(app, "ebitda")] == ["761.8", "767.2"]
    assert "ebitda" not in app.session_state["review_records"]
    assert any(item.value == "Status: Vorgeschlagen" for item in app.text)
    assert observation in app.session_state["review_audit_history"]
    assert next(candidate for candidate in app.session_state["pdf_candidates"] if candidate.canonical_metric == "ebitda") == original
    assert parser.call_count == 1


def test_reset_restores_mapping_currency_and_scale_and_keeps_other_metric(original_ebitda_app):
    app, parser = original_ebitda_app
    _confirm(app, "revenue")
    revenue_confirmation = app.session_state["review_records"]["revenue"]
    app.selectbox(key="review_metric").select("ebitda").run()
    _editor_selectbox(app, "review_mapping_ebitda_").select("adjusted_ebitda").run()
    _editor_selectbox(app, "review_unit_currency_ebitda_").select("EUR").run()
    _editor_selectbox(app, "review_unit_scale_ebitda_").select("thousand").run()
    _values(app, "ebitda")[0].set_value("999").run()
    app.button(key="review_reset_metric").click().run()
    assert not app.exception
    assert _editor_selectbox(app, "review_mapping_ebitda_").value == "ebitda"
    assert _editor_selectbox(app, "review_unit_currency_ebitda_").value == "CHF"
    assert _editor_selectbox(app, "review_unit_scale_ebitda_").value == "million"
    assert [item.value for item in _values(app, "ebitda")] == ["761.8", "767.2"]
    assert app.session_state["review_records"]["revenue"] == revenue_confirmation
    assert app.text_input(key="company_name").value == ""
    assert parser.call_count == 1


def test_rejection_removes_active_correction_restores_original_and_preserves_history(original_ebitda_app):
    app, parser = original_ebitda_app
    _confirm(app, "revenue")
    revenue_confirmation = app.session_state["review_records"]["revenue"]
    app.selectbox(key="review_metric").select("ebitda").run()
    _values(app, "ebitda")[1].set_value("768.2").run()
    app.button(key="review_confirm_metric").click().run()
    correction = next(item for item in app.session_state["review_records"]["ebitda"][1] if item.period_label == "FY2025")
    app.button(key="review_reject_metric").click().run()
    assert not app.exception and not app.error
    assert app.session_state["review_records"]["ebitda"] == ("Abgelehnt", ())
    assert app.session_state["review_records"]["revenue"] == revenue_confirmation
    assert [item.value for item in _values(app, "ebitda")] == ["761.8", "767.2"]
    assert any(item.value == "Status: Abgelehnt" for item in app.text)
    assert correction in app.session_state["review_audit_history"]
    assert correction.original_value == 767.2 and correction.confirmed_value == 768.2
    assert parser.call_count == 1


def test_rejected_candidate_can_be_reopened_and_confirmed_again(original_ebitda_app):
    app, parser = original_ebitda_app
    _values(app, "ebitda")[1].set_value("768.2").run()
    app.button(key="review_confirm_metric").click().run()
    app.button(key="review_reject_metric").click().run()
    app.selectbox(key="review_metric").select("revenue").run()
    app.selectbox(key="review_metric").select("ebitda").run()
    assert [item.value for item in _values(app, "ebitda")] == ["761.8", "767.2"]
    assert app.session_state["review_records"]["ebitda"] == ("Abgelehnt", ())
    app.button(key="review_confirm_metric").click().run()
    assert app.session_state["review_records"]["ebitda"][0] == "Bestätigt"
    assert next(item for item in app.session_state["review_records"]["ebitda"][1] if item.period_label == "FY2025").confirmed_value == 767.2
    _values(app, "ebitda")[1].set_value("769.2").run()
    app.button(key="review_confirm_metric").click().run()
    status, observations = app.session_state["review_records"]["ebitda"]
    assert status == "Geändert"
    assert next(item for item in observations if item.period_label == "FY2025").original_value == 767.2
    assert next(item for item in observations if item.period_label == "FY2025").confirmed_value == 769.2
    assert any(item.confirmed_value == 768.2 for item in app.session_state["review_audit_history"])
    assert parser.call_count == 1
    assert not app.exception


def test_reset_does_not_change_another_source_draft(monkeypatch):
    extract = pdf_ui.extract_financial_metric_candidates

    def with_alternative(document, config):
        candidates = extract(document, config)
        revenue = next(candidate for candidate in candidates if candidate.canonical_metric == "revenue")
        return (*candidates, replace(revenue, candidate_id="revenue-alternative", source_priority=4))

    monkeypatch.setattr(pdf_ui, "extract_financial_metric_candidates", with_alternative)
    app = _app()
    _company(app)
    original_source = app.selectbox(key="review_source_revenue").value
    _values(app, "revenue")[1].set_value("1150").run()
    app.selectbox(key="review_source_revenue").select("revenue-alternative").run()
    _values(app, "revenue")[1].set_value("1250").run()
    app.button(key="review_reset_metric").click().run()
    assert _values(app, "revenue")[1].value == "1100.0"
    app.selectbox(key="review_source_revenue").select(original_source).run()
    assert _values(app, "revenue")[1].value == "1150"
    assert not app.exception


def test_reset_clears_explicit_unknown_period_assignments(monkeypatch):
    extract = pdf_ui.extract_financial_metric_candidates

    def without_headers(document, config):
        candidates = extract(document, config)
        return tuple(replace(candidate, confidence="low", values=(
            PeriodValueCandidate(None, "767.2", 767.2), PeriodValueCandidate(None, "761.8", 761.8),
        )) if candidate.canonical_metric == "ebitda" else candidate for candidate in candidates)

    monkeypatch.setattr(pdf_ui, "extract_financial_metric_candidates", without_headers)
    app = _app()
    _company(app)
    app.selectbox(key="review_metric").select("ebitda").run()
    assignments = [item for item in app.selectbox if item.key.startswith("review_assignment_ebitda_")]
    assignments[0].select(1).run()
    assignments = [item for item in app.selectbox if item.key.startswith("review_assignment_ebitda_")]
    assignments[1].select(0).run()
    _values(app, "ebitda")[0].set_value("761.8")
    _values(app, "ebitda")[1].set_value("768.2").run()
    app.button(key="review_reset_metric").click().run()
    assert [item.value for item in _values(app, "ebitda")] == ["", ""]
    assert all(item.value is None for item in app.selectbox if item.key.startswith("review_assignment_ebitda_"))
    assert "ebitda" not in app.session_state["review_records"]
    assert not app.exception


def test_reset_manual_complement_clears_values_without_invented_originals():
    app = _app(include_capex=False)
    _company(app)
    app.selectbox(key="review_metric").select("capex").run()
    _values(app, "capex")[0].set_value("-60")
    _values(app, "capex")[1].set_value("-80").run()
    app.button(key="review_confirm_metric").click().run()
    manual_confirmation = app.session_state["review_records"]["capex"][1]
    app.button(key="review_reset_metric").click().run()
    assert [item.value for item in _values(app, "capex")] == ["", ""]
    assert "capex" not in app.session_state["review_records"]
    assert all(item.source_document is None and item.original_value is None for item in manual_confirmation)
    assert all(item in app.session_state["review_audit_history"] for item in manual_confirmation)
    assert not app.exception
