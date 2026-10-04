"""Prüfe den kompletten manuellen Analysefluss mit Streamlit AppTest."""

from pathlib import Path
from dataclasses import replace
from datetime import date
import re
import json
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from research_update_assistant import ui
from research_update_assistant.flag_config import FlagConfigError, RuleThresholds, load_flag_rules
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
        "Aktueller Entwicklungsstand: Phase 5A – PDF-Dokumentanalyse"
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
    assert app.metric[0].value == "1'100"
    assert app.metric[1].value == "13.0 %"
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


def test_research_flags_appear_only_after_analysis_and_show_latest_pair_first() -> None:
    app = _example_app(3)
    assert "Research-Prüfpunkte" not in [element.value for element in app.header]
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert not app.error
    assert [element.value for element in app.header] == [
        "Geschäftsbericht einlesen", "Research-Prüfpunkte", "Kennzahlenüberblick", "Finanzübersicht", "Trendanalyse", "Periodenvergleich",
    ]
    assert [element.value for element in app.subheader][-2:] == ["FY2025 vs FY2024", "FY2024 vs FY2023"]
    result = app.session_state["analysis_result"]
    assert [(flag.rule_id, flag.severity) for flag in result.research_flags[1]] == [
        ("ebit_margin_decline", "red"), ("free_cash_flow_decline", "red"),
        ("ebit_growth_lag", "red"), ("inventory_growth_excess", "yellow"),
        ("receivables_growth_excess", "yellow"),
    ]
    assert [(flag.rule_id, flag.severity) for flag in result.research_flags[0]] == [("ebit_growth_lag", "yellow")]
    assert any(":red-badge[Deutliche Veränderung]" in element.value for element in app.markdown)
    assert any(":yellow-badge[Prüfen]" in element.value for element in app.markdown)


def test_flag_texts_explain_numbers_and_display_configured_thresholds() -> None:
    app = _example_app()
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    texts = "\n".join(element.value for element in app.text)
    assert "15,0 % auf 13,0 %" in texts
    assert "200 Basispunkte" in texts
    assert "CHF 100 Mio. auf CHF 60 Mio." in texts
    assert "40,0 %" in texts
    assert "26,7 %" in texts and "+16,7 Prozentpunkte" in texts
    assert "25,0 %" in texts and "+15,0 Prozentpunkte" in texts
    captions = "\n".join(element.value for element in app.caption)
    assert "ebit_margin_decline · Auslöseschwelle: ≤ -200 bps" in captions
    assert "free_cash_flow_decline · Auslöseschwelle: ≤ -40,0 %" in captions


def test_research_text_has_no_investment_recommendation_or_overall_score() -> None:
    app = _example_app(3)
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    text = "\n".join(
        element.value for elements in (app.text, app.markdown, app.caption, app.header, app.subheader)
        for element in elements
    )
    assert not re.search(r"\b(kaufen|verkaufen|buy|sell|hold|bullish|bearish|attraktiv|unattraktiv|score)\b", text, re.I)


def test_green_observations_are_displayed_for_measured_improvements(periods) -> None:
    app = _example_app()
    _set_period(app, 0, periods["FY2024"])
    current = replace(
        periods["FY2024"], period_label="FY2025", period_end=date(2025, 12, 31),
        ebit=160, operating_cash_flow=180, gross_debt=200,
    )
    _set_period(app, 1, current)
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert not app.error
    flags = app.session_state["analysis_result"].research_flags[0]
    assert {flag.rule_id for flag in flags} == {"ebit_margin_improvement", "free_cash_flow_improvement", "leverage_decrease"}
    assert all(flag.severity == "green" for flag in flags)
    assert any(":green-badge[Verbesserung]" in element.value for element in app.markdown)


def test_missing_financial_values_are_not_classified_as_green_or_red() -> None:
    app = _example_app()
    for index in range(2):
        for _, definitions in FINANCIAL_INPUT_GROUPS:
            for name, _ in definitions:
                app.text_input(key=f"period_{index}_{name}").set_value("")
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert not app.error
    assert app.session_state["analysis_result"].research_flags == ((),)
    assert any("keine Regel ausgelöst" in element.value for element in app.caption)
    assert not any("-badge[" in element.value for element in app.markdown)
    assert all(metric.value == "–" for metric in app.metric)
    assert len(app.get("plotly_chart")) == 7
    for element in app.get("plotly_chart"):
        figure = json.loads(element.proto.spec)
        assert "Keine verfügbaren Werte" in figure["layout"]["annotations"][0]["text"]


def test_config_error_preserves_financial_tables_without_silent_fallback(monkeypatch) -> None:
    def invalid_configuration():
        raise FlagConfigError("Research-Konfiguration fehlt.")

    monkeypatch.setattr(ui, "load_flag_rules", invalid_configuration)
    app = _example_app()
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert len(app.table) == 2
    assert _overview(app).loc["Berechneter Free Cashflow", "FY2025"] == "60"
    assert "Research-Konfiguration fehlt" in app.error[0].value
    assert app.session_state["analysis_result"].research_flags == ()
    assert not app.text


