"""Streamlit-Integration für Erfassung, Auswahl und sauberen Fallback."""

from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

from phase6_samples import make_confirmed_report
from research_update_assistant.expectation_models import ExpectationSnapshot
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


def _expectation_table(app: AppTest):
    return next(
        item.value.set_index("Kennzahl")
        for item in _update(app).dataframe
        if "Estimate" in item.value.columns and "Surprise" in item.value.columns
    )


def test_no_snapshot_keeps_phase_seven_results_without_expectation_block() -> None:
    app = _history_app()
    update = _update(app)
    assert "Abweichung zu Erwartungen" not in [item.value for item in update.subheader]
    assert "Wichtigste Veränderungen" in [item.value for item in update.subheader]
    assert "Research-Prüfpunkte" in [item.value for item in update.subheader]
    assert not app.exception


def test_manual_snapshot_is_saved_selected_and_can_be_disabled() -> None:
    app = _history_app()
    changes_before = tuple(item.value for item in app.get_by_key("history_update_changes").text)
    flags_before = tuple(flag.rule_id for flag in app.session_state["history_result"].research_flags[0])

    app.selectbox(key="expectation_target_period").select(
        "Synthetic Industrial AG|2025-12-31|12|CHF|million"
    )
    app.text_input(key="expectation_label").set_value("Illustrative Testerwartungen")
    app.text_input(key="expectation_value_revenue").set_value("1080")
    app.text_input(key="expectation_value_ebit").set_value("150")
    app.text_input(key="expectation_value_ebit_margin").set_value("14")
    app.button(key="expectation_save").click().run()

    assert not app.exception and not app.error
    snapshots = app.session_state["expectation_snapshots"]
    assert len(snapshots) == 1
    assert snapshots[0].get("revenue") == 1080
    assert snapshots[0].get("ebit_margin") == 0.14
    assert app.selectbox(key="history_expectation_snapshot").value == snapshots[0].snapshot_id
    table = _expectation_table(app)
    assert table.loc["Umsatz", "Actual"] == "CHF 1'100 Mio."
    assert table.loc["Umsatz", "Estimate"] == "CHF 1'080 Mio."
    assert table.loc["Umsatz", "Surprise"] == "+1.9 %"
    assert table.loc["EBIT", "Surprise"] == "-4.7 %"
    assert table.loc["EBIT-Marge", "Surprise"] == "-100 bps"
    assert "Abweichung zu Erwartungen" in [item.value for item in _update(app).subheader]

    app.selectbox(key="history_expectation_snapshot").select(None).run()
    assert "Abweichung zu Erwartungen" not in [item.value for item in _update(app).subheader]
    assert tuple(item.value for item in app.get_by_key("history_update_changes").text) == changes_before
    assert tuple(flag.rule_id for flag in app.session_state["history_result"].research_flags[0]) == flags_before
    assert not app.exception


def test_multiple_snapshots_require_one_explicit_active_choice() -> None:
    app = _history_app()
    common = dict(
        company="Synthetic Industrial AG",
        target_period=PeriodKey(date(2025, 12, 31), 12),
        as_of_date=date(2025, 10, 1),
        source_type="internal",
        currency="CHF",
        scale="million",
    )
    first = ExpectationSnapshot(label="Snapshot A", metric_expectations={"revenue": 1075}, **common)
    second = ExpectationSnapshot(label="Snapshot B", metric_expectations={"revenue": 1080}, **common)
    app.session_state["expectation_snapshots"] = (first, second)
    app.run()

    selector = app.selectbox(key="history_expectation_snapshot")
    assert selector.value is None
    selector.select(second.snapshot_id).run()
    table = _expectation_table(app)
    assert table.loc["Umsatz", "Estimate"] == "CHF 1'080 Mio."
    assert not app.exception
