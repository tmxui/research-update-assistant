"""Prüfe den kompletten manuellen Analysefluss mit Streamlit AppTest."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from research_update_assistant import ui
from research_update_assistant.input_parsing import FINANCIAL_INPUT_GROUPS
from research_update_assistant.models import FinancialPeriod


def _new_app() -> AppTest:
    path = Path(__file__).resolve().parents[1] / "app.py"
    return AppTest.from_file(str(path), default_timeout=15).run()


def _example_app(count: int = 2) -> AppTest:
    app = _new_app()
    if count == 3:
        app.selectbox(key="period_count").select(3).run()
    app.button(key="load_examples").click().run()
    return app


def _overview(app: AppTest):
    return app.table[0].value.set_index("Kennzahl")


def _comparison(app: AppTest):
    return app.table[1].value.set_index("Kennzahl")


def _set_period(app: AppTest, index: int, period: FinancialPeriod) -> None:
    prefix = f"period_{index}_"
    app.text_input(key=prefix + "period_label").set_value(period.period_label)
    app.date_input(key=prefix + "period_end").set_value(period.period_end)
    app.number_input(key=prefix + "period_months").set_value(period.period_months)
    for _, definitions in FINANCIAL_INPUT_GROUPS:
        for name, _ in definitions:
            value = getattr(period, name)
            app.text_input(key=prefix + name).set_value("" if value is None else str(value))


def test_app_starts_with_german_content() -> None:
    app = _new_app()
    assert not app.exception
    assert app.title[0].value == "Research Update Assistant"
    assert app.markdown[0].value == "Strukturierte Auswertung von Unternehmensresultaten"
    assert app.info[0].value == (
        "Aktueller Entwicklungsstand: Phase 2 – Manuelle Finanzanalyse"
    )
    assert [item.value for item in app.subheader] == [
        "1. Unternehmensdaten", "2. Finanzperioden erfassen", "3. Daten prüfen",
    ]
    assert len(app.get("form")) == 1
    assert app.button(key="calculate_analysis").label == "Analyse berechnen"
    assert app.selectbox(key="period_count").value == 2
    assert app.selectbox(key="currency").value == "CHF"
    assert app.selectbox(key="scale").value == "million"
    assert not app.table


def test_example_prefill_does_not_compute_until_submit(monkeypatch) -> None:
    metrics = Mock(wraps=ui.calculate_period_metrics)
    comparisons = Mock(wraps=ui.compare_periods)
    monkeypatch.setattr(ui, "calculate_period_metrics", metrics)
    monkeypatch.setattr(ui, "compare_periods", comparisons)
    app = _example_app(3)
    assert metrics.call_count == comparisons.call_count == 0
    assert app.session_state["analysis_result"] is None
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert not app.error
    assert metrics.call_count == 3
    assert comparisons.call_count == 2


def test_three_year_examples_show_phase_one_results() -> None:
    app = _example_app(3)
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert not app.error
    overview = _overview(app)
    assert list(overview.columns) == ["FY2023", "FY2024", "FY2025"]
    assert overview.loc["Umsatz", "FY2025"] == "1'100"
    assert overview.loc["EBIT-Marge", "FY2025"] == "13.0 %"
    assert overview.loc["Berechneter Free Cashflow", "FY2025"] == "60"
    assert overview.loc["Berechnete Nettoverschuldung", "FY2025"] == "270"
    assert overview.loc["Berechnete Nettoverschuldung / EBITDA", "FY2025"] == "1.29x"
    comparison = _comparison(app)
    assert list(comparison.columns) == ["FY2024 vs FY2023", "FY2025 vs FY2024"]
    assert comparison.loc["Umsatzwachstum", "FY2024 vs FY2023"] == "+8.7 %"
    assert comparison.loc["Umsatzwachstum", "FY2025 vs FY2024"] == "+10.0 %"
    assert comparison.loc["EBIT-Margenänderung", "FY2025 vs FY2024"] == "-200 bps"
    assert comparison.loc["Berechnetes FCF-Wachstum", "FY2025 vs FY2024"] == "-40.0 %"


def test_two_period_examples_and_results_survive_rerun() -> None:
    app = _example_app()
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert list(_overview(app).columns) == ["FY2024", "FY2025"]
    assert list(_comparison(app).columns) == ["FY2025 vs FY2024"]
    result = app.session_state["analysis_result"]
    app.run()
    assert app.session_state["analysis_result"] is result
    assert len(app.table) == 2


def test_unordered_manual_periods_are_sorted(periods) -> None:
    app = _example_app(3)
    for index, label in enumerate(("FY2025", "FY2023", "FY2024")):
        _set_period(app, index, periods[label])
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert not app.error
    assert list(_overview(app).columns) == ["FY2023", "FY2024", "FY2025"]
    result = app.session_state["analysis_result"]
    assert all(period.source is None for period in result.history.periods)
    assert result.comparisons[1].ebit_margin_change_bps == pytest.approx(-200)


def test_swiss_number_and_negative_capex_reach_existing_engine() -> None:
    app = _example_app()
    app.text_input(key="period_1_revenue").set_value("1’100,5")
    app.text_input(key="period_1_capex").set_value("-80")
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    result = app.session_state["analysis_result"]
    assert result.history.periods[1].revenue == 1100.5
    assert result.history.periods[1].capex == -80
    assert result.metrics[1].normalized_capex == 80
    assert result.metrics[1].calculated_free_cash_flow == 60
    assert result.metrics[1].ebit_margin == pytest.approx(143 / 1100.5)


def test_missing_values_are_dashes_and_zero_is_zero() -> None:
    app = _example_app()
    app.text_input(key="period_1_ebitda").set_value("")
    app.text_input(key="period_0_revenue").set_value("0")
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert _overview(app).loc["EBITDA", "FY2025"] == "–"
    assert _overview(app).loc["Umsatz", "FY2024"] == "0"
    assert _comparison(app).loc["Umsatzwachstum", "FY2025 vs FY2024"] == "–"


def test_reported_and_calculated_rows_remain_separate() -> None:
    app = _example_app()
    app.text_input(key="period_1_reported_free_cash_flow").set_value("80")
    app.text_input(key="period_1_reported_net_debt").set_value("252")
    app.text_input(key="period_1_adjusted_ebit").set_value("165")
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    table = _overview(app)
    assert table.loc["Ausgewiesener Free Cashflow", "FY2025"] == "80"
    assert table.loc["Berechneter Free Cashflow", "FY2025"] == "60"
    assert table.loc["Ausgewiesene Nettoverschuldung", "FY2025"] == "252"
    assert table.loc["Berechnete Nettoverschuldung", "FY2025"] == "270"
    assert table.loc["Bereinigte EBIT-Marge", "FY2025"] == "15.0 %"
    assert table.loc["EBIT-Marge", "FY2025"] == "13.0 %"
    assert table.loc["Ausgewiesener Free Cashflow", "FY2024"] == "–"


@pytest.mark.parametrize("key, value, message", [
    ("company_name", " ", "Unternehmensnamen"),
    ("period_1_period_label", "", "Periodenbezeichnung"),
    ("period_1_period_label", "FY2024", "unterschiedlich"),
    ("period_1_ebit", "abc", "EBIT in FY2025"),
])
def test_form_errors_are_german_and_hide_previous_results(key, value, message) -> None:
    app = _example_app()
    app.button(key="calculate_analysis").click().run()
    app.text_input(key=key).set_value(value)
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert message in app.error[0].value
    assert app.session_state["analysis_result"] is None
    assert not app.table


def test_missing_date_has_a_user_facing_error() -> None:
    app = _example_app()
    app.date_input(key="period_1_period_end").set_value(None)
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert "Stichtag für FY2025" in app.error[0].value


def test_incompatible_duration_has_no_traceback() -> None:
    app = _example_app()
    app.number_input(key="period_1_period_months").set_value(6)
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert "Periodenlänge" in app.error[0].value
    assert not app.table


def test_half_years_have_no_artificial_leverage() -> None:
    app = _example_app()
    app.number_input(key="period_0_period_months").set_value(6)
    app.number_input(key="period_1_period_months").set_value(6)
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert not app.error
    assert _overview(app).loc["Berechnete Nettoverschuldung / EBITDA", "FY2025"] == "–"
    assert _comparison(app).loc["Berechnete Nettoverschuldung / EBITDA: Änderung", "FY2025 vs FY2024"] == "–"


def test_period_count_change_invalidates_results_and_preserves_hidden_inputs() -> None:
    app = _example_app(3)
    app.button(key="calculate_analysis").click().run()
    app.selectbox(key="period_count").select(2).run()
    assert app.session_state["analysis_result"] is None
    assert not app.table
    app.selectbox(key="period_count").select(3).run()
    assert app.text_input(key="period_2_period_label").value == "FY2025"
    assert app.text_input(key="period_2_revenue").value == "1100"
