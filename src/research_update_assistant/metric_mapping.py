"""Prüfbare Kennzahlen-Synonyme, ohne PDF-, UI- oder Berechnungsabhängigkeit."""

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
import re
import unicodedata

import yaml

from .candidate_models import Confidence, StatementType


class MetricConfigError(ValueError):
    """Die Kennzahlen-Konfiguration ist unvollständig oder mehrdeutig."""


@dataclass(frozen=True)
class MetricDefinition:
    """Stabile ID, deutsche Anzeige und zulässige vollständige Synonyme."""

    canonical_metric: str
    display_name_de: str
    statement_type: StatementType
    synonyms: tuple[str, ...]


@dataclass(frozen=True)
class MetricConfig:
    """Explizit übergebene, unveränderliche Mapping-Konfiguration."""

    metrics: tuple[MetricDefinition, ...]


@dataclass(frozen=True)
class MetricMatch:
    """Eine transparente Zuordnung; keine Wahrscheinlichkeit oder Bestätigung."""

    canonical_metric: str
    display_name_de: str
    statement_type: StatementType
    confidence: Confidence
    reasons: tuple[str, ...]
    is_segment: bool = False


_EXPECTED_METRICS = (
    "revenue", "ebitda", "adjusted_ebitda", "ebit", "adjusted_ebit",
    "net_income", "basic_eps", "diluted_eps", "operating_cash_flow", "capex",
    "reported_free_cash_flow", "cash", "gross_debt", "reported_net_debt",
    "inventory", "receivables", "payables", "total_assets", "equity",
)
_ADJUSTED = re.compile(r"\b(?:bereinigt\w*|adjusted|vor sondereffekten|vor einmaleffekten)\b")
_CONSOLIDATED_SUFFIXES = ("konzern", "gruppe", "group", "des konzerns", "der gruppe", "konsolidiert", "consolidated")
_EMPLOYEE_QUALIFIER = re.compile(r"\b(?:(?:pro|je) (?:beschäftigt\w*|mitarbeiter\w*)|per employees?)\b")
_NARRATIVE_QUALIFIER = re.compile(r"\b(?:stieg|stiegen|sank|sanken|betrug|betragen|erhöhte|erhöhten|nahm|nahmen|verzeichnete|was|were|increased|decreased)\b")


def _is_unit_suffix(label: str) -> bool:
    """Eine reine Einheitsangabe ist kein Segment; keine Währung wird erfunden."""
    scale = r"(?:mio|millionen|million|tausend|thousand|mrd|milliarden|billion)"
    currency = r"(?:chf|eur|usd|mchf|meur|musd|tchf|teur|tusd)"
    return bool(re.fullmatch(rf"(?:in )?(?:{scale} )?{currency}(?: {scale})?(?: (?:je aktie|per share))?", label))


def normalize_metric_label(label: str) -> str:
    """Normalisiere Unicode, Grossschreibung und Trennzeichen, nie Zahlenwerte."""
    normalized = unicodedata.normalize("NFKC", label).casefold().strip()
    normalized = re.sub(r"[’‘`´]", "'", normalized)
    normalized = re.sub(r"[‐‑–—-]", " ", normalized)
    normalized = re.sub(r"[^\w\s']", " ", normalized)
    return " ".join(normalized.split())


def normalize_mapping_label(label: str) -> str:
    """Entferne dekorative PDF-Zeichen ausschliesslich für die Zuordnung.

    Private-use-/replacement-Glyphs und Linkpfeile sind keine Kennzahlenteile.
    Das Rohlabel bleibt beim Aufrufer erhalten. Zahlen werden bewusst nicht
    entfernt: Note-Referenzen erfordern einen separaten räumlichen Nachweis.
    """
    cleaned = "".join(
        character for character in label
        if unicodedata.category(character) != "Co"
        and character != "\ufffd"
        and not ("\u2190" <= character <= "\u21ff" or "\u2794" <= character <= "\u27bf")
    )
    return normalize_metric_label(cleaned)


class _UniqueKeyLoader(yaml.SafeLoader):
    """Doppelte YAML-Schlüssel werden nie still überschrieben."""


