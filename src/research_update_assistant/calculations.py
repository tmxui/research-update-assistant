"""Reine Finanzberechnungen ohne Streamlit, Pandas oder Dokumentenzugriff."""

from .models import CalculatedPeriodMetrics, FinancialPeriod, PeriodComparison


class PeriodCompatibilityError(ValueError):
    """Die Perioden sind für den gewünschten Zeitvergleich nicht kompatibel."""


def safe_divide(
    numerator: float | None, denominator: float | None
) -> float | None:
    """Teile nur bei vorhandenen Werten und einem Nenner ungleich null."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def percentage_change(current: float | None, previous: float | None) -> float | None:
    """Berechne current / previous - 1, ohne Rundung oder Vorzeichenkorrektur.

Auch negative Ausgangswerte folgen dieser Formel. Eine wirtschaftliche
Interpretation, etwa bei einem Verlustwechsel, gehört nicht zu Phase 1.
"""
    ratio = safe_divide(current, previous)
    return None if ratio is None else ratio - 1


def _difference(current: float | None, previous: float | None) -> float | None:
    """Berechne die absolute Differenz vorhandener Werte."""
    if current is None or previous is None:
        return None
    return current - previous


def margin_change(
    current_margin: float | None, previous_margin: float | None
) -> float | None:
    """Berechne eine Margendifferenz als Dezimalzahl, nicht als Wachstumsrate."""
    return _difference(current_margin, previous_margin)


def margin_change_bps(
    current_margin: float | None, previous_margin: float | None
) -> float | None:
    """Rechne die Margendifferenz in Basispunkte um: Differenz * 10_000."""
    change = margin_change(current_margin, previous_margin)
    return None if change is None else change * 10_000


def normalize_capex(capex: float | None) -> float | None:
    """Behandle Capex als positiven Investitionsbetrag; fehlend bleibt None."""
    return None if capex is None else abs(capex)


def _operating_working_capital(period: FinancialPeriod) -> float | None:
    """Berechne Forderungen + Vorräte - Verbindlichkeiten bei vollständigen Daten."""
    if period.receivables is None or period.inventory is None or period.payables is None:
        return None
    return period.receivables + period.inventory - period.payables


def calculate_period_metrics(period: FinancialPeriod) -> CalculatedPeriodMetrics:
    """Berechne Kennzahlen separat von reported-Werten und Herkunft.

Net Debt / EBITDA wird nur für zwölfmonatige Perioden berechnet. Es gibt
keine Annualisierung. Alle Ergebnisse behalten die Eingabeeinheit bzw.
sind dimensionslose Verhältnisse; fehlende Eingaben werden nicht ersetzt.
"""
    capex = normalize_capex(period.capex)
    free_cash_flow = _difference(period.operating_cash_flow, capex)
    net_debt = _difference(period.gross_debt, period.cash)
    working_capital = _operating_working_capital(period)
    is_full_year = period.period_months == 12

    return CalculatedPeriodMetrics(
        normalized_capex=capex,
        ebitda_margin=safe_divide(period.ebitda, period.revenue),
        adjusted_ebitda_margin=safe_divide(period.adjusted_ebitda, period.revenue),
        ebit_margin=safe_divide(period.ebit, period.revenue),
        adjusted_ebit_margin=safe_divide(period.adjusted_ebit, period.revenue),
        net_income_margin=safe_divide(period.net_income, period.revenue),
        calculated_free_cash_flow=free_cash_flow,
        calculated_free_cash_flow_margin=safe_divide(free_cash_flow, period.revenue),
        reported_free_cash_flow_margin=safe_divide(
            period.reported_free_cash_flow, period.revenue
        ),
        operating_cash_flow_to_ebitda=safe_divide(period.operating_cash_flow, period.ebitda),
        calculated_free_cash_flow_to_net_income=safe_divide(free_cash_flow, period.net_income),
        calculated_net_debt=net_debt,
        calculated_net_debt_to_ebitda=(
            safe_divide(net_debt, period.ebitda) if is_full_year else None
        ),
        reported_net_debt_to_ebitda=(
            safe_divide(period.reported_net_debt, period.ebitda) if is_full_year else None
        ),
        calculated_operating_working_capital=working_capital,
        operating_working_capital_to_revenue=safe_divide(working_capital, period.revenue),
        inventory_to_revenue=safe_divide(period.inventory, period.revenue),
        receivables_to_revenue=safe_divide(period.receivables, period.revenue),
        capex_to_revenue=safe_divide(capex, period.revenue),
    )


def _validate_comparison(current: FinancialPeriod, previous: FinancialPeriod) -> None:
    """Verhindere einen Vergleich verschiedener Unternehmen oder Einheiten."""
    for name, label in (
        ("company_name", "Unternehmen"),
        ("currency", "Währung"),
        ("scale", "Skalierung"),
        ("period_months", "Periodenlänge"),
    ):
        current_value = getattr(current, name)
        previous_value = getattr(previous, name)
        if current_value != previous_value:
            raise PeriodCompatibilityError(
                f"Vergleich verhindert: {label} unterscheiden sich "
                f"({current_value} vs. {previous_value})."
            )
    if current.period_end <= previous.period_end:
        raise PeriodCompatibilityError(
            "Die aktuelle Periode muss nach der Vergleichsperiode enden."
        )


def compare_periods(current: FinancialPeriod, previous: FinancialPeriod) -> PeriodComparison:
    """Vergleiche genau zwei kompatible Perioden; auch mehrjährige Abstände.

