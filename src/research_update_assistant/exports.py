"""Modellfreundliche In-Memory-Exporte bestätigter Finanzdaten.

Die Export-Schicht übernimmt ausschliesslich normalisierte Werte aus dem
HistoryWorkspace und bereits berechnete Kennzahlen aus der Finance-Engine.
Offene Konflikte bleiben leer; sämtliche Quell-Observations werden separat
ausgegeben.
"""

from __future__ import annotations

from collections.abc import Sequence
import csv
from dataclasses import fields
from io import BytesIO, StringIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .calculations import PeriodCompatibilityError, calculate_period_metrics, compare_periods
from .expectation_models import ExpectationSnapshot
from .guidance_models import GuidanceSnapshot, PERCENTAGE_GUIDANCE_METRICS
from .history_workspace import (
    HistoryWorkspace, MetricObservation, PeriodKey, PeriodMetricResolution, period_key_for,
)
from .models import CalculatedPeriodMetrics, FinancialPeriod, PeriodComparison
from .validation import EPS_METRICS, SUPPORTED_METRICS


FINANCIAL_METRICS = SUPPORTED_METRICS
CALCULATED_KPIS = tuple(field.name for field in fields(CalculatedPeriodMetrics))
GROWTH_KPIS = (
    "revenue_growth",
    "ebitda_growth",
    "ebit_growth",
    "net_income_growth",
    "operating_cash_flow_growth",
    "calculated_free_cash_flow_growth",
    "inventory_growth",
    "receivables_growth",
    "gross_debt_growth",
)
PERCENTAGE_KPIS = {
    "ebitda_margin",
    "adjusted_ebitda_margin",
    "ebit_margin",
    "adjusted_ebit_margin",
    "net_income_margin",
    "calculated_free_cash_flow_margin",
    "reported_free_cash_flow_margin",
    "operating_working_capital_to_revenue",
    "inventory_to_revenue",
    "receivables_to_revenue",
    "capex_to_revenue",
    *GROWTH_KPIS,
}
MULTIPLE_KPIS = {
    "operating_cash_flow_to_ebitda",
    "calculated_free_cash_flow_to_net_income",
    "calculated_net_debt_to_ebitda",
    "reported_net_debt_to_ebitda",
}

_HEADER_FILL = PatternFill(fill_type="solid", fgColor="D9E1F2")


class ExportValidationError(ValueError):
    """Die gewünschte Exportauswahl passt nicht zur bestätigten Historie."""


def _selected_periods(
    workspace: HistoryWorkspace,
    selected_period_keys: Sequence[PeriodKey] | None,
) -> tuple[FinancialPeriod, ...]:
    history = workspace.to_financial_history()
    available = {period_key_for(period): period for period in history.periods}
    if selected_period_keys is None:
        keys = tuple(sorted(available))
    else:
        keys = tuple(selected_period_keys)
        if not keys:
            raise ExportValidationError("Bitte mindestens eine Periode für den Export auswählen.")
        if len(keys) != len(set(keys)):
            raise ExportValidationError("Eine Exportperiode darf nicht doppelt ausgewählt werden.")
        missing = tuple(key for key in keys if key not in available)
        if missing:
            raise ExportValidationError(
                "Mindestens eine Exportperiode gehört nicht zur bestätigten Finanzhistorie."
            )
        keys = tuple(sorted(keys))
    return tuple(available[key] for key in keys)


def _period_comparisons(periods: Sequence[FinancialPeriod]) -> dict[PeriodKey, PeriodComparison]:
    comparisons: dict[PeriodKey, PeriodComparison] = {}
    for previous, current in zip(periods, periods[1:]):
        try:
            comparisons[period_key_for(current)] = compare_periods(current, previous)
        except PeriodCompatibilityError:
            continue
    return comparisons


def _style_table(
    sheet: Worksheet,
    *,
    freeze_panes: str,
    percent_rows: set[int] | None = None,
    multiple_rows: set[int] | None = None,
) -> None:
    sheet.freeze_panes = freeze_panes
    sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = _HEADER_FILL
    for row in percent_rows or set():
        for cell in sheet[row][1:]:
            if cell.value is not None:
                cell.number_format = "0.0%"
    for row in multiple_rows or set():
        for cell in sheet[row][1:]:
            if cell.value is not None:
                cell.number_format = '0.00"x"'
    for column in range(1, sheet.max_column + 1):
        values = (sheet.cell(row, column).value for row in range(1, sheet.max_row + 1))
        width = min(max((len(str(value)) for value in values if value is not None), default=8) + 2, 42)
        sheet.column_dimensions[get_column_letter(column)].width = width


