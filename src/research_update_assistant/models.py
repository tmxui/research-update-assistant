"""Periodenwerte, optionale Herkunft und Berechnungsergebnisse.

Ein Datensatz beschreibt eine Periode aus einer Quelle, nicht ein Dokument.
Mehrere Quellen dürfen unterschiedliche Datensätze derselben Periode liefern.
Fehlende Finanzwerte bleiben None; Verhältnisse werden als Dezimalzahlen gespeichert.
"""

from dataclasses import dataclass, fields
from datetime import date
from math import isfinite


@dataclass(frozen=True)
class SourceMetadata:
    """Optionale Herkunft eines Periodendatensatzes, ohne Einfluss auf Formeln.

Die Metadaten gelten zunächst für den gesamten Datensatz. Eine spätere
Extraktionsschicht kann zusätzlich die Herkunft einzelner Zahlen abbilden.
None bedeutet bei den Statusfeldern, dass der Status unbekannt ist.
"""

    source_document: str | None = None
    source_document_period: str | None = None
    reported_as_comparative: bool | None = None
    source_page: int | None = None
    source_label: str | None = None
    restated: bool | None = None
    user_confirmed: bool | None = None


@dataclass(frozen=True)
class FinancialPeriod:
    """Finanzwerte einer Periode in einer einheitlichen Währung und Skalierung.

period_end ist ein datetime.date, period_months eine positive Monatsanzahl.
Alle Finanzwerte verwenden dieselbe Einheit, zum Beispiel CHF million.
Negative Werte sind erlaubt, insbesondere Verluste und Cashflow-Capex.
Unveränderliche Datensätze schützen die ausgewiesenen Werte vor Überschreiben.
"""

    company_name: str
    period_label: str
    period_end: date
    period_months: int
    currency: str
    scale: str

    revenue: float | None = None
    ebitda: float | None = None
    adjusted_ebitda: float | None = None
    ebit: float | None = None
    adjusted_ebit: float | None = None
    net_income: float | None = None
    operating_cash_flow: float | None = None
    capex: float | None = None
    reported_free_cash_flow: float | None = None
    cash: float | None = None
    gross_debt: float | None = None
    reported_net_debt: float | None = None
    inventory: float | None = None
    receivables: float | None = None
    payables: float | None = None
    total_assets: float | None = None
    equity: float | None = None

    source: SourceMetadata | None = None

    def __post_init__(self) -> None:
        """Verhindere unklare Metadaten und ungültige Zahlen an der Datengrenze."""
        for name in ("company_name", "period_label", "currency", "scale"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} muss ein nicht leerer Text sein.")
        if type(self.period_end) is not date:
            raise TypeError("period_end muss ein datetime.date sein.")
        if type(self.period_months) is not int or self.period_months <= 0:
            raise ValueError("period_months muss eine positive ganze Zahl sein.")
        if self.source is not None and not isinstance(self.source, SourceMetadata):
            raise TypeError("source muss SourceMetadata oder None sein.")

        metadata = {
            "company_name", "period_label", "period_end", "period_months",
            "currency", "scale", "source",
        }
        for definition in fields(self):
            if definition.name in metadata:
                continue
            value = getattr(self, definition.name)
            if value is not None and (
                type(value) not in (int, float) or not isfinite(value)
            ):
                raise ValueError(
                    f"{definition.name} muss eine endliche Zahl oder None sein."
                )


@dataclass(frozen=True)
class CalculatedPeriodMetrics:
    """Separate Kennzahlen; die FinancialPeriod wird nicht verändert."""

    normalized_capex: float | None = None
    ebitda_margin: float | None = None
    adjusted_ebitda_margin: float | None = None
    ebit_margin: float | None = None
    adjusted_ebit_margin: float | None = None
    net_income_margin: float | None = None
    calculated_free_cash_flow: float | None = None
    calculated_free_cash_flow_margin: float | None = None
    reported_free_cash_flow_margin: float | None = None
    operating_cash_flow_to_ebitda: float | None = None
    calculated_free_cash_flow_to_net_income: float | None = None
    calculated_net_debt: float | None = None
    calculated_net_debt_to_ebitda: float | None = None
    reported_net_debt_to_ebitda: float | None = None
    calculated_operating_working_capital: float | None = None
    operating_working_capital_to_revenue: float | None = None
    inventory_to_revenue: float | None = None
    receivables_to_revenue: float | None = None
    capex_to_revenue: float | None = None


@dataclass(frozen=True)
class PeriodComparison:
    """Faktenvergleich zweier Perioden; Differenzen sind nicht Prozentwachstum.

Margenänderungen sind Dezimaldifferenzen, *_bps sind Basispunkte.
Leverage-Änderungen sind Differenzen der Multiplikatoren, zum Beispiel 0.29x.
"""

    current_period: FinancialPeriod
    previous_period: FinancialPeriod
    current_metrics: CalculatedPeriodMetrics
    previous_metrics: CalculatedPeriodMetrics

    revenue_growth: float | None = None
    ebitda_growth: float | None = None
    ebit_growth: float | None = None
    net_income_growth: float | None = None
    operating_cash_flow_growth: float | None = None
    calculated_free_cash_flow_growth: float | None = None
    inventory_growth: float | None = None
    receivables_growth: float | None = None
    gross_debt_growth: float | None = None

    ebitda_margin_change: float | None = None
    ebitda_margin_change_bps: float | None = None
    ebit_margin_change: float | None = None
    ebit_margin_change_bps: float | None = None
    net_income_margin_change: float | None = None
    net_income_margin_change_bps: float | None = None
    calculated_free_cash_flow_margin_change: float | None = None
    calculated_free_cash_flow_margin_change_bps: float | None = None

    calculated_net_debt_to_ebitda_change: float | None = None
    reported_net_debt_to_ebitda_change: float | None = None