Dies ist kein Historienalgorithmus und keine automatisch annualisierte
Wachstumsrate. Dokumentherkunft und Labels beeinflussen die Formeln nicht.
Die aufrufende Schicht entscheidet, welche Quelldatensätze sie verwendet.
"""
    _validate_comparison(current, previous)
    current_metrics = calculate_period_metrics(current)
    previous_metrics = calculate_period_metrics(previous)
    return PeriodComparison(
        current_period=current,
        previous_period=previous,
        current_metrics=current_metrics,
        previous_metrics=previous_metrics,
        revenue_growth=percentage_change(current.revenue, previous.revenue),
        ebitda_growth=percentage_change(current.ebitda, previous.ebitda),
        ebit_growth=percentage_change(current.ebit, previous.ebit),
        net_income_growth=percentage_change(current.net_income, previous.net_income),
        operating_cash_flow_growth=percentage_change(
            current.operating_cash_flow, previous.operating_cash_flow
        ),
        calculated_free_cash_flow_growth=percentage_change(
            current_metrics.calculated_free_cash_flow,
            previous_metrics.calculated_free_cash_flow,
        ),
        inventory_growth=percentage_change(current.inventory, previous.inventory),
        receivables_growth=percentage_change(current.receivables, previous.receivables),
        gross_debt_growth=percentage_change(current.gross_debt, previous.gross_debt),
        ebitda_margin_change=margin_change(
            current_metrics.ebitda_margin, previous_metrics.ebitda_margin
        ),
        ebitda_margin_change_bps=margin_change_bps(
            current_metrics.ebitda_margin, previous_metrics.ebitda_margin
        ),
        ebit_margin_change=margin_change(
            current_metrics.ebit_margin, previous_metrics.ebit_margin
        ),
        ebit_margin_change_bps=margin_change_bps(
            current_metrics.ebit_margin, previous_metrics.ebit_margin
        ),
        net_income_margin_change=margin_change(
            current_metrics.net_income_margin, previous_metrics.net_income_margin
        ),
        net_income_margin_change_bps=margin_change_bps(
            current_metrics.net_income_margin, previous_metrics.net_income_margin
        ),
        calculated_free_cash_flow_margin_change=margin_change(
            current_metrics.calculated_free_cash_flow_margin,
            previous_metrics.calculated_free_cash_flow_margin,
        ),
        calculated_free_cash_flow_margin_change_bps=margin_change_bps(
            current_metrics.calculated_free_cash_flow_margin,
            previous_metrics.calculated_free_cash_flow_margin,
        ),
        calculated_net_debt_to_ebitda_change=_difference(
            current_metrics.calculated_net_debt_to_ebitda,
            previous_metrics.calculated_net_debt_to_ebitda,
        ),
        reported_net_debt_to_ebitda_change=_difference(
            current_metrics.reported_net_debt_to_ebitda,
            previous_metrics.reported_net_debt_to_ebitda,
        ),
    )
