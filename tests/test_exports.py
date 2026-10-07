"""In-Memory-XLSX/CSV-Export der bestätigten Finanzhistorie."""

from dataclasses import replace
from datetime import date
from io import BytesIO, StringIO
import csv

import pytest
from openpyxl import load_workbook

from phase6_samples import make_confirmed_report
from research_update_assistant.expectation_models import ExpectationSnapshot
from research_update_assistant.exports import create_excel_export, create_financial_history_csv
from research_update_assistant.guidance_models import GuidanceItem, GuidanceSnapshot
from research_update_assistant.history_workspace import HistoryWorkspace, PeriodKey


def _workspace(*report_years: int) -> HistoryWorkspace:
    workspace = HistoryWorkspace("Synthetic Industrial AG", "CHF", "million")
    for report_year in report_years:
        history, observations = make_confirmed_report(report_year)
        workspace = workspace.add_report(
            history, observations, f"synthetic_report_{report_year}.pdf"
        )
    return workspace


def _sheet_matrix(sheet) -> dict[str, dict[str, float | None]]:
    periods = [cell.value for cell in sheet[1][1:]]
    return {
        row[0].value: {period: cell.value for period, cell in zip(periods, row[1:])}
        for row in sheet.iter_rows(min_row=2)
    }


def test_xlsx_opens_with_expected_sheets_and_two_sorted_periods() -> None:
    workspace = _workspace(2025)
    data = create_excel_export(workspace)
    workbook = load_workbook(BytesIO(data), data_only=False)

    assert workbook.sheetnames == [
        "Overview", "Financials", "Calculated KPIs", "Expectations", "Guidance", "Sources",
    ]
    assert [cell.value for cell in workbook["Financials"][1]] == ["metric", "FY2024", "FY2025"]
    financials = _sheet_matrix(workbook["Financials"])
    assert financials["revenue"] == {"FY2024": 1000, "FY2025": 1100}
    assert isinstance(workbook["Financials"]["B2"].value, (int, float))
    assert workbook["Financials"].freeze_panes == "B2"


def test_five_period_export_keeps_missing_values_blank_and_numbers_numeric() -> None:
    workspace = _workspace(2025, 2024, 2023, 2022)
    workbook = load_workbook(BytesIO(create_excel_export(workspace)))
    assert [cell.value for cell in workbook["Financials"][1][1:]] == [
        "FY2021", "FY2022", "FY2023", "FY2024", "FY2025",
    ]
    financials = _sheet_matrix(workbook["Financials"])
    assert financials["operating_cash_flow"]["FY2022"] is None
    assert financials["operating_cash_flow"]["FY2021"] == 150
    assert isinstance(financials["revenue"]["FY2025"], (int, float))
    kpis = _sheet_matrix(workbook["Calculated KPIs"])
    assert kpis["revenue_growth"]["FY2025"] == pytest.approx(0.1)
    assert kpis["revenue_growth"]["FY2021"] is None


def test_unresolved_conflict_is_blank_but_all_sources_remain_visible() -> None:
    workspace = _workspace(2025, 2024)
    workbook = load_workbook(BytesIO(create_excel_export(workspace)))
    financials = _sheet_matrix(workbook["Financials"])
    assert financials["ebit"]["FY2024"] is None

    overview = list(workbook["Overview"].values)
    assert ("open_conflicts", 1) in overview
    assert any(row[0] == "Unresolved conflict" and "FY2024 | ebit" in row[1] for row in overview)

    source_rows = list(workbook["Sources"].values)
    header = source_rows[0]
    records = [dict(zip(header, row)) for row in source_rows[1:]]
    conflict_rows = [
        row for row in records if row["period"] == "FY2024" and row["canonical_metric"] == "ebit"
    ]
    assert {row["observation_value"] for row in conflict_rows} == {148, 150}
    assert {row["resolution_status"] for row in conflict_rows} == {"unresolved"}
    assert {row["observation_role"] for row in conflict_rows} == {"unresolved_alternative"}
    assert {row["active_resolved_value"] for row in conflict_rows} == {None}


