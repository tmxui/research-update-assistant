"""Synthetische mehrjährige Reports mit einer gezielten FY2024-EBIT-Abweichung.

Keine externen Dateien oder Unternehmensdaten. Die PDFs entstehen vollständig
im Arbeitsspeicher; die bestätigten Testbeobachtungen behalten dieselben Quellen.
"""

from datetime import date

import pymupdf

from research_update_assistant.history import FinancialHistory
from research_update_assistant.validation import (
    ConfirmedMetricObservation, ConfirmedPeriodMetadata, create_confirmed_history,
)


_PERIOD_VALUES = {
    2021: dict(revenue=800, ebitda=160, ebit=120, net_income=80,
               operating_cash_flow=150, capex=50, cash=75, gross_debt=240,
               inventory=120, receivables=95, payables=80),
    2022: dict(revenue=860, ebitda=175, ebit=135, net_income=88,
               operating_cash_flow=None, capex=50, cash=90, gross_debt=260,
               inventory=130, receivables=100, payables=90),
    2023: dict(revenue=920, ebitda=190, ebit=145, net_income=95,
               operating_cash_flow=165, capex=55, cash=95, gross_debt=280,
               inventory=140, receivables=110, payables=95),
    2024: dict(revenue=1000, ebitda=200, ebit=150, net_income=100,
               operating_cash_flow=160, capex=60, cash=100, gross_debt=300,
               inventory=150, receivables=120, payables=100),
    2025: dict(revenue=1100, ebitda=210, ebit=143, net_income=92,
               operating_cash_flow=140, capex=80, cash=90, gross_debt=360,
               inventory=190, receivables=150, payables=110),
}
_STATEMENTS = (
    ("Konsolidierte Erfolgsrechnung", (
        ("revenue", "Nettoumsatz"), ("ebitda", "Operativer Cashflow (EBITDA)"),
        ("ebit", "Betriebsergebnis (EBIT)"), ("net_income", "Reingewinn"),
    )),
    ("Konsolidierte Bilanz", (
        ("cash", "Flüssige Mittel"), ("gross_debt", "Finanzverbindlichkeiten"),
        ("inventory", "Vorräte"), ("receivables", "Forderungen aus Lieferungen und Leistungen"),
        ("payables", "Verbindlichkeiten aus Lieferungen und Leistungen"),
    )),
    ("Konsolidierte Geldflussrechnung", (
        ("operating_cash_flow", "Geldfluss aus Geschäftstätigkeit"),
        ("capex", "Investitionen in Sachanlagen"),
    )),
)
_SCALE_LABELS = {"unit": "Einheiten", "thousand": "Tausend", "million": "Millionen", "billion": "Milliarden"}


def report_file_name(report_year: int) -> str:
    """Ein stabiler synthetischer Dateiname je Bericht, ohne absolute Pfade."""
    return f"annual_report_{report_year}.pdf"


def report_values(report_year: int) -> dict[int, dict[str, float | None]]:
    """Frische unabhängige Datensätze; nur FY2024 EBIT unterscheidet sich."""
    if report_year not in (2022, 2023, 2024, 2025):
        raise ValueError("Die synthetischen Berichte unterstützen 2022 bis 2025.")
    values = {year: dict(_PERIOD_VALUES[year]) for year in (report_year, report_year - 1)}
    if report_year == 2025:
        values[2024]["ebit"] = 148
    return values


def make_confirmed_report(
    report_year: int, *, company_name: str = "Synthetic Industrial AG",
    currency: str = "CHF", scale: str = "million",
) -> tuple[FinancialHistory, tuple[ConfirmedMetricObservation, ...]]:
    """Bestätigte Reportdaten zum direkten Testen des History-UI-Adapters."""
    values = report_values(report_year)
    observations = []
    for page_number, (_, definitions) in enumerate(_STATEMENTS, 1):
        for metric, label in definitions:
            for year, period_values in values.items():
                value = period_values[metric]
                if value is None:
                    continue
                raw = f"({value})" if metric == "capex" else str(value)
                normalized = -value if metric == "capex" else value
                observations.append(ConfirmedMetricObservation(
                    canonical_metric=metric, period_label=f"FY{year}", confirmed_value=normalized,
                    currency=currency, scale=scale, status="confirmed",
                    original_extracted_value=normalized, original_raw_value=raw,
                    original_canonical_metric=metric, original_period_label=f"FY{year}",
                    original_currency=currency, original_scale=scale,
                    candidate_id=f"report-{report_year}-{metric}",
                    source_document=report_file_name(report_year), page_number=page_number,
                    reported_label=label, source_snippet=f"{label} | {year} | {raw}",
                    extraction_method="pymupdf_layout", bbox=(45, 130, 605, 145),
                ))
    periods = tuple(ConfirmedPeriodMetadata(f"FY{year}", date(year, 12, 31), 12) for year in values)
    confirmed = tuple(observations)
    history = create_confirmed_history(company_name, currency, scale, periods, confirmed)
    return history, confirmed


def make_history_pdf(
    report_year: int, *, company_name: str = "Synthetic Industrial AG",
    currency: str = "CHF", scale: str = "million",
) -> bytes:
    """Drei maschinenlesbare Statements mit sicheren rechtsbündigen Jahrsspalten."""
    values = report_values(report_year)
    with pymupdf.open() as pdf:
        font = pymupdf.Font("cjk")
        for title, definitions in _STATEMENTS:
            page = pdf.new_page(width=650, height=840)
            page.insert_font(fontname="history_test", fontbuffer=font.buffer)

            def text(x: float, y: float, value: str, size: float = 10) -> None:
                page.insert_text((x, y), value, fontname="history_test", fontsize=size)

            def right_text(x: float, y: float, value: str) -> None:
                text(x - font.text_length(value, fontsize=10), y, value)

            text(45, 55, title, 15)
            text(45, 85, f"{company_name} – in {currency} {_SCALE_LABELS[scale]}")
            text(45, 118, "Bezeichnung")
            text(365, 118, "Anhang")
            for column, year in enumerate(values):
                header = f"31.12.{year}" if title == "Konsolidierte Bilanz" else str(year)
                right_text((490, 605)[column], 118, header)
            for row_index, (metric, label) in enumerate(definitions):
                y = 150 + row_index * 32
                text(45, y, label)
                text(370, y, str(row_index + 3))
                for column, (_, period_values) in enumerate(values.items()):
                    number = period_values[metric]
                    raw = "–" if number is None else f"({number})" if metric == "capex" else str(number)
                    right_text((490, 605)[column], y, raw)
        pdf.set_metadata({"title": f"Synthetischer Geschäftsbericht {report_year}", "author": "Research Update Assistant Tests"})
        pdf.subset_fonts()
        return pdf.tobytes(garbage=4, deflate=True)
