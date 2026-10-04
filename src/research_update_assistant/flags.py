"""Transparente Research-Prüfpunkte aus bestehenden Kennzahlen, ohne Streamlit.

Schwellen kommen ausschliesslich aus FlagRules. Keine Gesamtnote, keine
Ursachenvermutungen und kein Fallback auf reported- oder adjusted-Kennzahlen.
Wachstumsregeln benötigen positive Ausgangswerte, damit Vorzeichenwechsel
bei Verlusten bzw. negativem Cashflow keine irreführenden Hinweise erzeugen.
"""

from dataclasses import dataclass
from math import isclose, isfinite
from typing import Literal

from .flag_config import FlagRules, RuleThresholds
from .formatting import format_amount
from .models import PeriodComparison


Severity = Literal["red", "yellow", "green"]
ThresholdUnit = Literal["percentage", "percentage_points", "bps", "multiple"]


@dataclass(frozen=True)
class ResearchFlag:
    """Ein einzelner Prüfanlass mit ungerundeten Werten und auslösender Schwelle.

current_value/previous_value beziehen sich auf die Finanzwerte der Perioden.
change_value verwendet die Einheit der Regel: Wachstum, Wachstumsspread,
Basispunkte oder Multiplikatordifferenz. Bei Level-Regeln ist es das Level.
"""

    rule_id: str
    category: str
    severity: Severity
    title: str
    message: str
    metric_name: str
    current_value: float | None
    previous_value: float | None
    change_value: float
    threshold: float
    threshold_unit: ThresholdUnit
    threshold_operator: str
    period_current: str
    period_previous: str


def _available(*values: float | None) -> bool:
    return all(value is not None and isfinite(value) for value in values)


def _growth_available(previous: float | None, growth: float | None) -> bool:
    return _available(previous, growth) and previous > 0


def _at_most(value: float, threshold: float) -> bool:
    """Toleranz nur für Maschinenpräzision; die Kennzahl bleibt ungerundet."""
    return value <= threshold or isclose(value, threshold, rel_tol=1e-12, abs_tol=1e-12)


def _at_least(value: float, threshold: float) -> bool:
    return value >= threshold or isclose(value, threshold, rel_tol=1e-12, abs_tol=1e-12)


def _decline_severity(
    value: float, thresholds: RuleThresholds, *, strict_yellow: bool = False
) -> Severity | None:
    if _at_most(value, thresholds.red):
        return "red"
    yellow = value < thresholds.yellow if strict_yellow else _at_most(value, thresholds.yellow)
    return "yellow" if yellow else None


def _increase_severity(value: float, thresholds: RuleThresholds) -> Severity | None:
    if _at_least(value, thresholds.red):
        return "red"
    return "yellow" if _at_least(value, thresholds.yellow) else None


def _decimal(value: float, digits: int = 1, *, signed: bool = False) -> str:
    return (f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}").replace(".", ",")


def _percent(value: float) -> str:
    return _decimal(abs(value) * 100) + " %"


def _growth_text(subject: str, value: float) -> str:
    if value > 0:
        return f"{subject} stieg um {_percent(value)}"
    if value < 0:
        return f"{subject} sank um {_percent(value)}"
    return f"{subject} blieb unverändert ({_percent(value)})"


def _money(value: float, comparison: PeriodComparison) -> str:
    period = comparison.current_period
    unit = {"unit": "", "thousand": "Tsd.", "million": "Mio.", "billion": "Mrd."}.get(
        period.scale, period.scale
    )
    return f"{period.currency} {format_amount(value).replace('.', ',')} {unit}".strip()


def _make_flag(
    comparison: PeriodComparison, *, rule_id: str, category: str,
    severity: Severity, title: str, message: str, metric_name: str,
    current_value: float | None, previous_value: float | None, change_value: float,
    threshold: float, unit: ThresholdUnit, operator: str,
) -> ResearchFlag:
    return ResearchFlag(
        rule_id=rule_id, category=category, severity=severity, title=title, message=message,
        metric_name=metric_name, current_value=current_value, previous_value=previous_value,
        change_value=change_value, threshold=threshold, threshold_unit=unit,
        threshold_operator=operator, period_current=comparison.current_period.period_label,
        period_previous=comparison.previous_period.period_label,
    )


def _revenue_flags(c: PeriodComparison, rules: FlagRules) -> list[ResearchFlag]:
    growth = c.revenue_growth
    if not _growth_available(c.previous_period.revenue, growth):
        return []
    severity = _decline_severity(growth, rules.revenue_decline, strict_yellow=True)
    if severity is None:
        return []
    return [_make_flag(
        c, rule_id="revenue_decline", category="Wachstum", severity=severity,
        title="Umsatzrückgang", message=f"Der Umsatz sank gegenüber der Vorperiode um {_percent(growth)}.",
        metric_name="revenue_growth", current_value=c.current_period.revenue,
        previous_value=c.previous_period.revenue, change_value=growth,
        threshold=getattr(rules.revenue_decline, severity), unit="percentage",
        operator="≤" if severity == "red" else "<",
    )]


