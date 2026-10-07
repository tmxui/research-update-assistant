"""Streamlit-Integration des Downloads ohne dauerhafte Exportdateien."""

from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

from phase6_samples import make_confirmed_report
from research_update_assistant.history_workspace import HistoryWorkspace, PeriodKey


def _token(year: int) -> str:
    return str(PeriodKey(date(year, 12, 31), 12))


def _export_app() -> AppTest:
    history, observations = make_confirmed_report(2025)
    workspace = HistoryWorkspace("Synthetic Industrial AG", "CHF", "million").add_report(
        history, observations, "synthetic_report_2025.pdf",
    )
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


def test_history_export_buttons_and_existing_analysis_render_together() -> None:
    app = _export_app()
    assert app.download_button(key="history_export_excel").label == "Excel herunterladen"
    assert app.download_button(key="history_export_csv").label == "CSV herunterladen"
    assert app.download_button(key="history_export_excel").proto.url
    assert app.download_button(key="history_export_csv").proto.url
    assert any(item.value == "Wichtigste Veränderungen" for item in app.subheader)
    assert any(item.value == "Research-Prüfpunkte" for item in app.subheader)
    assert not app.error


def test_export_can_follow_selected_trend_periods() -> None:
    app = _export_app()
    app.radio(key="history_export_scope").set_value("Aktuell ausgewählte Trendperioden").run()
    assert any(
        "Exportierte Perioden: FY2024 / FY2025" in item.value
        for item in app.caption
    )
    assert len(app.download_button) == 2
    assert not app.exception
