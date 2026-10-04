"""Manuelle Eingaben prüfen und in bestehende Periodenobjekte übersetzen."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from math import isfinite

from .history import FinancialHistory
from .models import FinancialPeriod


CURRENCIES = ("CHF", "EUR", "USD")
SCALE_OPTIONS = (
    ("unit", "Einheiten"),
    ("thousand", "Tausend"),
    ("million", "Millionen"),
    ("billion", "Milliarden"),
)
FINANCIAL_INPUT_GROUPS = (
    ("Erfolgsrechnung", (
        ("revenue", "Umsatz"),
        ("ebitda", "EBITDA"),
        ("adjusted_ebitda", "Bereinigtes EBITDA (optional)"),
        ("ebit", "EBIT"),
        ("adjusted_ebit", "Bereinigtes EBIT (optional)"),
        ("net_income", "Nettoergebnis"),
    )),
    ("Cashflow", (
        ("operating_cash_flow", "Geldfluss aus Geschäftstätigkeit"),
        ("capex", "Investitionen (Capex)"),
        ("reported_free_cash_flow", "Ausgewiesener Free Cashflow (optional)"),
    )),
    ("Bilanz", (
        ("cash", "Flüssige Mittel"),
        ("gross_debt", "Finanzschulden"),
        ("reported_net_debt", "Ausgewiesene Nettoverschuldung (optional)"),
        ("inventory", "Vorräte"),
        ("receivables", "Forderungen aus Lieferungen und Leistungen"),
        ("payables", "Verbindlichkeiten aus Lieferungen und Leistungen"),
        ("total_assets", "Bilanzsumme (optional)"),
        ("equity", "Eigenkapital (optional)"),
    )),
)

# Punkt/Komma sind ausschliesslich Dezimaltrenner. Gruppierung muss aus
# vollständigen Dreiergruppen mit einem einheitlichen Trenner bestehen.
_NUMBER_PATTERN = re.compile(
    r"[+-]?(?:[0-9]+|[0-9]{1,3}(?P<group>[' ])[0-9]{3}"
    r"(?:(?P=group)[0-9]{3})*)(?:[.,][0-9]+)?"
)


class NumberParsingError(ValueError):
    """Eine manuell eingegebene Zahl besitzt kein unterstütztes Format."""


class InputValidationError(ValueError):
    """Die manuelle Analyse benötigt eine Korrektur der Eingaben."""


def parse_optional_number(text: str) -> float | None:
    """Parse Schweizer Gruppierung und Punkt/Komma als Dezimaltrenner.

Leer bzw. nur Leerzeichen ergibt None. Apostroph, typografischer Apostroph
und normale/geschützte Leerzeichen sind Tausendertrenner. Ungültige oder
gemischte Gruppierung, Exponenten und nicht endliche Werte werden abgewiesen.
Es werden keine Finanzwerte normalisiert oder gerundet.
"""
    value = text.strip()
    if not value:
        return None
    value = value.replace("’", "'").replace("\u00a0", " ").replace("\u202f", " ")
    if _NUMBER_PATTERN.fullmatch(value) is None:
        raise NumberParsingError(
            "Bitte eine Zahl wie 1100, 1’100 oder 1’100,5 eingeben. "
            "Punkt oder Komma trennt die Dezimalstellen."
        )
    number = float(value.replace("'", "").replace(" ", "").replace(",", "."))
    if not isfinite(number):
        raise NumberParsingError("Die Zahl liegt ausserhalb des unterstützten Zahlenbereichs.")
    return number


@dataclass(frozen=True)
class ManualPeriodInput:
    """Noch ungeparste Formulardaten; Finanzfelder enthalten ausschliesslich Text."""

    period_label: str
    period_end: date | None
    period_months: int = 12
    values: Mapping[str, str] = field(default_factory=dict)


def create_financial_period(
    company_name: str, currency: str, scale: str, raw: ManualPeriodInput
) -> FinancialPeriod:
    """Erzeuge eine Periode mit None für Leerwerte und ohne erzwungene PDF-Herkunft."""
    company_name = company_name.strip()
    label = raw.period_label.strip()
    if not company_name:
        raise InputValidationError("Bitte einen Unternehmensnamen eingeben.")
    if currency not in CURRENCIES:
        raise InputValidationError("Bitte eine Währung auswählen: CHF, EUR oder USD.")
    if scale not in dict(SCALE_OPTIONS):
        raise InputValidationError("Bitte eine gültige Einheit auswählen.")
    if not label:
        raise InputValidationError("Bitte für jede Periode eine Periodenbezeichnung eingeben.")
    if type(raw.period_end) is not date:
        raise InputValidationError(f"Bitte einen gültigen Stichtag für {label} eingeben.")
    if type(raw.period_months) is not int or raw.period_months <= 0:
        raise InputValidationError(f"Die Periodendauer für {label} muss eine positive Monatsanzahl sein.")

    values: dict[str, float | None] = {}
    for _, definitions in FINANCIAL_INPUT_GROUPS:
        for name, display_label in definitions:
            try:
                values[name] = parse_optional_number(raw.values.get(name, ""))
            except NumberParsingError as error:
                field_label = display_label.removesuffix(" (optional)")
                raise InputValidationError(
                    f"Der Wert für {field_label} in {label} konnte nicht als Zahl "
                    f"interpretiert werden. {error}"
                ) from error

    return FinancialPeriod(
        company_name=company_name, period_label=label, period_end=raw.period_end,
        period_months=raw.period_months, currency=currency, scale=scale, **values,
    )


def create_manual_history(
    company_name: str, currency: str, scale: str, raw_periods: Sequence[ManualPeriodInput]
) -> FinancialHistory:
    """Prüfe zwei oder drei manuelle Perioden und lasse die Historie sortieren.

Eindeutige Labels gelten nur für dieses manuelle Formular. Der bestehende
Historienkern behält weiterhin mehrere Quellen für dieselbe Periode bei.
"""
    if len(raw_periods) not in (2, 3):
        raise InputValidationError("Bitte zwei oder drei Perioden erfassen.")
    periods = tuple(
        create_financial_period(company_name, currency, scale, raw)
        for raw in raw_periods
    )
    labels = [period.period_label.casefold() for period in periods]
    if len(set(labels)) != len(labels):
        raise InputValidationError("Die Periodenbezeichnungen müssen unterschiedlich sein.")
    return FinancialHistory(periods)