def _margin_flags(c: PeriodComparison, rules: FlagRules) -> list[ResearchFlag]:
    flags = []
    for name, label in (("ebit", "EBIT"), ("ebitda", "EBITDA")):
        current = getattr(c.current_metrics, f"{name}_margin")
        previous = getattr(c.previous_metrics, f"{name}_margin")
        change = getattr(c, f"{name}_margin_change_bps")
        if not _available(current, previous, change):
            continue
        rule_id = f"{name}_margin_decline"
        thresholds = getattr(rules, rule_id)
        severity = _decline_severity(change, thresholds)
        if severity is not None:
            flags.append(_make_flag(
                c, rule_id=rule_id, category="Profitabilität", severity=severity,
                title=f"{label}-Marge gesunken",
                message=f"Die {label}-Marge sank von {_decimal(previous * 100)} % auf {_decimal(current * 100)} % "
                        f"bzw. um {abs(change):.0f} Basispunkte.",
                metric_name=f"{name}_margin_change_bps", current_value=current,
                previous_value=previous, change_value=change,
                threshold=getattr(thresholds, severity), unit="bps", operator="≤",
            ))
        if name == "ebit" and _at_least(change, rules.positive.ebit_margin_increase_bps):
            flags.append(_make_flag(
                c, rule_id="ebit_margin_improvement", category="Profitabilität", severity="green",
                title="EBIT-Marge gestiegen",
                message=f"Die EBIT-Marge stieg von {_decimal(previous * 100)} % auf {_decimal(current * 100)} % "
                        f"bzw. um {change:.0f} Basispunkte.",
                metric_name="ebit_margin_change_bps", current_value=current,
                previous_value=previous, change_value=change,
                threshold=rules.positive.ebit_margin_increase_bps, unit="bps", operator="≥",
            ))
    return flags


def _free_cash_flow_flags(c: PeriodComparison, rules: FlagRules) -> list[ResearchFlag]:
    current = c.current_metrics.calculated_free_cash_flow
    previous = c.previous_metrics.calculated_free_cash_flow
    growth = c.calculated_free_cash_flow_growth
    if not _available(current) or not _growth_available(previous, growth):
        return []
    severity = _decline_severity(growth, rules.free_cash_flow_decline)
    if severity is None and _at_least(growth, rules.positive.free_cash_flow_growth):
        severity = "green"
    if severity is None:
        return []
    positive = severity == "green"
    verb = "stieg" if positive else "sank"
    return [_make_flag(
        c, rule_id="free_cash_flow_improvement" if positive else "free_cash_flow_decline",
        category="Cashflow", severity=severity, title=f"Berechneter Free Cashflow {verb}",
        message=f"Der berechnete Free Cashflow {verb} von {_money(previous, c)} auf "
                f"{_money(current, c)} bzw. um {_percent(growth)}.",
        metric_name="calculated_free_cash_flow_growth", current_value=current,
        previous_value=previous, change_value=growth,
        threshold=rules.positive.free_cash_flow_growth if positive else getattr(rules.free_cash_flow_decline, severity),
        unit="percentage", operator="≥" if positive else "≤",
    )]


def _growth_spread_flags(c: PeriodComparison, rules: FlagRules) -> list[ResearchFlag]:
    if not _growth_available(c.previous_period.revenue, c.revenue_growth):
        return []
    flags = []
    definitions = (
        ("ebit", "ebit_growth_lag", "Profitabilität", "EBIT wächst schwächer als Umsatz", "Der EBIT", ""),
        ("inventory", "inventory_growth_excess", "Working Capital", "Vorräte wachsen schneller als Umsatz", "Die Vorräte", "Working-Capital-Entwicklung prüfen."),
        ("receivables", "receivables_growth_excess", "Working Capital", "Forderungen wachsen schneller als Umsatz", "Die Forderungen", "Entwicklung der Forderungen prüfen."),
    )
    for name, rule_id, category, title, subject, follow_up in definitions:
        growth = getattr(c, f"{name}_growth")
        previous = getattr(c.previous_period, name)
        if not _growth_available(previous, growth):
            continue
        if name == "ebit" and c.revenue_growth <= 0:
            continue
        spread = growth - c.revenue_growth
        thresholds = getattr(rules, rule_id)
        severity = (_decline_severity if name == "ebit" else _increase_severity)(spread, thresholds)
        if severity is None:
            continue
        growth_text = _growth_text(subject, growth)
        # Grammatik für Plural; Zahlen und Richtung bleiben unverändert.
        if name != "ebit":
            growth_text = growth_text.replace(" stieg ", " stiegen ").replace(" sank ", " sanken ").replace(" blieb ", " blieben ")
        message = f"{growth_text}; {_growth_text('der Umsatz', c.revenue_growth)}. "
        message += f"Der Wachstumsabstand beträgt {_decimal(spread * 100, signed=True)} Prozentpunkte. {follow_up}"
        flags.append(_make_flag(
            c, rule_id=rule_id, category=category, severity=severity, title=title,
            message=message.strip(), metric_name=f"{name}_growth_minus_revenue_growth",
            current_value=getattr(c.current_period, name), previous_value=previous,
            change_value=spread, threshold=getattr(thresholds, severity),
            unit="percentage_points", operator="≤" if name == "ebit" else "≥",
        ))
    return flags