def _write_matrix_sheet(
    workbook: Workbook,
    title: str,
    row_names: Sequence[str],
    periods: Sequence[FinancialPeriod],
    value_for,
    *,
    percentage_metrics: set[str] | None = None,
    multiple_metrics: set[str] | None = None,
) -> None:
    sheet = workbook.create_sheet(title)
    sheet.append(["metric", *(period.period_label for period in periods)])
    percent_rows: set[int] = set()
    multiple_rows: set[int] = set()
    for metric in row_names:
        sheet.append([metric, *(value_for(period, metric) for period in periods)])
        row = sheet.max_row
        if metric in (percentage_metrics or set()):
            percent_rows.add(row)
        if metric in (multiple_metrics or set()):
            multiple_rows.add(row)
    _style_table(
        sheet, freeze_panes="B2", percent_rows=percent_rows, multiple_rows=multiple_rows,
    )


def _active_observations(resolution: PeriodMetricResolution | None) -> tuple[MetricObservation, ...]:
    if resolution is None:
        return ()
    if resolution.status == "equivalent":
        return resolution.observations
    if resolution.status == "resolved":
        return tuple(
            item for item in resolution.observations
            if item.observation_id == resolution.selected_observation_id
        )
    return ()


def _observation_role(
    resolution: PeriodMetricResolution,
    observation: MetricObservation,
) -> str:
    if resolution.status == "equivalent":
        return "equivalent_source"
    if resolution.status in ("unresolved", "rounding_difference"):
        return "unresolved_alternative"
    if observation.observation_id == resolution.selected_observation_id:
        return "active"
    return "alternative"


def _matching_expectations(
    workspace: HistoryWorkspace,
    keys: set[PeriodKey],
    snapshots: Sequence[ExpectationSnapshot],
) -> tuple[ExpectationSnapshot, ...]:
    return tuple(sorted(
        (
            snapshot for snapshot in snapshots
            if snapshot.company.strip() == workspace.company_name
            and snapshot.currency == workspace.currency
            and snapshot.scale == workspace.scale
            and snapshot.target_period in keys
        ),
        key=lambda item: (item.target_period, item.as_of_date, item.snapshot_id),
    ))


def _matching_guidance(
    workspace: HistoryWorkspace,
    keys: set[PeriodKey],
    snapshots: Sequence[GuidanceSnapshot],
) -> tuple[GuidanceSnapshot, ...]:
    return tuple(sorted(
        (
            snapshot for snapshot in snapshots
            if snapshot.company.strip() == workspace.company_name
            and snapshot.currency == workspace.currency
            and snapshot.scale == workspace.scale
            and snapshot.target_period in keys
        ),
        key=lambda item: (item.target_period, item.as_of_date, item.snapshot_id),
    ))


