"""Unveränderliche Erwartungs-Snapshots und neutrale Surprise-Ergebnisse."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from math import isfinite
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from .history_workspace import PeriodKey

if TYPE_CHECKING:
    from .models import CalculatedPeriodMetrics, FinancialPeriod


ExpectationSourceType = Literal["consensus", "internal", "other"]
SurpriseType = Literal["amount", "margin", "multiple"]
SurpriseDirection = Literal["above", "below", "equal"]

SUPPORTED_EXPECTATION_METRICS = (
    "revenue",
    "ebitda",
    "ebit",
    "ebit_margin",
    "net_income",
    "basic_eps",
    "diluted_eps",
    "operating_cash_flow",
    "reported_free_cash_flow",
    "reported_net_debt",
    "calculated_net_debt_to_ebitda",
)


@dataclass(frozen=True)
class ExpectationSnapshot:
    """Manuell erfasster Informationsstand für genau eine Zielperiode.

    Mehrere Snapshots dürfen dieselbe Zielperiode betreffen. ``snapshot_id``
    unterscheidet sie, während ``as_of_date`` den Wissensstand dokumentiert.
    Fehlende Schätzwerte bleiben ``None``.
    """

    company: str
    target_period: PeriodKey
    as_of_date: date
    label: str
    source_type: ExpectationSourceType
    currency: str
    scale: str
    metric_expectations: Mapping[str, float | None] | tuple[tuple[str, float | None], ...]
    notes: str | None = None
    snapshot_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        for name in ("company", "label", "currency", "scale", "snapshot_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} muss ein nicht leerer Text sein.")
        if not isinstance(self.target_period, PeriodKey):
            raise TypeError("target_period muss ein PeriodKey sein.")
        if type(self.as_of_date) is not date:
            raise TypeError("as_of_date muss ein datetime.date sein.")
        if self.source_type not in ("consensus", "internal", "other"):
            raise ValueError("source_type muss consensus, internal oder other sein.")
        if self.notes is not None and not isinstance(self.notes, str):
            raise TypeError("notes muss Text oder None sein.")

        items = (
            tuple(self.metric_expectations.items())
            if isinstance(self.metric_expectations, Mapping)
            else tuple(self.metric_expectations)
        )
        seen: set[str] = set()
        normalized: list[tuple[str, float | None]] = []
        for metric, value in items:
            if metric not in SUPPORTED_EXPECTATION_METRICS:
                raise ValueError(f"Nicht unterstützte Erwartungskennzahl: {metric}.")
            if metric in seen:
                raise ValueError(f"Doppelte Erwartungskennzahl: {metric}.")
            if value is not None and (
                type(value) not in (int, float) or not isfinite(value)
            ):
                raise ValueError(f"{metric} muss eine endliche Zahl oder None sein.")
            seen.add(metric)
            normalized.append((metric, value))
        object.__setattr__(self, "metric_expectations", tuple(normalized))

    def get(self, canonical_metric: str) -> float | None:
        """Liefere einen Schätzwert, ohne fehlende Werte als null zu behandeln."""
        return dict(self.metric_expectations).get(canonical_metric)

    @property
    def metrics(self) -> dict[str, float | None]:
        """Liefere eine frische, veränderbare Ansicht der unveränderlichen Werte."""
        return dict(self.metric_expectations)


@dataclass(frozen=True)
class MetricSurprise:
    """Neutrale Abweichung einer Kennzahl von ihrer Erwartung."""

    canonical_metric: str
    actual_value: float | None
    estimate_value: float | None
    surprise_absolute: float | None
    surprise_percent: float | None
    surprise_bps: float | None
    change_type: SurpriseType
    direction: SurpriseDirection | None


@dataclass(frozen=True)
class ExpectationComparison:
    """Ergebnis eines validierten Actual-vs-Estimate-Vergleichs."""

    actual_period: "FinancialPeriod"
    actual_metrics: "CalculatedPeriodMetrics"
    expectation: ExpectationSnapshot
    metric_surprises: tuple[MetricSurprise, ...]

    def get(self, canonical_metric: str) -> MetricSurprise | None:
        return next(
            (item for item in self.metric_surprises if item.canonical_metric == canonical_metric),
            None,
        )
