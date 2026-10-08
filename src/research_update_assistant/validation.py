"""Explizit bestätigte Kennzahlen mit getrenntem, unveränderlichem Audit-Trail.

Ein Extraktionskandidat ist noch keine Finanzperiode. Nur die nach einem
Bestätigungsschritt erzeugten Observations dürfen in die normalisierte Historie.
Unterschiedliche Quellen derselben Kennzahl werden niemals automatisch ersetzt.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Literal

from .candidate_models import BBox, FinancialMetricCandidate, PeriodValueCandidate
from .calculations import calculate_gross_debt
from .history import FinancialHistory
from .input_parsing import CURRENCIES, SCALE_OPTIONS, NumberParsingError, parse_optional_number
from .models import FinancialPeriod, SourceMetadata


SUPPORTED_METRICS = (
    "revenue", "ebitda", "adjusted_ebitda", "ebit", "adjusted_ebit", "net_income",
    "basic_eps", "diluted_eps", "operating_cash_flow", "capex",
    "reported_free_cash_flow", "cash", "current_financial_debt",
    "noncurrent_financial_debt", "gross_debt", "reported_net_debt",
    "inventory", "receivables", "payables", "total_assets", "equity",
)
EPS_METRICS = ("basic_eps", "diluted_eps")
ConfirmationStatus = Literal["confirmed", "changed"]


class CandidateValidationError(ValueError):
    """Ein bestätigter Wert benötigt eine eindeutige Zuordnung oder Korrektur."""


@dataclass(frozen=True)
class ConfirmedMetricObservation:
    """Eine bestätigte Kennzahl für eine Periode samt ursprünglicher Extraktion.

    EPS verwendet scale='unit' (Währungsbetrag je Aktie), auch wenn die übrigen
    Periodenwerte in Millionen vorliegen. PDF-Seiten sind einsbasiert. Manuelle
    Ergänzungen erhalten keine erfundene PDF-Herkunft. Der Audit-Trail bleibt
    ausserhalb des einfachen numerischen FinancialPeriod-Datenmodells erhalten.
    """

    canonical_metric: str
    period_label: str
    confirmed_value: float
    currency: str
    scale: str
    status: ConfirmationStatus
    original_extracted_value: float | None = None
    original_raw_value: str | None = None
    original_canonical_metric: str | None = None
    original_period_label: str | None = None
    original_currency: str | None = None
    original_scale: str | None = None
    candidate_id: str | None = None
    source_document: str | None = None
    page_number: int | None = None
    reported_label: str | None = None
    source_snippet: str | None = None
    extraction_method: str = "manual"
    bbox: BBox | None = None

    def __post_init__(self) -> None:
        _validate_metric_and_units(self.canonical_metric, self.currency, self.scale)
        _validate_label(self.period_label)
        if self.status not in ("confirmed", "changed"):
            raise CandidateValidationError("Nur bestätigte oder geänderte Werte sind erlaubt.")
        for value in (self.confirmed_value, self.original_extracted_value):
            if value is not None and (type(value) not in (int, float) or not isfinite(value)):
                raise CandidateValidationError("Bestätigte Werte müssen endliche Zahlen sein.")
        if self.confirmed_value is None:
            raise CandidateValidationError("Ein fehlender Wert ist keine bestätigte Observation.")
        if self.canonical_metric in EPS_METRICS and self.scale != "unit":
            raise CandidateValidationError("EPS muss als Währungsbetrag je Aktie bestätigt werden.")
        if self.page_number is not None and (type(self.page_number) is not int or self.page_number < 1):
            raise CandidateValidationError("Die PDF-Seitennummer muss positiv sein.")

    @property
    def value(self) -> float:
        """Kurzer Zugriff auf den bestätigten, für Berechnungen nutzbaren Wert."""
        return self.confirmed_value

    @property
    def original_value(self) -> float | None:
        """Ursprünglicher Parserwert vor einer manuellen Korrektur."""
        return self.original_extracted_value


@dataclass(frozen=True)
class ConfirmedPeriodMetadata:
    """Vom Nutzer bestätigte Periodenbezeichnung, Stichtag und Monatsanzahl."""

    period_label: str
    period_end: date
    period_months: int

    def __post_init__(self) -> None:
        _validate_label(self.period_label)
        if type(self.period_end) is not date:
            raise CandidateValidationError("Bitte einen gültigen Periodenstichtag bestätigen.")
        if type(self.period_months) is not int or self.period_months not in (6, 12):
            raise CandidateValidationError("Phase 5B unterstützt Jahres- oder Halbjahresperioden.")


def _validate_label(label: str) -> None:
    if not isinstance(label, str) or not label.strip() or label != label.strip():
        raise CandidateValidationError("Bitte eine eindeutige, nicht leere Periodenbezeichnung eingeben.")


def _validate_metric_and_units(metric: str, currency: str, scale: str) -> None:
    if metric not in SUPPORTED_METRICS:
        raise CandidateValidationError(f"Die Kennzahl {metric!r} wird nicht unterstützt.")
    if currency not in CURRENCIES:
        raise CandidateValidationError("Bitte CHF, EUR oder USD als Währung bestätigen.")
    if scale not in dict(SCALE_OPTIONS):
        raise CandidateValidationError("Bitte eine gültige Skalierung bestätigen.")


def _parse_confirmed_values(values: Mapping[str, str]) -> dict[str, float]:
    parsed: dict[str, float] = {}
    labels: set[str] = set()
    for label, text in values.items():
        _validate_label(label)
        if label.casefold() in labels:
            raise CandidateValidationError("Periodenbezeichnungen müssen eindeutig sein.")
        labels.add(label.casefold())
        if not isinstance(text, str):
            raise CandidateValidationError("Bestätigte Eingaben müssen als Zahlentext vorliegen.")
        try:
            value = parse_optional_number(text)
        except NumberParsingError as error:
            raise CandidateValidationError(f"Ungültiger Wert für {label}: {error}") from error
        if value is not None:
            parsed[label] = value
    return parsed


def _original_value(
    candidate: FinancialMetricCandidate,
    label: str,
    period_assignments: Mapping[str, int | None] | None,
) -> PeriodValueCandidate | None:
    if period_assignments is not None and label in period_assignments:
        index = period_assignments[label]
        if index is None:
            return None
        if type(index) is not int or not 0 <= index < len(candidate.values):
            raise CandidateValidationError("Die gewählte ursprüngliche Wertespalte existiert nicht.")
        return candidate.values[index]
    matches = tuple(value for value in candidate.values if value.period_label == label)
    if len(matches) != 1:
        raise CandidateValidationError(
            f"Die ursprüngliche Wertespalte für {label} ist unklar. "
            "Bitte die Periodenzuordnung ausdrücklich bestätigen."
        )
    return matches[0]


def confirm_candidate(
    candidate: FinancialMetricCandidate,
    *,
    values: Mapping[str, str],
    currency: str,
    scale: str,
    canonical_metric: str | None = None,
    period_assignments: Mapping[str, int | None] | None = None,
) -> tuple[ConfirmedMetricObservation, ...]:
    """Bestätige einen geprüften Kandidaten, ohne bereits Perioden zu erzeugen.

    Die UI ruft diese Funktion erst nach ausdrücklicher Nutzerbestätigung auf.
    Bei unbekannten bzw. geänderten Perioden verbindet period_assignments die
    bestätigten Labels mit den ursprünglichen Wertespalten (nullbasierter Index).
    Ein ausdrücklich zugeordnetes None bezeichnet eine manuelle Ergänzung ohne
    extrahierten Rohwert und erzeugt entsprechend keine PDF-Quellenbehauptung.
    Leerwerte werden übersprungen; der ursprüngliche Rohwert bleibt unverändert.
    """
    if not isinstance(candidate, FinancialMetricCandidate):
        raise TypeError("Bitte einen FinancialMetricCandidate bestätigen.")
    if candidate.is_segment:
        raise CandidateValidationError("Segmentwerte dürfen nicht als Konzernwerte übernommen werden.")
    metric = candidate.canonical_metric if canonical_metric is None else canonical_metric
    _validate_metric_and_units(metric, currency, scale)
    final_scale = "unit" if metric in EPS_METRICS else scale
    observations: list[ConfirmedMetricObservation] = []
    original_indices: set[int] = set()
    for label, confirmed_value in _parse_confirmed_values(values).items():
        original = _original_value(candidate, label, period_assignments)
        if original is None:
            observations.append(ConfirmedMetricObservation(
                canonical_metric=metric, period_label=label, confirmed_value=confirmed_value,
                currency=currency, scale=final_scale, status="confirmed", extraction_method="manual",
            ))
            continue
        index = next(index for index, value in enumerate(candidate.values) if value is original)
        if index in original_indices:
            raise CandidateValidationError("Eine ursprüngliche Wertespalte darf nur einer Periode zugeordnet werden.")
        original_indices.add(index)
        changed = (
            confirmed_value != original.normalized_value
            or metric != candidate.canonical_metric
            or label != original.period_label
            or currency != candidate.currency
            or final_scale != candidate.scale
        )
        observations.append(ConfirmedMetricObservation(
            canonical_metric=metric, period_label=label, confirmed_value=confirmed_value,
            currency=currency, scale=final_scale, status="changed" if changed else "confirmed",
            original_extracted_value=original.normalized_value,
            original_raw_value=original.raw_value,
            original_canonical_metric=candidate.canonical_metric,
            original_period_label=original.period_label,
            original_currency=candidate.currency, original_scale=candidate.scale,
            candidate_id=candidate.candidate_id, source_document=candidate.source_document,
            page_number=candidate.page_number, reported_label=candidate.reported_label,
            source_snippet=candidate.source_snippet, extraction_method=candidate.extraction_method,
            bbox=original.bbox if original.bbox is not None else candidate.bbox,
        ))
    return tuple(observations)


def confirm_manual_metric(
    metric: str,
    *,
    values: Mapping[str, str],
    currency: str,
    scale: str,
) -> tuple[ConfirmedMetricObservation, ...]:
    """Bestätige manuelle Ergänzungen ohne eine PDF-Quelle vorzutäuschen."""
    _validate_metric_and_units(metric, currency, scale)
    final_scale = "unit" if metric in EPS_METRICS else scale
    return tuple(
        ConfirmedMetricObservation(
            canonical_metric=metric, period_label=label, confirmed_value=value,
            currency=currency, scale=final_scale, status="confirmed", extraction_method="manual",
        )
        for label, value in _parse_confirmed_values(values).items()
    )


def derive_gross_debt_observations(
    observations: Sequence[ConfirmedMetricObservation],
) -> tuple[ConfirmedMetricObservation, ...]:
    """Leite Bruttoschulden nur aus zwei kompatiblen, bestätigten Komponenten ab.

    Die beiden ursprünglichen Observations bleiben vollständig erhalten. Die
    zusätzliche Observation ist ausdrücklich als ``derived`` gekennzeichnet und
    behauptet keine eigene PDF-Seite oder Originalbezeichnung. Ein direkt
    bestätigter gross_debt-Wert hat Vorrang.
    """
    if any(not isinstance(item, ConfirmedMetricObservation) for item in observations):
        raise TypeError("Unbestätigte Kandidaten dürfen nicht als Finanzdaten übernommen werden.")
    result = list(observations)
    labels = tuple(dict.fromkeys(item.period_label for item in observations))
    for label in labels:
        period_items = tuple(item for item in observations if item.period_label == label)
        if any(item.canonical_metric == "gross_debt" for item in period_items):
            continue
        current = tuple(
            item for item in period_items if item.canonical_metric == "current_financial_debt"
        )
        noncurrent = tuple(
            item for item in period_items if item.canonical_metric == "noncurrent_financial_debt"
        )
        if len(current) != 1 or len(noncurrent) != 1:
            continue
        short_term, long_term = current[0], noncurrent[0]
        if (short_term.currency, short_term.scale) != (long_term.currency, long_term.scale):
            continue
        derived_value = calculate_gross_debt(
            short_term.confirmed_value, long_term.confirmed_value,
        )
        result.append(ConfirmedMetricObservation(
            canonical_metric="gross_debt",
            period_label=label,
            confirmed_value=derived_value,
            currency=short_term.currency,
            scale=short_term.scale,
            status="confirmed",
            source_snippet=(
                "Abgeleitet aus kurzfristigen und langfristigen Finanzverbindlichkeiten."
            ),
            extraction_method="derived",
        ))
    return tuple(result)


def create_confirmed_history(
    company_name: str,
    currency: str,
    scale: str,
    periods: Sequence[ConfirmedPeriodMetadata],
    observations: Sequence[ConfirmedMetricObservation],
) -> FinancialHistory:
    """Übernimm ausschliesslich bestätigte Werte in dieselbe bestehende Engine.

    Quellen und Korrekturen bleiben in den separat aufzubewahrenden Observations.
    Zwei Quellen für dieselbe Kennzahl/Periode sind ein offener Auswahlkonflikt,
    auch wenn die Werte zufällig gleich sind. Es gibt keine stille Umrechnung.
    """
    _validate_metric_and_units("revenue", currency, scale)
    if not isinstance(company_name, str) or not company_name.strip():
        raise CandidateValidationError("Bitte einen Unternehmensnamen bestätigen.")
    if len(periods) < 2:
        raise CandidateValidationError("Bitte mindestens zwei vergleichbare Perioden bestätigen.")
    if any(not isinstance(period, ConfirmedPeriodMetadata) for period in periods):
        raise TypeError("Periodenmetadaten müssen ausdrücklich bestätigt sein.")
    labels = [period.period_label for period in periods]
    if len(set(label.casefold() for label in labels)) != len(labels):
        raise CandidateValidationError("Periodenbezeichnungen müssen eindeutig sein.")
    if len({period.period_end for period in periods}) != len(periods):
        raise CandidateValidationError("Die bestätigten Perioden müssen unterschiedliche Stichtage besitzen.")
    if len({period.period_months for period in periods}) != 1:
        raise CandidateValidationError("Jahres- und Halbjahresperioden dürfen nicht direkt verglichen werden.")
    if any(not isinstance(item, ConfirmedMetricObservation) for item in observations):
        raise TypeError("Unbestätigte Kandidaten dürfen nicht als Finanzdaten übernommen werden.")
    values: dict[str, dict[str, float]] = {label: {} for label in labels}
    enriched_observations = derive_gross_debt_observations(observations)
    for observation in enriched_observations:
        if not isinstance(observation, ConfirmedMetricObservation):
            raise TypeError("Unbestätigte Kandidaten dürfen nicht als Finanzdaten übernommen werden.")
        if observation.period_label not in values:
            raise CandidateValidationError(f"Die Periode {observation.period_label} wurde nicht bestätigt.")
        expected_scale = "unit" if observation.canonical_metric in EPS_METRICS else scale
        if observation.currency != currency or observation.scale != expected_scale:
            raise CandidateValidationError(
                f"Währung oder Skalierung von {observation.canonical_metric} in "
                f"{observation.period_label} stimmt nicht mit den bestätigten Einheiten überein."
            )
        period_values = values[observation.period_label]
        if observation.canonical_metric in period_values:
            raise CandidateValidationError(
                f"Für {observation.canonical_metric} in {observation.period_label} wurden mehrere "
                "Quellen bestätigt. Bitte eine Quelle ausdrücklich auswählen."
            )
        period_values[observation.canonical_metric] = observation.confirmed_value
    return FinancialHistory(tuple(
        FinancialPeriod(
            company_name=company_name.strip(), period_label=period.period_label,
            period_end=period.period_end, period_months=period.period_months,
            currency=currency, scale=scale, source=SourceMetadata(user_confirmed=True),
            **values[period.period_label],
        )
        for period in periods
    ))