def _valid_leverage(c: PeriodComparison, *, current: bool) -> bool:
    period = c.current_period if current else c.previous_period
    metrics = c.current_metrics if current else c.previous_metrics
    return (period.period_months == 12 and _available(period.ebitda, metrics.calculated_net_debt_to_ebitda)
            and period.ebitda > 0)


def _leverage_flags(c: PeriodComparison, rules: FlagRules) -> list[ResearchFlag]:
    if not _valid_leverage(c, current=True):
        return []
    current = c.current_metrics.calculated_net_debt_to_ebitda
    previous = c.previous_metrics.calculated_net_debt_to_ebitda
    flags = []
    severity = _increase_severity(current, rules.leverage_level)
    if severity is not None:
        flags.append(_make_flag(
            c, rule_id="leverage_level", category="Bilanz / Verschuldung", severity=severity,
            title="Net Debt / EBITDA: erhöhtes Level",
            message=f"Die berechnete Nettoverschuldung / EBITDA beträgt aktuell {_decimal(current, 2)}x. "
                    "Absolutes Leverage-Level prüfen.",
            metric_name="calculated_net_debt_to_ebitda", current_value=current,
            previous_value=previous, change_value=current,
            threshold=getattr(rules.leverage_level, severity), unit="multiple", operator="≥",
        ))
    change = c.calculated_net_debt_to_ebitda_change
    if not _valid_leverage(c, current=False) or not _available(change):
        return flags
    severity = _increase_severity(change, rules.leverage_increase)
    if severity is None and _at_most(change, -rules.positive.leverage_decrease):
        severity = "green"
    if severity is not None:
        positive = severity == "green"
        verb = "sank" if positive else "stieg"
        flags.append(_make_flag(
            c, rule_id="leverage_decrease" if positive else "leverage_increase",
            category="Bilanz / Verschuldung", severity=severity,
            title=f"Net Debt / EBITDA {verb}",
            message=f"Die berechnete Nettoverschuldung / EBITDA {verb} von {_decimal(previous, 2)}x auf "
                    f"{_decimal(current, 2)}x; Veränderung: {_decimal(change, 2, signed=True)}x.",
            metric_name="calculated_net_debt_to_ebitda_change", current_value=current,
            previous_value=previous, change_value=change,
            threshold=-rules.positive.leverage_decrease if positive else getattr(rules.leverage_increase, severity),
            unit="multiple", operator="≤" if positive else "≥",
        ))
    return flags


def _cashflow_divergence_flags(c: PeriodComparison, rules: FlagRules) -> list[ResearchFlag]:
    ebit_growth = c.ebit_growth
    cash_growth = c.operating_cash_flow_growth
    if not (_growth_available(c.previous_period.ebit, ebit_growth)
            and _growth_available(c.previous_period.operating_cash_flow, cash_growth)):
        return []
    thresholds = rules.cashflow_ebit_divergence
    if ebit_growth >= 0 and _at_most(cash_growth, thresholds.red):
        severity: Severity = "red"
    elif ebit_growth > 0 and cash_growth < thresholds.yellow:
        severity = "yellow"
    else:
        return []
    return [_make_flag(
        c, rule_id="cashflow_ebit_divergence", category="Cashflow", severity=severity,
        title="Geldfluss entwickelt sich schwächer als EBIT",
        message=f"{_growth_text('Der EBIT', ebit_growth)}, während "
                f"{_growth_text('der Geldfluss aus Geschäftstätigkeit', cash_growth)}. Cash Conversion prüfen.",
        metric_name="operating_cash_flow_growth", current_value=c.current_period.operating_cash_flow,
        previous_value=c.previous_period.operating_cash_flow, change_value=cash_growth,
        threshold=getattr(thresholds, severity), unit="percentage",
        operator="≤" if severity == "red" else "<",
    )]


def generate_research_flags(comparison: PeriodComparison, rules: FlagRules) -> list[ResearchFlag]:
    """Erzeuge Prüfpunkte für genau einen Vergleich: rot, gelb, dann grün.

PeriodComparison enthält bereits beide FinancialPeriods und ihre berechneten
Kennzahlen. Die Funktion liest keine Dateien und berechnet keine Finanzratios.
Innerhalb einer Stufe bleibt die dokumentierte Regelreihenfolge bestehen.
"""
    flags = []
    for evaluate in (
        _revenue_flags, _margin_flags, _free_cash_flow_flags,
        _growth_spread_flags, _leverage_flags, _cashflow_divergence_flags,
    ):
        flags.extend(evaluate(comparison, rules))
    priority = {"red": 0, "yellow": 1, "green": 2}
    return sorted(flags, key=lambda flag: priority[flag.severity])
