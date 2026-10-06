"""Unveränderliche Mehrbericht-Historie mit expliziter Quellenentscheidung.

Wirtschaftliche Perioden werden über Stichtag und Dauer identifiziert. Jeder
bestätigte Quellwert bleibt separat erhalten. Erst die aufgelöste Auswahl wird
in die bestehenden FinancialPeriod-/FinancialHistory-Modelle übersetzt.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
from hashlib import sha256
import re
from typing import Literal

from .history import FinancialHistory
from .input_parsing import CURRENCIES, SCALE_OPTIONS, NumberParsingError
from .layout_parser import parse_accounting_number
from .models import FinancialPeriod, SourceMetadata
from .validation import ConfirmedMetricObservation, EPS_METRICS, SUPPORTED_METRICS

ResolutionStatus = Literal["unresolved", "resolved", "equivalent", "rounding_difference"]
PrecisionKey = tuple[str, str]


class HistoryWorkspaceError(ValueError):
    """Bericht, Einheiten oder Quellenentscheidung passen nicht zur Historie."""


@dataclass(frozen=True, order=True)
class PeriodKey:
    """Wirtschaftliche Identität einer Periode; das Anzeigenlabel ist kein Schlüssel."""

    period_end: date
    period_months: int

    def __post_init__(self) -> None:
        if type(self.period_end) is not date:
            raise HistoryWorkspaceError("Die Periode benötigt einen gültigen Stichtag.")
        if type(self.period_months) is not int or self.period_months <= 0:
            raise HistoryWorkspaceError("Die Periodendauer muss positiv und ganzzahlig sein.")

    def __str__(self) -> str:
        return f"{self.period_end.isoformat()}:{self.period_months}"

    @property
    def token(self) -> str:
        return str(self)


def period_key_for(period: FinancialPeriod) -> PeriodKey:
    return PeriodKey(period.period_end, period.period_months)


@dataclass(frozen=True)
class MetricObservation:
    """Bestätigter Quellwert samt unverändertem Phase-5B-Audit-Trail."""

    observation_id: str
    report_id: str
    period_key: PeriodKey
    confirmed: ConfirmedMetricObservation
    decimal_places: int | None = None
    source_priority: int = 6

    @property
    def canonical_metric(self) -> str:
        return self.confirmed.canonical_metric

    @property
    def value(self) -> float:
        return self.confirmed.confirmed_value

    @property
    def period_label(self) -> str:
        return self.confirmed.period_label

    @property
    def source_document(self) -> str | None:
        return self.confirmed.source_document

    @property
    def page_number(self) -> int | None:
        return self.confirmed.page_number


@dataclass(frozen=True)
class PeriodMetricResolution:
    """Alle Alternativen und höchstens ein für Analysen ausgewählter Wert."""

    period_key: PeriodKey
    canonical_metric: str
    observations: tuple[MetricObservation, ...]
    status: ResolutionStatus
    selected_observation_id: str | None = None
    reason: str = ""

    @property
    def resolved_value(self) -> float | None:
        if self.status == "equivalent":
            return self.observations[0].value
        if self.status == "resolved":
            return next((item.value for item in self.observations
                         if item.observation_id == self.selected_observation_id), None)
        return None


@dataclass(frozen=True)
class HistoryReport:
    """Unveränderliche Momentaufnahme eines ausdrücklich hinzugefügten Berichts."""

    report_id: str
    periods: tuple[FinancialPeriod, ...]
    observations: tuple[ConfirmedMetricObservation, ...]
    precisions: tuple[tuple[PrecisionKey, int], ...] = ()
    source_priorities: tuple[tuple[PrecisionKey, int], ...] = ()


@dataclass(frozen=True)
class ResolutionEvent:
    """Frühere Nutzerentscheidungen bleiben auch nach erneutem Konflikt erhalten."""

    action: Literal["report_added", "source_selected", "resolution_deferred", "resolution_reopened"]
    period_key: PeriodKey | None = None
    canonical_metric: str | None = None
    selected_observation_id: str | None = None
    previous_selected_observation_id: str | None = None
    reason: str = ""
    report_id: str | None = None


def _validate_precision(value: float, places: int) -> None:
    if type(places) is not int or not 0 <= places <= 15:
        raise HistoryWorkspaceError("Die berichtete Präzision benötigt 0 bis 15 Dezimalstellen.")
    decimal = Decimal(str(value))
    with localcontext() as context:
        context.prec = max(28, abs(decimal.adjusted()) + places + 20)
        if decimal.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP) != decimal:
            raise HistoryWorkspaceError("Wert und angegebene Dezimalpräzision widersprechen sich.")


def infer_reported_precision(observation: ConfirmedMetricObservation) -> int | None:
    """Nutze nur unveränderten, gültigen PDF-Rohtext als Präzisionsnachweis.

    Manuelle Ergänzungen, korrigierte Zahlen, fehlende oder nicht numerische
    Rohwerte liefern keine Präzision. Punkt und Komma sind Dezimaltrenner;
    Schweizer Apostroph-/Leerzeichengruppen verändern die Präzision nicht.
    """
    raw = observation.original_raw_value
    if (
        observation.extraction_method == "manual" or not isinstance(raw, str)
        or observation.original_extracted_value != observation.confirmed_value
    ):
        return None
    try:
        if parse_accounting_number(raw, accounting_context=True) != observation.confirmed_value:
            return None
    except NumberParsingError:
        return None
    match = re.search(r"[.,](\d+)\)?\s*$", raw.strip())
    places = len(match.group(1)) if match else 0
    return places if places <= 15 else None


def _possible_rounding(observations: tuple[MetricObservation, ...]) -> bool:
    """Gemeinsame Rundungsintervalle statt einer universellen Betrags-Toleranz.

    Die explizite Präzision bezeichnet kaufmännisches Runden (ROUND_HALF_UP).
    Ein gemeinsamer möglicher Ursprungswert muss zu jeder Observation runden.
    Null/nicht null und Vorzeichenwechsel bleiben vorsichtshalber Konflikte.
    """
    if any(item.decimal_places is None for item in observations):
        return False
    values = tuple(Decimal(str(item.value)) for item in observations)
    if any(value == 0 for value in values) or min(values) < 0 < max(values):
        return False
    with localcontext() as context:
        context.prec = max(40, max(abs(value.adjusted()) for value in values) + 40)
        units = tuple(Decimal(1).scaleb(-item.decimal_places) for item in observations)
        lower = max(value - unit / 2 for value, unit in zip(values, units))
        upper = min(value + unit / 2 for value, unit in zip(values, units))
        if lower < upper:
            return True
        if lower == upper:
            return all(lower.quantize(unit, rounding=ROUND_HALF_UP) == value
                       for value, unit in zip(values, units))
        return False


def _automatic_resolution(
    key: PeriodKey, metric: str, observations: tuple[MetricObservation, ...],
) -> PeriodMetricResolution:
    if len(observations) == 1:
        return PeriodMetricResolution(key, metric, observations, "resolved", observations[0].observation_id,
                                      "Eine ausdrücklich bestätigte Quelle.")
    if len({item.value for item in observations}) == 1:
        return PeriodMetricResolution(key, metric, observations, "equivalent", reason="Durch mehrere Quellen bestätigt.")
    if _possible_rounding(observations):
        return PeriodMetricResolution(key, metric, observations, "rounding_difference",
                                      reason="Mögliche Rundungsdifferenz anhand expliziter Dezimalpräzision; Quelle auswählen.")
    return PeriodMetricResolution(key, metric, observations, "unresolved",
                                  reason="Abweichende bestätigte Werte; Quelle ausdrücklich auswählen.")


@dataclass(frozen=True)
class HistoryWorkspace:
    """Vollständige lokale Historie, unabhängig vom gewählten Analysefenster."""

    company_name: str
    currency: str
    scale: str
    reports: tuple[HistoryReport, ...] = ()
    observations: tuple[MetricObservation, ...] = ()
    resolutions: tuple[PeriodMetricResolution, ...] = ()
    events: tuple[ResolutionEvent, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.company_name, str) or not self.company_name.strip():
            raise HistoryWorkspaceError("Bitte ein Unternehmen für die Historie bestätigen.")
        object.__setattr__(self, "company_name", self.company_name.strip())
        if self.currency not in CURRENCIES or self.scale not in dict(SCALE_OPTIONS):
            raise HistoryWorkspaceError("Die Historie benötigt eine gültige Währung und Skalierung.")

    @property
    def period_keys(self) -> tuple[PeriodKey, ...]:
        return tuple(sorted({period_key_for(period) for report in self.reports for period in report.periods}))

    @property
    def periods(self) -> tuple[FinancialPeriod, ...]:
        return self.to_financial_history().periods

    @property
    def open_resolutions(self) -> tuple[PeriodMetricResolution, ...]:
        return tuple(item for item in self.resolutions if item.status in ("unresolved", "rounding_difference"))

    def period_aliases(self, key: PeriodKey) -> tuple[str, ...]:
        return tuple(dict.fromkeys(period.period_label for report in self.reports for period in report.periods
                                   if period_key_for(period) == key))

    def get_resolution(self, key: PeriodKey, metric: str) -> PeriodMetricResolution:
        for item in self.resolutions:
            if item.period_key == key and item.canonical_metric == metric:
                return item
        raise KeyError(f"Keine Observation für {metric} in {key} vorhanden.")

    def add_report(
        self, history: FinancialHistory, observations: Sequence[ConfirmedMetricObservation], report_id: str,
        *, precisions: Mapping[PrecisionKey, int] | None = None,
        source_priorities: Mapping[PrecisionKey, int] | None = None,
    ) -> "HistoryWorkspace":
        """Füge einen bestätigten Bericht hinzu; nie Quellen oder Konflikte überschreiben."""
        if not isinstance(report_id, str) or not report_id.strip():
            raise HistoryWorkspaceError("Der Bericht benötigt eine eindeutige lokale ID.")
        if not isinstance(history, FinancialHistory) or not history.periods:
            raise HistoryWorkspaceError("Bitte mindestens eine bestätigte Periode hinzufügen.")
        report = HistoryReport(report_id.strip(), tuple(history.periods), tuple(observations),
                               tuple(sorted((precisions or {}).items())), tuple(sorted((source_priorities or {}).items())))
        previous_report = next((item for item in self.reports if item.report_id == report.report_id), None)
        if previous_report is not None:
            if previous_report == report:
                return self
            raise HistoryWorkspaceError("Diese Berichts-ID ist bereits mit anderen Daten gespeichert; bitte eine neue ID verwenden.")
        new_observations = self._validated_observations(report)
        combined = self.observations + new_observations
        resolutions = []
        events = [*self.events, ResolutionEvent("report_added", report_id=report.report_id)]
        groups = sorted({(item.period_key, item.canonical_metric) for item in combined})
        for key, metric in groups:
            items = tuple(item for item in combined if item.period_key == key and item.canonical_metric == metric)
            previous = next((item for item in self.resolutions if item.period_key == key and item.canonical_metric == metric), None)
            incoming = tuple(item for item in new_observations if item.period_key == key and item.canonical_metric == metric)
            if previous is not None and not incoming:
                resolutions.append(previous)
                continue
            decision = _automatic_resolution(key, metric, items)
            if previous is not None and previous.status == "resolved" and previous.selected_observation_id:
                if any(item.value != previous.resolved_value for item in incoming):
                    events.append(ResolutionEvent("resolution_reopened", key, metric,
                                                  previous_selected_observation_id=previous.selected_observation_id,
                                                  reason="Neue abweichende Observation; frühere Auswahl muss erneut geprüft werden.",
                                                  report_id=report.report_id))
                elif len({item.value for item in items}) > 1 or any(
                    event.action == "source_selected" and event.period_key == key
                    and event.canonical_metric == metric
                    and event.selected_observation_id == previous.selected_observation_id
                    for event in self.events
                ):
                    decision = replace(previous, observations=items)
            resolutions.append(decision)
        return replace(self, reports=self.reports + (report,), observations=combined,
                       resolutions=tuple(resolutions), events=tuple(events))

    def _validated_observations(self, report: HistoryReport) -> tuple[MetricObservation, ...]:
        by_label: dict[str, FinancialPeriod] = {}
        keys: set[PeriodKey] = set()
        for period in report.periods:
            if period.company_name.strip() != self.company_name:
                raise HistoryWorkspaceError("Unternehmen stimmt nicht mit der ausdrücklich bestätigten Historie überein.")
            if period.currency != self.currency or period.scale != self.scale:
                raise HistoryWorkspaceError("Währung oder Skalierung des Berichts stimmt nicht mit der Historie überein.")
            key = period_key_for(period)
            if key in keys or period.period_label in by_label:
                raise HistoryWorkspaceError("Der Bericht enthält eine doppelte oder unklare wirtschaftliche Periode.")
            keys.add(key)
            by_label[period.period_label] = period
        precisions, priorities = dict(report.precisions), dict(report.source_priorities)
        expected: set[PrecisionKey] = set()
        wrapped: list[MetricObservation] = []
        for index, observation in enumerate(report.observations):
            if not isinstance(observation, ConfirmedMetricObservation):
                raise HistoryWorkspaceError("Nur ausdrücklich bestätigte Observations dürfen zur Historie gehören.")
            period = by_label.get(observation.period_label)
            if period is None:
                raise HistoryWorkspaceError("Observation gehört zu keiner bestätigten Periode dieses Berichts.")
            scale = "unit" if observation.canonical_metric in EPS_METRICS else self.scale
            if observation.currency != self.currency or observation.scale != scale:
                raise HistoryWorkspaceError("Währung oder Skalierung der Observation stimmt nicht mit der Historie überein.")
            metadata_key = (observation.period_label, observation.canonical_metric)
            if metadata_key in expected:
                raise HistoryWorkspaceError("Ein Bericht darf pro Kennzahl und Periode nur einen bestätigten Quellwert enthalten.")
            expected.add(metadata_key)
            if getattr(period, observation.canonical_metric) != observation.value:
                raise HistoryWorkspaceError("Bestätigte Observation und Periodenwert widersprechen sich.")
            precision = precisions.get(metadata_key)
            if precision is not None:
                _validate_precision(observation.value, precision)
            priority = priorities.get(metadata_key, 6)
            if type(priority) is not int or not 1 <= priority <= 7:
                raise HistoryWorkspaceError("Die Quellenpriorität muss zwischen 1 und 7 liegen.")
            identity = repr((report.report_id, str(period_key_for(period)), index, observation))
            wrapped.append(MetricObservation(sha256(identity.encode("utf-8")).hexdigest()[:24], report.report_id,
                                              period_key_for(period), observation, precision, priority))
        if set(precisions) - expected or set(priorities) - expected:
            raise HistoryWorkspaceError("Präzisions-/Quellenmetadaten gehören zu keiner bestätigten Observation.")
        for period in report.periods:
            for metric in SUPPORTED_METRICS:
                if getattr(period, metric) is not None and (period.period_label, metric) not in expected:
                    raise HistoryWorkspaceError("Jeder vorhandene Periodenwert benötigt eine bestätigte Observation.")
        return tuple(wrapped)

    def add_periods(self, periods: Sequence[FinancialPeriod], report_id: str) -> "HistoryWorkspace":
        """Adapter für ausdrücklich bestätigte manuelle Perioden ohne PDF-Quelle."""
        snapshot = tuple(periods)
        observations = tuple(ConfirmedMetricObservation(
            metric, period.period_label, getattr(period, metric), period.currency,
            "unit" if metric in EPS_METRICS else period.scale, "confirmed",
        ) for period in snapshot for metric in SUPPORTED_METRICS if getattr(period, metric) is not None)
        return self.add_report(FinancialHistory(snapshot), observations, report_id)

    def resolve(
        self, period_key: PeriodKey, metric: str, observation_id: str | None, reason: str = "",
    ) -> "HistoryWorkspace":
        """Wähle eine Quelle oder lasse die Abweichung ausdrücklich noch offen."""
        previous = self.get_resolution(period_key, metric)
        if not isinstance(reason, str):
            raise HistoryWorkspaceError("Ein Entscheidungsgrund muss Text sein.")
        if observation_id is None:
            decision = _automatic_resolution(period_key, metric, previous.observations)
            if decision.status == "resolved":
                decision = replace(decision, status="unresolved", selected_observation_id=None)
            decision = replace(decision, reason=reason or "Noch keine Quelle ausgewählt.")
            action = "resolution_deferred"
        else:
            if not any(item.observation_id == observation_id for item in previous.observations):
                raise HistoryWorkspaceError("Die gewählte Observation gehört nicht zu dieser Kennzahl und Periode.")
            decision = replace(previous, status="resolved", selected_observation_id=observation_id, reason=reason.strip())
            action = "source_selected"
        event = ResolutionEvent(action, period_key, metric, observation_id, previous.selected_observation_id, reason.strip())
        return replace(self, resolutions=tuple(decision if item is previous else item for item in self.resolutions),
                       events=self.events + (event,))

    def to_financial_history(self) -> FinancialHistory:
        """Übersetze nur verfügbare Werte; ungeklärte Kennzahlen bleiben None."""
        periods = []
        originals = tuple(next(period for report in self.reports for period in report.periods
                               if period_key_for(period) == key) for key in self.period_keys)
        labels = tuple(period.period_label.casefold() for period in originals)
        used_labels: set[str] = set()
        for key, original in zip(self.period_keys, originals):
            label = original.period_label
            if labels.count(label.casefold()) > 1:
                label = f"{label} ({key.period_end.isoformat()}, {key.period_months} Monate)"
            # Auch ein absichtlich gleich benanntes, natürliches Label darf
            # eine bereits erzeugte Anzeigespalte nicht überschreiben.
            base_label = label
            suffix = 0
            while label.casefold() in used_labels:
                suffix += 1
                label = f"{base_label} [{key}]" if suffix == 1 else f"{base_label} [{key}, {suffix}]"
            used_labels.add(label.casefold())
            values = {item.canonical_metric: item.resolved_value for item in self.resolutions if item.period_key == key}
            periods.append(FinancialPeriod(self.company_name, label, key.period_end,
                                           key.period_months, self.currency, self.scale,
                                           source=SourceMetadata(user_confirmed=True), **values))
        return FinancialHistory(tuple(periods))