def test_config_is_reloaded_only_when_analysis_is_submitted(monkeypatch) -> None:
    original = load_flag_rules()
    modified = replace(original, ebit_margin_decline=RuleThresholds(-100, -250))
    loader = Mock(return_value=original)
    monkeypatch.setattr(ui, "load_flag_rules", loader)
    app = _example_app()
    assert loader.call_count == 0
    app.button(key="calculate_analysis").click().run()
    assert loader.call_count == 1
    loader.return_value = modified
    app.run()
    assert loader.call_count == 1
    flags = {flag.rule_id: flag for flag in app.session_state["analysis_result"].research_flags[0]}
    assert flags["ebit_margin_decline"].severity == "red"
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert loader.call_count == 2
    flags = {flag.rule_id: flag for flag in app.session_state["analysis_result"].research_flags[0]}
    assert flags["ebit_margin_decline"].severity == "yellow"


def _chart_specs(app: AppTest) -> dict:
    figures = [json.loads(element.proto.spec) for element in app.get("plotly_chart")]
    return {figure["layout"]["title"]["text"]: figure for figure in figures}


@pytest.mark.parametrize("count", [2, 3])
def test_dashboard_has_five_latest_metrics_with_neutral_deltas(count) -> None:
    app = _example_app(count)
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert not app.error
    assert [(metric.label, metric.value, metric.delta) for metric in app.metric] == [
        ("Umsatz", "1'100", "+10.0 %"), ("EBIT-Marge", "13.0 %", "-200 bps"),
        ("Berechneter FCF", "60", "-40.0 %"), ("Nettoverschuldung", "270", ""),
        ("Net Debt / EBITDA", "1.29x", "+0.29x"),
    ]
    assert all(metric.proto.color == metric.proto.GRAY for metric in app.metric)
    assert all(metric.proto.direction == metric.proto.NONE for metric in app.metric)
    assert any("Geldbeträge in CHF Mio." in caption.value for caption in app.caption)
    assert [tab.label for tab in app.tabs][-4:] == [
        "Ergebnis & Margen", "Cashflow", "Bilanz & Verschuldung", "Working Capital",
    ]


def test_dashboard_displays_expected_chart_data_after_analysis() -> None:
    app = _example_app(3)
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    figures = _chart_specs(app)
    assert set(figures) == {
        "Umsatzentwicklung", "Ergebnisentwicklung", "Margenentwicklung", "Cashflow-Entwicklung",
        "Nettoverschuldung", "Net Debt / EBITDA", "Working Capital im Verhältnis zum Umsatz",
    }
    assert figures["Umsatzentwicklung"]["data"][0]["x"] == ["FY2023", "FY2024", "FY2025"]
    assert figures["Umsatzentwicklung"]["data"][0]["y"] == [920, 1000, 1100]
    cashflow = {trace["name"]: trace for trace in figures["Cashflow-Entwicklung"]["data"]}
    assert cashflow["Berechneter Free Cashflow"]["y"] == [95, 100, 60]
    assert figures["Nettoverschuldung"]["data"][0]["y"] == [185, 200, 270]
    assert all(element.proto.alt for element in app.get("plotly_chart"))


def test_dashboard_survives_switch_between_two_and_three_periods() -> None:
    app = _example_app()
    for count in (2, 3, 2):
        if app.selectbox(key="period_count").value != count:
            app.selectbox(key="period_count").select(count).run()
            assert not app.exception
            assert not app.metric
            assert not app.get("plotly_chart")
            app.button(key="load_examples").click().run()
        app.button(key="calculate_analysis").click().run()
        assert not app.exception
        assert not app.error
        labels = _chart_specs(app)["Umsatzentwicklung"]["data"][0]["x"]
        assert labels == (["FY2023", "FY2024", "FY2025"] if count == 3 else ["FY2024", "FY2025"])


def test_dashboard_missing_fcf_and_leverage_do_not_crash_or_become_zero() -> None:
    app = _example_app(3)
    app.text_input(key="period_2_ebitda").set_value("")
    app.text_input(key="period_2_capex").set_value("")
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert not app.error
    assert app.metric[2].value == "–"
    assert app.metric[4].value == "–"
    figures = _chart_specs(app)
    margins = {trace["name"]: trace for trace in figures["Margenentwicklung"]["data"]}
    assert margins["EBITDA-Marge"]["y"][-1] is None
    assert margins["EBITDA-Marge"]["connectgaps"] is False
    cashflow = {trace["name"]: trace for trace in figures["Cashflow-Entwicklung"]["data"]}
    assert cashflow["Berechneter Free Cashflow"]["y"][-1] is None
    assert figures["Net Debt / EBITDA"]["data"][0]["x"] == ["FY2023", "FY2024"]


def test_dashboard_zero_changes_remain_neutral(periods) -> None:
    app = _example_app()
    _set_period(app, 0, periods["FY2024"])
    _set_period(app, 1, replace(periods["FY2024"], period_label="FY2025", period_end=date(2025, 12, 31)))
    app.button(key="calculate_analysis").click().run()
    assert not app.exception
    assert [metric.delta for metric in app.metric] == ["0", "0", "0", "", "0"]
    assert all(metric.proto.color == metric.proto.GRAY for metric in app.metric)
    assert all(metric.proto.direction == metric.proto.NONE for metric in app.metric)
