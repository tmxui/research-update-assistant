"""YAML muss vollständig, sicher und eindeutig sein; keine stillen Defaults."""

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from research_update_assistant.flag_config import FlagConfigError, load_flag_rules


@pytest.fixture
def config_data():
    path = Path(__file__).resolve().parents[1] / "config" / "flag_rules.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_config(tmp_path, data):
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_default_config_loads_independently_of_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rules = load_flag_rules()
    assert rules.ebit_margin_decline.yellow == -100
    assert rules.ebit_margin_decline.red == -200
    assert rules.free_cash_flow_decline.red == -0.4
    assert rules.leverage_increase.yellow == 0.5
    assert rules.leverage_level.red == 4.0


def test_custom_config_path_loads_modified_threshold(config_data, tmp_path):
    config_data["rules"]["ebit_margin_decline"]["red"] = -250
    assert load_flag_rules(_write_config(tmp_path, config_data)).ebit_margin_decline.red == -250


def test_missing_config_has_readable_error(tmp_path):
    with pytest.raises(FlagConfigError, match="konnte nicht gelesen werden"):
        load_flag_rules(tmp_path / "missing.yaml")


@pytest.mark.parametrize("content", [
    "rules: [", "!!python/object/apply:os.system ['echo unsafe']", "schema_version: 1\nschema_version: 2\n",
])
def test_invalid_unsafe_or_duplicate_yaml_is_rejected(tmp_path, content):
    path = tmp_path / "rules.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(FlagConfigError):
        load_flag_rules(path)


def test_duplicate_nested_threshold_is_rejected(config_data, tmp_path):
    text = yaml.safe_dump(config_data).replace("yellow: -100", "yellow: -100\n    yellow: -50", 1)
    path = tmp_path / "rules.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(FlagConfigError, match="eindeutige"):
        load_flag_rules(path)


def test_non_utf8_config_is_rejected(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_bytes(b'\xff')
    with pytest.raises(FlagConfigError, match="YAML-Syntax"):
        load_flag_rules(path)


@pytest.mark.parametrize("data", [None, [], {"schema_version": 1}, {"schema_version": 1, "rules": {}, "positive": {}, "typo": 1}])
def test_invalid_root_shape_is_rejected(tmp_path, data):
    with pytest.raises(FlagConfigError, match="genau diese Schlüssel"):
        load_flag_rules(_write_config(tmp_path, data))


@pytest.mark.parametrize("version", [2, "1", True, None])
def test_schema_version_is_validated(tmp_path, config_data, version):
    config_data["schema_version"] = version
    with pytest.raises(FlagConfigError, match="schema_version"):
        load_flag_rules(_write_config(tmp_path, config_data))


@pytest.mark.parametrize("mutation", ["missing_rule", "unknown_rule", "missing_threshold", "unknown_threshold"])
def test_rule_and_threshold_keys_are_checked(tmp_path, config_data, mutation):
    if mutation == "missing_rule":
        config_data["rules"].pop("ebit_margin_decline")
    elif mutation == "unknown_rule":
        config_data["rules"]["typo"] = {"yellow": 1, "red": 2}
    elif mutation == "missing_threshold":
        config_data["rules"]["ebit_margin_decline"].pop("red")
    else:
        config_data["rules"]["ebit_margin_decline"]["typo"] = -250
    with pytest.raises(FlagConfigError, match="Schlüssel"):
        load_flag_rules(_write_config(tmp_path, config_data))


@pytest.mark.parametrize("value", ["-200", True, None, float('nan'), float('inf'), -float('inf'), 10**400])
def test_threshold_must_be_a_finite_number(tmp_path, config_data, value):
    config_data["rules"]["ebit_margin_decline"]["red"] = value
    with pytest.raises(FlagConfigError, match="Zahl|Zahlenbereich"):
        load_flag_rules(_write_config(tmp_path, config_data))


@pytest.mark.parametrize("name, thresholds", [
    ("ebit_margin_decline", {"yellow": -100, "red": -50}),
    ("ebit_margin_decline", {"yellow": -100, "red": -100}),
    ("ebit_margin_decline", {"yellow": 100, "red": 200}),
    ("ebit_margin_decline", {"yellow": 0, "red": -100}),
    ("leverage_increase", {"yellow": 1, "red": 0.5}),
    ("leverage_level", {"yellow": -3, "red": -4}),
])
def test_threshold_order_and_sign_are_validated(tmp_path, config_data, name, thresholds):
    config_data["rules"][name] = thresholds
    with pytest.raises(FlagConfigError):
        load_flag_rules(_write_config(tmp_path, config_data))


@pytest.mark.parametrize("value", [0, -1, "100", None])
def test_positive_thresholds_are_validated(tmp_path, config_data, value):
    config_data["positive"]["ebit_margin_increase_bps"] = value
    with pytest.raises(FlagConfigError):
        load_flag_rules(_write_config(tmp_path, config_data))


def test_missing_positive_rule_does_not_use_default(tmp_path, config_data):
    invalid = deepcopy(config_data)
    invalid["positive"].pop("leverage_decrease")
    with pytest.raises(FlagConfigError, match="positive"):
        load_flag_rules(_write_config(tmp_path, invalid))
