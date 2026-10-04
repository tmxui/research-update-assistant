"""Lade und validiere Research-Schwellen ohne Streamlit oder Finanzberechnungen."""

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Literal

import yaml


class FlagConfigError(ValueError):
    """Die Research-Konfiguration fehlt oder enthält ungültige Regeln."""


@dataclass(frozen=True)
class RuleThresholds:
    """Gelbe und rote Schwelle in der dokumentierten Einheit der jeweiligen Regel."""

    yellow: float
    red: float


@dataclass(frozen=True)
class PositiveThresholds:
    """Schwellen für drei gezielte positive Beobachtungen."""

    ebit_margin_increase_bps: float
    free_cash_flow_growth: float
    leverage_decrease: float


@dataclass(frozen=True)
class FlagRules:
    """Geprüfte Konfiguration; die Engine erhält sie ausdrücklich als Argument."""

    revenue_decline: RuleThresholds
    ebit_margin_decline: RuleThresholds
    ebitda_margin_decline: RuleThresholds
    free_cash_flow_decline: RuleThresholds
    ebit_growth_lag: RuleThresholds
    inventory_growth_excess: RuleThresholds
    receivables_growth_excess: RuleThresholds
    leverage_increase: RuleThresholds
    leverage_level: RuleThresholds
    cashflow_ebit_divergence: RuleThresholds
    positive: PositiveThresholds


# Nur erwartete Regeln und Prüfrichtung, keine finanziellen Schwellenwerte.
_RULE_DIRECTIONS = (
    ("revenue_decline", "below"),
    ("ebit_margin_decline", "below"),
    ("ebitda_margin_decline", "below"),
    ("free_cash_flow_decline", "below"),
    ("ebit_growth_lag", "below"),
    ("inventory_growth_excess", "above"),
    ("receivables_growth_excess", "above"),
    ("leverage_increase", "above"),
    ("leverage_level", "above"),
    ("cashflow_ebit_divergence", "below"),
)


class _UniqueKeyLoader(yaml.SafeLoader):
    """Verhindere das stille Überschreiben doppelter YAML-Schlüssel."""


def _unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict:
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise FlagConfigError("YAML-Schlüssel müssen eindeutige Texte sein.")
        result[key] = loader.construct_object(value_node)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping
)


def _mapping(value: object, name: str, keys: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise FlagConfigError(
            f"{name} muss genau diese Schlüssel enthalten: {', '.join(sorted(keys))}."
        )
    return value


def _number(value: object, name: str) -> float:
    if type(value) not in (int, float):
        raise FlagConfigError(f"{name} muss eine endliche Zahl sein.")
    try:
        number = float(value)
    except OverflowError as error:
        raise FlagConfigError(f"{name} liegt ausserhalb des Zahlenbereichs.") from error
    if not isfinite(number):
        raise FlagConfigError(f"{name} muss eine endliche Zahl sein.")
    return number


def _thresholds(
    value: object, name: str, direction: Literal["below", "above"]
) -> RuleThresholds:
    data = _mapping(value, f"rules.{name}", {"yellow", "red"})
    yellow = _number(data["yellow"], f"rules.{name}.yellow")
    red = _number(data["red"], f"rules.{name}.red")
    ordered = red < yellow <= 0 if direction == "below" else 0 < yellow < red
    if not ordered:
        required = "red < yellow <= 0" if direction == "below" else "0 < yellow < red"
        raise FlagConfigError(f"rules.{name}: Erforderlich ist {required}.")
    if direction == "below" and name not in ("revenue_decline", "cashflow_ebit_divergence") and yellow == 0:
        raise FlagConfigError(f"rules.{name}.yellow muss kleiner als null sein.")
    return RuleThresholds(yellow, red)


def load_flag_rules(path: Path | None = None) -> FlagRules:
    """Lade UTF-8-YAML sicher und ohne Ersatzschwellen bei Fehlern.

Der Standardpfad wird vom Projekt abgeleitet. Ein anderer Pfad erlaubt später
sektor- oder analystenspezifische Konfigurationen mit derselben Engine.
"""
    if path is None:
        path = Path(__file__).resolve().parents[2] / "config" / "flag_rules.yaml"
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.load(text, Loader=_UniqueKeyLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise FlagConfigError(
            f"Research-Konfiguration {path.name} konnte nicht gelesen werden. "
            "Bitte Datei und YAML-Syntax prüfen."
        ) from error
    root = _mapping(data, "Konfiguration", {"schema_version", "rules", "positive"})
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise FlagConfigError("Die Research-Konfiguration benötigt schema_version: 1.")
    rules = _mapping(root["rules"], "rules", {name for name, _ in _RULE_DIRECTIONS})
    checked = {
        name: _thresholds(rules[name], name, direction)
        for name, direction in _RULE_DIRECTIONS
    }
    positive_keys = {"ebit_margin_increase_bps", "free_cash_flow_growth", "leverage_decrease"}
    positive = _mapping(root["positive"], "positive", positive_keys)
    values = {name: _number(value, f"positive.{name}") for name, value in positive.items()}
    if any(value <= 0 for value in values.values()):
        raise FlagConfigError("Positive Schwellenwerte müssen grösser als null sein.")
    return FlagRules(**checked, positive=PositiveThresholds(**values))