def create_excel_export(
    workspace: HistoryWorkspace,
    *,
    selected_period_keys: Sequence[PeriodKey] | None = None,
    expectations: Sequence[ExpectationSnapshot] = (),
    guidance: Sequence[GuidanceSnapshot] = (),
) -> bytes:
    """Erzeuge ein schlichtes XLSX vollständig im Arbeitsspeicher."""
    periods = _selected_periods(workspace, selected_period_keys)
    keys = {period_key_for(period) for period in periods}
    comparisons = _period_comparisons(periods)
    calculated = {period_key_for(period): calculate_period_metrics(period) for period in periods}

    workbook = Workbook()
    overview = workbook.active
    overview.title = "Overview"
    overview.append(["field", "value"])
    overview.append(["company", workspace.company_name])
    overview.append(["currency", workspace.currency])
    overview.append(["scale", workspace.scale])
    overview.append(["exported_periods", " | ".join(period.period_label for period in periods)])
    conflicts = tuple(
        item for item in workspace.resolutions
        if item.period_key in keys and item.resolved_value is None
    )
    overview.append(["open_conflicts", len(conflicts)])
    overview.append([
        "note",
        "Unresolved conflict: affected Financials cells are blank; see Sources."
        if conflicts else "No unresolved conflicts in the exported periods.",
    ])
    labels = {period_key_for(period): period.period_label for period in periods}
    for conflict in conflicts:
        overview.append([
            "Unresolved conflict",
            f"{labels[conflict.period_key]} | {conflict.canonical_metric} | {conflict.reason}",
        ])
    _style_table(overview, freeze_panes="A2")

    _write_matrix_sheet(
        workbook, "Financials", FINANCIAL_METRICS, periods,
        lambda period, metric: getattr(period, metric),
    )

    def calculated_value(period: FinancialPeriod, metric: str) -> float | None:
        key = period_key_for(period)
        if metric in GROWTH_KPIS:
            comparison = comparisons.get(key)
            return None if comparison is None else getattr(comparison, metric)
        return getattr(calculated[key], metric)

    _write_matrix_sheet(
        workbook, "Calculated KPIs", (*GROWTH_KPIS, *CALCULATED_KPIS), periods,
        calculated_value, percentage_metrics=PERCENTAGE_KPIS, multiple_metrics=MULTIPLE_KPIS,
    )

    expectation_sheet = workbook.create_sheet("Expectations")
    expectation_sheet.append([
        "target_period", "target_period_end", "period_months", "as_of_date", "label",
        "source_type", "metric", "estimate", "currency", "scale", "notes",
    ])
    for snapshot in _matching_expectations(workspace, keys, expectations):
        for metric, estimate in snapshot.metric_expectations:
            if estimate is None:
                continue
            expectation_sheet.append([
                labels[snapshot.target_period], snapshot.target_period.period_end,
                snapshot.target_period.period_months, snapshot.as_of_date, snapshot.label,
                snapshot.source_type, metric, estimate, snapshot.currency, snapshot.scale,
                snapshot.notes,
            ])
            if metric in PERCENTAGE_KPIS:
                expectation_sheet.cell(expectation_sheet.max_row, 8).number_format = "0.0%"
    _style_table(expectation_sheet, freeze_panes="A2")

    guidance_sheet = workbook.create_sheet("Guidance")
    guidance_sheet.append([
        "target_period", "target_period_end", "period_months", "as_of_date", "label",
        "source_type", "metric", "guidance_type", "exact_value", "minimum", "maximum",
        "qualitative_value", "currency", "scale", "source_document", "source_page", "notes",
    ])
    for snapshot in _matching_guidance(workspace, keys, guidance):
        for item in snapshot.guidance_items:
            guidance_sheet.append([
                labels[snapshot.target_period], snapshot.target_period.period_end,
                snapshot.target_period.period_months, snapshot.as_of_date, snapshot.label,
                snapshot.source_type, item.canonical_metric, item.guidance_type,
                item.exact_value, item.minimum, item.maximum, item.qualitative_direction,
                snapshot.currency, snapshot.scale, snapshot.source_document,
                snapshot.source_page, snapshot.notes,
            ])
            if item.canonical_metric in PERCENTAGE_GUIDANCE_METRICS:
                for column in (9, 10, 11):
                    guidance_sheet.cell(guidance_sheet.max_row, column).number_format = "0.0%"
    _style_table(guidance_sheet, freeze_panes="A2")

    sources_sheet = workbook.create_sheet("Sources")
    sources_sheet.append([
        "period", "period_end", "period_months", "canonical_metric",
        "active_resolved_value", "observation_value", "source_document", "source_page",
        "reported_label", "extraction_method", "resolution_status", "observation_role",
        "confirmation_status", "report_id", "observation_id", "source_snippet",
    ])
    for resolution in sorted(
        (item for item in workspace.resolutions if item.period_key in keys),
        key=lambda item: (item.period_key, FINANCIAL_METRICS.index(item.canonical_metric)),
    ):
        for observation in resolution.observations:
            confirmed = observation.confirmed
            sources_sheet.append([
                labels[resolution.period_key], resolution.period_key.period_end,
                resolution.period_key.period_months, resolution.canonical_metric,
                resolution.resolved_value, observation.value, confirmed.source_document,
                confirmed.page_number, confirmed.reported_label, confirmed.extraction_method,
                resolution.status, _observation_role(resolution, observation), confirmed.status,
                observation.report_id, observation.observation_id, confirmed.source_snippet,
            ])
    _style_table(sources_sheet, freeze_panes="A2")

    # Entferne nur das nie verwendete Standardsheet, falls seine Umbenennung
    # durch eine zukünftige openpyxl-Version anders behandelt würde.
    for sheet in tuple(workbook.worksheets):
        if sheet.title == "Sheet" and sheet.max_row == 1 and sheet.max_column == 1:
            workbook.remove(sheet)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def create_financial_history_csv(
    workspace: HistoryWorkspace,
    *,
    selected_period_keys: Sequence[PeriodKey] | None = None,
) -> bytes:
    """Erzeuge eine UTF-8-CSV-Historie im Long-Format ohne eigene Berechnungen."""
    periods = _selected_periods(workspace, selected_period_keys)
    resolutions = {
        (item.period_key, item.canonical_metric): item for item in workspace.resolutions
    }
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([
        "company", "period", "period_end", "period_months", "metric", "value",
        "currency", "scale", "source_document", "source_page",
    ])
    for period in periods:
        key = period_key_for(period)
        for metric in FINANCIAL_METRICS:
            resolution = resolutions.get((key, metric))
            active = _active_observations(resolution)
            documents = " | ".join(dict.fromkeys(
                item.source_document for item in active if item.source_document
            ))
            pages = " | ".join(dict.fromkeys(
                str(item.page_number) for item in active if item.page_number is not None
            ))
            writer.writerow([
                period.company_name, period.period_label, period.period_end.isoformat(),
                period.period_months, metric, getattr(period, metric), period.currency,
                "unit" if metric in EPS_METRICS else period.scale, documents, pages,
            ])
    return output.getvalue().encode("utf-8-sig")
