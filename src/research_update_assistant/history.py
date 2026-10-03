"""Chronologische Periodenhistorie ohne automatische Quellenauswahl."""

from dataclasses import dataclass

from .models import FinancialPeriod


class AmbiguousPeriodError(ValueError):
    """Mehrere Datensätze erfüllen die Periodenabfrage."""


@dataclass
class FinancialHistory:
    """Bewahre alle Periodendatensätze inklusive gleicher Labels und Stichtage.

Die Historie kann eine bereits normalisierte Auswahl oder mehrere Kandidaten
enthalten. Sie löst keine Restatements und Quellenkonflikte auf. Eine spätere
Source-/Validation-Schicht bestimmt explizit die normalisierte Auswahl.
Eine unveränderliche Sequenz verhindert unbeabsichtigtes Anhängen ohne Sortierung.
"""

    periods: tuple[FinancialPeriod, ...] = ()

    def __post_init__(self) -> None:
        self.periods = tuple(sorted(self.periods, key=lambda period: period.period_end))

    def add_period(self, period: FinancialPeriod) -> None:
        """Ergänze einen Datensatz und sortiere nach dem tatsächlichen Stichtag."""
        self.periods = tuple(
            sorted((*self.periods, period), key=lambda item: item.period_end)
        )

    def get_periods(self, period_label: str) -> tuple[FinancialPeriod, ...]:
        """Liefere alle passenden Datensätze, auch aus unterschiedlichen Quellen."""
        return tuple(period for period in self.periods if period.period_label == period_label)

    def get_period(self, period_label: str) -> FinancialPeriod:
        """Liefere nur eindeutige Treffer; wähle bei Konflikten keinen Gewinner."""
        matches = self.get_periods(period_label)
        if not matches:
            raise KeyError(f"Keine Periode mit Label {period_label} vorhanden.")
        if len(matches) > 1:
            raise AmbiguousPeriodError(
                f"{period_label} hat {len(matches)} Datensätze. "
                "Bitte Quelle und Periode ausdrücklich auswählen."
            )
        return matches[0]
