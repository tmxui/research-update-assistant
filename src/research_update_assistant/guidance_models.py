"""Unveränderliche Modelle für Unternehmens-Guidance und ihre Vergleiche."""

from dataclasses import dataclass, field
from datetime import date
from math import isfinite
from typing import Literal
from uuid import uuid4

from .history_workspace import PeriodKey
from .models import CalculatedPeriodMetrics, FinancialPeriod


GuidanceType = Literal[
    "exact", "min", "above", "max", "below", "range", "approximate", "qualitative"
]
QualitativeDirection = Literal["increase", "decrease", "stable", "around"]
GuidanceSourceType = Literal[
    "annual_report", "half_year_report", "results_presentation", "other"
]
GuidanceChangeType = Literal[
    "raised", "lowered", "narrowed", "widened", "unchanged", "changed"
]
ActualGuidanceStatus = Literal[
    "within", "above", "below", "not_assessable", "missing_actual"
]

SUPPORTED_GUIDANCE_METRICS = (
    "revenue_growth",
    "ebitda_margin",
    "ebit_margin",
    "revenue",
    "ebitda",
    "ebit",
    "reported_free_cash_flow",
    "reported_net_debt",
)
PERCENTAGE_GUIDANCE_METRICS = {
    "revenue_growth", "ebitda_margin", "ebit_margin",
}


@dataclass(frozen=True)
class GuidanceItem:
    """Eine Guidance-Aussage, deren ursprüngliche Form erhalten bleibt."""

    canonical_metric: str
    guidance_type: GuidanceType
    exact_value: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    qualitative_direction: QualitativeDirection | None = None

    def __post_init__(self) -> None:
        if self.canonical_metric not in SUPPORTED_GUIDANCE_METRICS:
            raise ValueError(f"Nicht unterstützte Guidance-Kennzahl: {self.canonical_metric}.")
        if self.guidance_type not in (
            "exact", "min", "above", "max", "below", "range", "approximate", "qualitative",
        ):
            raise ValueError(f"Nicht unterstützte Guidance-Form: {self.guidance_type}.")
        for name in ("exact_value", "minimum", "maximum"):
            value = getattr(self, name)
            if value is not None and (
                type(value) not in (int, float) or not isfinite(value)
            ):
                raise ValueError(f"{name} muss eine endliche Zahl oder None sein.")

        numeric = {
            "exact": (self.exact_value is not None and self.minimum is None and self.maximum is None),
            "min": (self.minimum is not None and self.exact_value is None and self.maximum is None),
            "above": (self.minimum is not None and self.exact_value is None and self.maximum is None),
            "max": (self.maximum is not None and self.exact_value is None and self.minimum is None),
            "below": (self.maximum is not None and self.exact_value is None and self.minimum is None),
            "range": (self.minimum is not None and self.maximum is not None and self.exact_value is None),
            "approximate": (self.exact_value is not None and self.minimum is None and self.maximum is None),
            "qualitative": (self.exact_value is None and self.minimum is None and self.maximum is None),
        }[self.guidance_type]
        if not numeric:
            raise ValueError("Werte passen nicht zur gewählten Guidance-Form.")
        if self.guidance_type == "range" and self.minimum > self.maximum:
            raise ValueError("Die Guidance-Untergrenze darf nicht über der Obergrenze liegen.")
        if self.guidance_type == "qualitative":
            if self.qualitative_direction not in ("increase", "decrease", "stable", "around"):
                raise ValueError("Qualitative Guidance benötigt eine unterstützte Richtung.")
        elif self.qualitative_direction is not None:
            raise ValueError("Eine numerische Guidance darf keine qualitative Richtung tragen.")


@dataclass(frozen=True)
class GuidanceSnapshot:
    """Unternehmensaussage für eine Zielperiode zu einem dokumentierten Stand."""

    company: str
    target_period: PeriodKey
    as_of_date: date
    label: str
    source_type: GuidanceSourceType
    currency: str
    scale: str
    guidance_items: tuple[GuidanceItem, ...]
    source_document: str | None = None
    source_page: int | None = None
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
        if self.source_type not in (
            "annual_report", "half_year_report", "results_presentation", "other",
        ):
            raise ValueError("source_type ist für Guidance nicht unterstützt.")
        for name in ("source_document", "notes"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"{name} muss Text oder None sein.")
        if self.source_page is not None and (
            type(self.source_page) is not int or self.source_page <= 0
        ):
            raise ValueError("source_page muss eine positive ganze Zahl oder None sein.")
        items = tuple(self.guidance_items)
        if any(not isinstance(item, GuidanceItem) for item in items):
            raise TypeError("guidance_items darf nur GuidanceItem-Objekte enthalten.")
        metrics = [item.canonical_metric for item in items]
        if len(metrics) != len(set(metrics)):
            raise ValueError("Ein Snapshot darf pro Kennzahl nur eine Guidance enthalten.")
        order = {metric: index for index, metric in enumerate(SUPPORTED_GUIDANCE_METRICS)}
        object.__setattr__(self, "guidance_items", tuple(sorted(items, key=lambda item: order[item.canonical_metric])))

    def get(self, canonical_metric: str) -> GuidanceItem | None:
        return next(
            (item for item in self.guidance_items if item.canonical_metric == canonical_metric),
            None,
        )


@dataclass(frozen=True)
class GuidanceItemChange:
    canonical_metric: str
    previous_item: GuidanceItem | None
    current_item: GuidanceItem | None
    changes: tuple[GuidanceChangeType, ...]


@dataclass(frozen=True)
class GuidanceSnapshotComparison:
    previous_snapshot: GuidanceSnapshot
    current_snapshot: GuidanceSnapshot
    item_changes: tuple[GuidanceItemChange, ...]

    def get(self, canonical_metric: str) -> GuidanceItemChange | None:
        return next(
            (item for item in self.item_changes if item.canonical_metric == canonical_metric),
            None,
        )


@dataclass(frozen=True)
class ActualGuidanceItemComparison:
    canonical_metric: str
    actual_value: float | None
    guidance_item: GuidanceItem
    status: ActualGuidanceStatus


@dataclass(frozen=True)
class ActualGuidanceComparison:
    actual_period: FinancialPeriod
    actual_metrics: CalculatedPeriodMetrics
    guidance_snapshot: GuidanceSnapshot
    item_comparisons: tuple[ActualGuidanceItemComparison, ...]

    def get(self, canonical_metric: str) -> ActualGuidanceItemComparison | None:
        return next(
            (item for item in self.item_comparisons if item.canonical_metric == canonical_metric),
            None,
        )