def _unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict:
    data = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in data:
            raise MetricConfigError("YAML-Schlüssel müssen eindeutige Texte sein.")
        data[key] = loader.construct_object(value_node)
    return data


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _require_mapping(value: object, name: str, keys: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise MetricConfigError(f"{name} muss genau diese Schlüssel enthalten: {', '.join(sorted(keys))}.")
    return value


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MetricConfigError(f"{name} muss ein nicht leerer Text sein.")
    return value.strip()


def load_metric_config(path: Path | None = None) -> MetricConfig:
    """Lade sicheres UTF-8-YAML; Fehler erzeugen keine versteckten Ersatzmappings."""
    if path is None:
        path = Path(__file__).resolve().parents[2] / "config" / "metrics.yaml"
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise MetricConfigError(f"Kennzahlen-Konfiguration {path.name} konnte nicht gelesen werden. Bitte Datei und YAML-Syntax prüfen.") from error
    root = _require_mapping(data, "Konfiguration", {"schema_version", "metrics"})
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise MetricConfigError("Die Kennzahlen-Konfiguration benötigt schema_version: 1.")
    entries = _require_mapping(root["metrics"], "metrics", set(_EXPECTED_METRICS))
    definitions = []
    synonym_owners: dict[str, str] = {}
    for metric_id, entry in entries.items():
        item = _require_mapping(entry, metric_id, {"display_name_de", "statement_type", "synonyms"})
        display = _require_text(item["display_name_de"], f"{metric_id}.display_name_de")
        statement = item["statement_type"]
        if statement not in ("income_statement", "balance_sheet", "cash_flow"):
            raise MetricConfigError(f"{metric_id}.statement_type ist ungültig.")
        synonyms = item["synonyms"]
        if not isinstance(synonyms, list) or not synonyms:
            raise MetricConfigError(f"{metric_id}.synonyms muss eine nicht leere Textliste sein.")
        checked = tuple(_require_text(value, f"{metric_id}.synonyms") for value in synonyms)
        for synonym in checked:
            normalized = normalize_metric_label(synonym)
            if not normalized:
                raise MetricConfigError(f"{metric_id}.synonyms enthält keine Kennzahlenbezeichnung.")
            owner = synonym_owners.get(normalized)
            if owner is not None and owner != metric_id:
                raise MetricConfigError(f"Synonym {synonym!r} gehört zu mehreren Kennzahlen ({owner}, {metric_id}).")
            synonym_owners[normalized] = metric_id
        definitions.append(MetricDefinition(metric_id, display, statement, checked))
    return MetricConfig(tuple(definitions))


def _match(definition: MetricDefinition, confidence: Confidence, *reasons: str, is_segment: bool = False) -> MetricMatch:
    return MetricMatch(definition.canonical_metric, definition.display_name_de, definition.statement_type, confidence, tuple(reasons), is_segment)


def _synonym_pairs(config: MetricConfig) -> tuple[tuple[str, MetricDefinition], ...]:
    return tuple((normalize_metric_label(synonym), definition) for definition in config.metrics for synonym in definition.synonyms)


def _suffix_match(label: str, synonyms: tuple[tuple[str, MetricDefinition], ...]) -> tuple[MetricDefinition, str] | None:
    """Nur ein vollständiges Label am Anfang ist zulässig, nie ein Teilwort."""
    matches = [(synonym, definition) for synonym, definition in synonyms if label.startswith(synonym + " ")]
    if not matches:
        return None
    synonym, definition = max(matches, key=lambda item: len(item[0]))
    return definition, label[len(synonym):].strip()


def map_metric_label(label: str, config: MetricConfig) -> MetricMatch | None:
    """Ordne ein Zeilenlabel konservativ zu und kennzeichne Segmentzusätze.

    Explizites EBIT/EBITDA schlägt alltagssprachliche Bezeichnungen. Adjusted
    wird stets getrennt gehalten. Widersprüchliche Kürzel bleiben ohne Zuordnung.
    Unspezifisches EPS bleibt offen, da basic und diluted verschiedene Werte sind.
    """
    normalized = normalize_mapping_label(label)
    if not normalized:
        return None
    # Je Beschäftigten ist eine abgeleitete Kennzahl, kein Konzernbetrag.
    # Die expliziten EPS-Bezeichnungen bleiben davon unabhängig zulässig.
    if _EMPLOYEE_QUALIFIER.search(normalized):
        return None
    # Prozent-/Wachstumszeilen und Quotienten sind keine absoluten Beträge.
    if "%" in label or re.search(r"\b(?:marge\w*|margin\w*|growth|\w*wachstum\w*|veränderung\w*|ratio|quote)\b", normalized):
        return None
    synonyms = _synonym_pairs(config)
    definitions = {definition.canonical_metric: definition for definition in config.metrics}
    # Vollständige Textsätze dürfen durch ein isoliertes EBIT/EBITDA oder einen
    # Synonym-Anfang weder zu einem sicheren Betrag noch zu einem Segment werden.
    if _NARRATIVE_QUALIFIER.search(normalized) or len(normalized.split()) > 14:
        return None
    abbreviations = set(re.findall(r"\b(?:ebitda|ebit)\b", normalized))
    if len(abbreviations) > 1:
        return None
    if abbreviations and "/" in label:
        return None
    if abbreviations:
        abbreviation = next(iter(abbreviations))
        metric_id = ("adjusted_" if _ADJUSTED.search(normalized) else "") + abbreviation
        definition = definitions[metric_id]
        if re.search(r"\b(?:segment\w*|region\w*|division\w*)\b", normalized):
            return _match(definition, "low", "Explizite Segment-/Regions-/Divisionsbezeichnung; keine Konzernzahl.", is_segment=True)
        exact = any(synonym == normalized and entry.canonical_metric == metric_id for synonym, entry in synonyms)
        if exact:
            return _match(definition, "high", "Explizite Finanzabkürzung bestimmt die Zuordnung.", "Vollständige Kennzahlenbezeichnung entspricht einem konfigurierten Synonym.")
        suffix = _suffix_match(normalized, synonyms)
        # Unbekannte Zusätze hinter einer vollständigen Kennzahl könnten Regionen
        # oder Segmente sein. Sie werden nicht als Konzernzahl übernommen.
        if suffix and suffix[0].canonical_metric == metric_id and suffix[1] not in _CONSOLIDATED_SUFFIXES and not _is_unit_suffix(suffix[1]):
            return _match(definition, "low", "Zusätzliche Segment-/Teilbereichsbezeichnung im Label; Konzernzuordnung nicht bestätigt.", is_segment=True)
        return _match(definition, "high", "Explizite Finanzabkürzung bestimmt die Zuordnung.", "Bereinigte Kennzahl bleibt separat." if metric_id.startswith("adjusted_") else "Ausgewiesene Kennzahl bleibt separat von bereinigten Werten.")
    exact = [(synonym, definition) for synonym, definition in synonyms if synonym == normalized]
    if exact:
        definition = exact[0][1]
        return _match(definition, "high", "Vollständige Kennzahlenbezeichnung entspricht einem konfigurierten Synonym.")
    suffix = _suffix_match(normalized, synonyms)
    if suffix:
        definition, remainder = suffix
        if remainder in _CONSOLIDATED_SUFFIXES:
            return _match(definition, "medium", "Synonym mit explizitem Konzern-/Gruppenzusatz.")
        if _is_unit_suffix(remainder):
            return _match(definition, "medium", "Vollständiges Kennzahlen-Synonym mit separater Einheitsangabe.")
        return _match(definition, "low", "Zusätzliche Segment-/Teilbereichsbezeichnung im Label; Konzernzuordnung nicht bestätigt.", is_segment=True)
    # Eine klare Adjusted-Bezeichnung darf niemals fuzzy auf reported fallen.
    if _ADJUSTED.search(normalized):
        return None
    fuzzy = [(SequenceMatcher(None, normalized, synonym).ratio(), definition) for synonym, definition in synonyms if len(synonym) >= 8 and len(normalized) >= 8]
    if not fuzzy:
        return None
    score, definition = max(fuzzy, key=lambda item: item[0])
    tied_ids = {item.canonical_metric for other_score, item in fuzzy if other_score >= score - 0.02}
    if score >= 0.90 and len(tied_ids) == 1:
        return _match(definition, "low", "Ähnliche Schreibweise eines Synonyms; Zuordnung muss geprüft werden.")
    return None