def test_reported_and_calculated_metrics_stay_separate(periods) -> None:
    period_2024 = replace(
        periods["FY2024"], reported_free_cash_flow=97, reported_net_debt=205,
    )
    period_2025 = replace(
        periods["FY2025"], reported_free_cash_flow=58, reported_net_debt=275,
    )
    workspace = HistoryWorkspace("Synthetic Industrial AG", "CHF", "million").add_periods(
        (period_2024, period_2025), "manual_confirmed_periods",
    )
    workbook = load_workbook(BytesIO(create_excel_export(workspace)))
    financials = _sheet_matrix(workbook["Financials"])
    kpis = _sheet_matrix(workbook["Calculated KPIs"])

    assert financials["reported_free_cash_flow"]["FY2025"] == 58
    assert kpis["calculated_free_cash_flow"]["FY2025"] == 60
    assert financials["reported_net_debt"]["FY2025"] == 275
    assert kpis["calculated_net_debt"]["FY2025"] == 270


def test_expectations_and_guidance_keep_snapshots_and_range_boundaries() -> None:
    workspace = _workspace(2025)
    target = PeriodKey(date(2025, 12, 31), 12)
    expectations = (
        ExpectationSnapshot(
            "Synthetic Industrial AG", target, date(2025, 2, 1), "Consensus vor FY2025",
            "consensus", "CHF", "million", {"revenue": 1080, "ebit": None},
            notes="Synthetische Erwartung",
        ),
    )
    guidance = (
        GuidanceSnapshot(
            "Synthetic Industrial AG", target, date(2025, 3, 1), "FY2025 Guidance",
            "annual_report", "CHF", "million",
            (GuidanceItem("revenue_growth", "range", minimum=0.04, maximum=0.06),),
            source_document="synthetic_report.pdf", source_page=4,
            notes="Synthetische Guidance",
        ),
    )
    workbook = load_workbook(BytesIO(create_excel_export(
        workspace, expectations=expectations, guidance=guidance,
    )))

    expectation_rows = list(workbook["Expectations"].values)
    assert len(expectation_rows) == 2
    assert expectation_rows[1][0].startswith("FY2025")
    assert expectation_rows[1][1].date() == date(2025, 12, 31)
    assert expectation_rows[1][3].date() == date(2025, 2, 1)
    assert expectation_rows[1][2:3] + expectation_rows[1][4:8] == (
        12,
        "Consensus vor FY2025", "consensus", "revenue", 1080,
    )
    guidance_rows = list(workbook["Guidance"].values)
    header = guidance_rows[0]
    record = dict(zip(header, guidance_rows[1]))
    assert record["guidance_type"] == "range"
    assert record["exact_value"] is None
    assert record["minimum"] == 0.04
    assert record["maximum"] == 0.06


def test_csv_is_tidy_sorted_and_contains_active_provenance() -> None:
    workspace = _workspace(2025)
    csv_bytes = create_financial_history_csv(
        workspace,
        selected_period_keys=(PeriodKey(date(2025, 12, 31), 12),),
    )
    rows = list(csv.DictReader(StringIO(csv_bytes.decode("utf-8-sig"))))
    assert rows[0].keys() == {
        "company", "period", "period_end", "period_months", "metric", "value",
        "currency", "scale", "source_document", "source_page",
    }
    revenue = next(row for row in rows if row["metric"] == "revenue")
    assert revenue == {
        "company": "Synthetic Industrial AG", "period": "FY2025",
        "period_end": "2025-12-31", "period_months": "12", "metric": "revenue",
        "value": "1100", "currency": "CHF", "scale": "million",
        "source_document": "annual_report_2025.pdf", "source_page": "1",
    }
    missing = next(row for row in rows if row["metric"] == "reported_free_cash_flow")
    assert missing["value"] == ""


def test_two_period_selection_from_five_period_history() -> None:
    workspace = _workspace(2025, 2024, 2023, 2022)
    selected = (PeriodKey(date(2024, 12, 31), 12), PeriodKey(date(2025, 12, 31), 12))
    workbook = load_workbook(BytesIO(create_excel_export(
        workspace, selected_period_keys=selected,
    )))
    assert [cell.value for cell in workbook["Financials"][1][1:]] == ["FY2024", "FY2025"]
