"""Streamlit-Integration für Guidance-Erfassung und Results Update."""

from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

from phase6_samples import make_confirmed_report
from research_update_assistant.expectation_models import ExpectationSnapshot
from research_update_assistant.guidance_models import GuidanceItem, GuidanceSnapshot
from research_update_assistant.history_workspace import HistoryWorkspace, PeriodKey


def _token(year: int) -> str:
    return str(PeriodKey(date(year, 12, 31), 12))


def _history_app() -> AppTest:
    history, observations = make_confirmed_report(2025)
    workspace = HistoryWorkspace("Synthetic Industrial AG", "CHF", "million")
    workspace = workspace.add_report(history, observations, "synthetic_report_2025.pdf")
    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20,
    ).run()
    app.session_state["history_workspace"] = workspace
    app.session_state["history_trend_periods"] = [_token(2024), _token(2025)]
    app.session_state["history_previous_period"] = _token(2024)
    app.session_state["history_current_period"] = _token(2025)
    app.session_state["history_analysis_active"] = True
    app.run()
    assert not app.exception
    return app


def _update(app: AppTest):
    views = app.get_by_key("history_analysis_views")
    return next(tab for tab in views.tabs if tab.label == "Ergebnis-Update")


def _guidance_table(app: AppTest):
    return next(
        item.value.set_index("Kennzahl")
        for item in _update(app).dataframe
        if "Guidance" in item.value.columns and "Status" in item.value.columns
    )


def _guidance_snapshot(when: date, label: str, lower: float) -> GuidanceSnapshot:
    return GuidanceSnapshot(
        company="Synthetic Industrial AG",
        target_period=PeriodKey(date(2025, 12, 31), 12),
        as_of_date=when,
        label=label,
        source_type="results_presentation",
        currency="CHF",
        scale="million",
        guidance_items=(
            GuidanceItem("revenue_growth", "range", minimum=lower, maximum=0.06),
            GuidanceItem("ebitda_margin", "above", minimum=0.19),
        ),
        source_document="synthetic_results.pdf",
        source_page=3,
        notes="Nur synthetische Testdaten.",
    )


def test_without_guidance_phase_seven_and_expectation_screen_stay_clean() -> None:
    app = _history_app()
    headings = [item.value for item in _update(app).subheader]
    assert "Guidance" not in headings
    assert "Wichtigste Veränderungen" in headings
    assert "Research-Prüfpunkte" in headings
    assert not app.exception


def test_manual_guidance_form_keeps_two_snapshots_and_shows_latest_change() -> None:
    app = _history_app()
    target = "Synthetic Industrial AG|2025-12-31|12|CHF|million"
    app.selectbox(key="guidance_target_period").select(target)
    app.text_input(key="guidance_label").set_value("FY2025 Guidance März")
    app.date_input(key="guidance_as_of_date").set_value(date(2025, 3, 1))
    app.selectbox(key="guidance_type_revenue_growth").select("range")
    app.text_input(key="guidance_minimum_revenue_growth").set_value("4")
    app.text_input(key="guidance_maximum_revenue_growth").set_value("6")
    app.button(key="guidance_save").click().run()

    assert not app.exception and not app.error
    assert len(app.session_state["guidance_snapshots"]) == 1
    first = app.session_state["guidance_snapshots"][0]
    assert first.get("revenue_growth").minimum == 0.04
    assert first.get("revenue_growth").maximum == 0.06

    app.text_input(key="guidance_label").set_value("FY2025 Guidance August")
    app.date_input(key="guidance_as_of_date").set_value(date(2025, 8, 1))
    app.text_input(key="guidance_minimum_revenue_growth").set_value("5")
    app.button(key="guidance_save").click().run()

    assert not app.exception and not app.error
    assert len(app.session_state["guidance_snapshots"]) == 2
    table = _guidance_table(app)
    assert table.loc["Umsatzwachstum", "Guidance"] == "5.0 %–6.0 %"
    assert table.loc["Umsatzwachstum", "Actual"] == "10.0 %"
    assert table.loc["Umsatzwachstum", "Status"] == "über Guidance"
    assert table.loc["Umsatzwachstum", "Vorherige Guidance"] == "4.0 %–6.0 %"
    assert table.loc["Umsatzwachstum", "Änderung"] == "angehoben / Range eingeengt"


def test_guidance_and_expectation_are_rendered_and_selected_independently() -> None:
    app = _history_app()
    guidance = _guidance_snapshot(date(2025, 8, 1), "FY2025 Guidance August", 0.05)
    expectation = ExpectationSnapshot(
        company="Synthetic Industrial AG",
        target_period=PeriodKey(date(2025, 12, 31), 12),
        as_of_date=date(2025, 9, 1),
        label="Illustrative Testerwartungen",
        source_type="internal",
        currency="CHF",
        scale="million",
        metric_expectations={"revenue": 1080},
    )
    app.session_state["guidance_snapshots"] = (guidance,)
    app.session_state["expectation_snapshots"] = (expectation,)
    app.run()

    headings = [item.value for item in _update(app).subheader]
    assert "Guidance" in headings
    assert "Abweichung zu Erwartungen" in headings
    assert app.selectbox(key="history_guidance_snapshot").value == guidance.snapshot_id
    assert app.selectbox(key="history_expectation_snapshot").value == expectation.snapshot_id

    app.selectbox(key="history_guidance_snapshot").select(None).run()
    headings = [item.value for item in _update(app).subheader]
    assert "Guidance" not in headings
    assert "Abweichung zu Erwartungen" in headings
    assert "Wichtigste Veränderungen" in headings
    assert "Research-Prüfpunkte" in headings
    assert not app.exception
