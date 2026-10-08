"""Konfigurierbare Schweizer Synonyme bleiben eindeutig und überprüfbar."""

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from research_update_assistant.metric_mapping import (
    MetricConfigError, load_metric_config, map_metric_label, normalize_mapping_label,
    normalize_metric_label,
)


@pytest.fixture
def metric_config():
    return load_metric_config()


@pytest.fixture
def config_data():
    path = Path(__file__).resolve().parents[1] / "config" / "metrics.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write(tmp_path, data):
    path = tmp_path / "metrics.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_all_configured_synonyms_map_to_their_own_metric(metric_config):
    for definition in metric_config.metrics:
        for synonym in definition.synonyms:
            match = map_metric_label(synonym, metric_config)
            assert match is not None, synonym
            assert match.canonical_metric == definition.canonical_metric, synonym
            assert match.confidence == "high"
            assert not match.is_segment
            assert match.reasons


@pytest.mark.parametrize("label,expected", [
    ("Nettoumsatz", "revenue"), ("  NETTO-UMSATZ  ", "revenue"),
    ("Betriebsergebnis (EBIT)", "ebit"), ("Betriebsgewinn (EBIT)", "ebit"),
    ("Operativer Cashflow (EBITDA)", "ebitda"), ("Operating Cash Flow (EBITDA)", "ebitda"),
    ("Nettomittelfluss aus/für (-) Geschäftstätigkeit", "operating_cash_flow"),
    ("Bereinigtes EBIT", "adjusted_ebit"), ("EBIT bereinigt", "adjusted_ebit"),
    ("Adjusted EBITDA", "adjusted_ebitda"), ("EBITDA vor Einmaleffekten", "adjusted_ebitda"),
    ("Shareholders’ Equity", "equity"), ("Ergebnis je Aktie", "basic_eps"),
    ("Gewinn je Aktie", "basic_eps"), ("EPS", "basic_eps"),
    ("Earnings per Share", "basic_eps"), ("Basic EPS", "basic_eps"),
    ("Basic Earnings per Share", "basic_eps"),
    ("Diluted EPS", "diluted_eps"),
    ("Diluted Earnings per Share", "diluted_eps"),
    ("Unverwässertes Ergebnis je Aktie", "basic_eps"),
    ("Verwässertes Ergebnis je Aktie", "diluted_eps"),
    ("Kurzfristige Finanzverbindlichkeiten", "current_financial_debt"),
    ("Current Borrowings", "current_financial_debt"),
    ("Langfristige Finanzverbindlichkeiten", "noncurrent_financial_debt"),
    ("Non-current Borrowings", "noncurrent_financial_debt"),
])
def test_priority_and_normalization_rules(metric_config, label, expected):
    match = map_metric_label(label, metric_config)
    assert match.canonical_metric == expected
    assert match.confidence == "high"


def test_explicit_ebitda_has_reason_and_wins_cashflow_word(metric_config):
    result = map_metric_label("Operativer Cashflow (EBITDA)", metric_config)
    assert result.canonical_metric == "ebitda"
    assert any("Finanzabkürzung" in reason for reason in result.reasons)


@pytest.mark.parametrize("label", ["Nettoumsatz Europa", "Nettoumsatz Deutschland", "Nettoumsatz Sanitärsysteme", "EBIT Europa", "Betriebsergebnis (EBIT) Europa"])
def test_segment_or_region_label_is_explicitly_marked(metric_config, label):
    match = map_metric_label(label, metric_config)
    assert match.is_segment
    assert match.confidence == "low"


@pytest.mark.parametrize("label,metric_id", [("Segment EBITDA", "ebitda"), ("Bereinigtes Segment EBIT", "adjusted_ebit"), ("Regional EBITDA", "ebitda"), ("Division EBIT", "ebit"), ("Operativer Cashflow Segment Europa (EBITDA)", "ebitda")])
def test_segment_prefix_cannot_be_hidden_by_explicit_abbreviation(metric_config, label, metric_id):
    match = map_metric_label(label, metric_config)
    assert match.canonical_metric == metric_id
    assert match.is_segment
    assert match.confidence == "low"


def test_explicit_consolidated_suffix_is_not_segment(metric_config):
    match = map_metric_label("Nettoumsatz der Gruppe", metric_config)
    assert match.canonical_metric == "revenue"
    assert not match.is_segment
    assert match.confidence == "medium"


@pytest.mark.parametrize("label,expected", [("Basic EPS (CHF)", "basic_eps"), ("EBIT in Mio. CHF", "ebit"), ("Nettoumsatz (MCHF)", "revenue"), ("Verwässertes Ergebnis je Aktie in CHF", "diluted_eps")])
def test_explicit_unit_suffix_does_not_become_segment(metric_config, label, expected):
    match = map_metric_label(label, metric_config)
    assert match.canonical_metric == expected
    assert not match.is_segment


@pytest.mark.parametrize("label", ["", "  ", "EBIT/EBITDA", "Veränderung der Vorräte", "Bereinigter Umsatz", "Revenuefulness", "EBIT-Marge", "Umsatzwachstum", "EBIT %", "EBITDA margin", "Net Debt / EBITDA", "Leasingverbindlichkeiten"])
def test_ambiguous_or_unknown_label_does_not_get_safe_mapping(metric_config, label):
    assert map_metric_label(label, metric_config) is None


def test_typo_is_low_confidence_with_reason(metric_config):
    match = map_metric_label("Nettoumsat", metric_config)
    assert match.canonical_metric == "revenue"
    assert match.confidence == "low"
    assert any("Schreibweise" in reason for reason in match.reasons)


def test_normalization_handles_unicode_apostrophes_and_spaces():
    assert normalize_metric_label(" Shareholders’  Equity ") == "shareholders' equity"
    assert normalize_metric_label("Netto–Umsatz") == "netto umsatz"


@pytest.mark.parametrize("glyph", ["\ue000", "\uf8ff", "\U000f0000", "\ufffd", "↗", "→", "➔"])
def test_pdf_decorative_glyphs_do_not_change_exact_mapping(metric_config, glyph):
    raw_label = f"Nettoumsatz {glyph}"
    assert normalize_mapping_label(raw_label) == "nettoumsatz"
    match = map_metric_label(raw_label, metric_config)
    assert match.canonical_metric == "revenue"
    assert match.confidence == "high"
    assert not match.is_segment
    assert raw_label.endswith(glyph)


def test_pdf_normalization_does_not_remove_unqualified_note_numbers():
    assert normalize_mapping_label("Nettoumsatz \ue000 28") == "nettoumsatz 28"
    assert normalize_mapping_label("Scope 3 Emissionen 2025") == "scope 3 emissionen 2025"


@pytest.mark.parametrize("label", [
    "Nettoumsatz pro Beschäftigten TCHF", "Nettoumsatz je Beschäftigten",
    "Umsatz pro Mitarbeiter", "Umsatz je Mitarbeiter", "Revenue per Employee",
    "Revenue per Employees (TCHF)", "EBITDA je Mitarbeiter", "EBIT pro Beschäftigtem",
])
def test_employee_derived_ratios_are_not_financial_period_metrics(metric_config, label):
    assert map_metric_label(label, metric_config) is None


@pytest.mark.parametrize("label", [
    "Der Nettoumsatz stieg im Jahr 2025 deutlich",
    "Nettoumsatz Umsatzwachstum deutlich über Marktentwicklung",
    "Nettoumsatz stieg im Berichtsjahr", "EBIT betrug im Berichtsjahr 143 MCHF",
    "Operativer Cashflow (EBITDA) nahm im Jahr 2025 zu",
])
def test_narrative_labels_do_not_become_exact_or_fake_segment_matches(metric_config, label):
    assert map_metric_label(label, metric_config) is None


def test_default_config_does_not_depend_on_current_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = load_metric_config()
    assert len(config.metrics) == 21
    assert {item.canonical_metric for item in config.metrics} >= {
        "basic_eps", "diluted_eps", "reported_free_cash_flow",
        "current_financial_debt", "noncurrent_financial_debt",
    }


def test_custom_synonym_is_used_without_changing_code(config_data, tmp_path):
    config_data["metrics"]["revenue"]["synonyms"].append("Synthetischer Verkaufserlös")
    config = load_metric_config(_write(tmp_path, config_data))
    assert map_metric_label("Synthetischer Verkaufserlös", config).canonical_metric == "revenue"


def test_missing_file_has_readable_error(tmp_path):
    with pytest.raises(MetricConfigError, match="konnte nicht gelesen werden"):
        load_metric_config(tmp_path / "missing.yaml")


@pytest.mark.parametrize("text", ["metrics: [", "!!python/object/apply:os.system ['echo unsafe']", "schema_version: 1\nschema_version: 1\n", "metrics:\n  revenue: 1\n  revenue: 2\n"])
def test_unsafe_invalid_or_duplicate_yaml_is_rejected(tmp_path, text):
    path = tmp_path / "metrics.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(MetricConfigError):
        load_metric_config(path)


def test_invalid_encoding_is_rejected(tmp_path):
    path = tmp_path / "metrics.yaml"
    path.write_bytes(b'\xff')
    with pytest.raises(MetricConfigError):
        load_metric_config(path)


@pytest.mark.parametrize("version", [None, True, "1", 2])
def test_schema_version_is_checked(config_data, tmp_path, version):
    config_data["schema_version"] = version
    with pytest.raises(MetricConfigError, match="schema_version"):
        load_metric_config(_write(tmp_path, config_data))


@pytest.mark.parametrize("mutation", ["missing_metric", "extra_metric", "missing_key", "extra_key", "empty_display", "invalid_statement", "empty_synonyms", "scalar_synonyms", "nontext_synonym", "empty_synonym", "punctuation_synonym", "ambiguous_synonym"])
def test_configuration_errors_are_rejected(config_data, tmp_path, mutation):
    data = deepcopy(config_data)
    if mutation == "missing_metric":
        data["metrics"].pop("revenue")
    elif mutation == "extra_metric":
        data["metrics"]["new_metric"] = deepcopy(data["metrics"]["revenue"])
    elif mutation == "missing_key":
        data["metrics"]["revenue"].pop("display_name_de")
    elif mutation == "extra_key":
        data["metrics"]["revenue"]["typo"] = 1
    elif mutation == "empty_display":
        data["metrics"]["revenue"]["display_name_de"] = " "
    elif mutation == "invalid_statement":
        data["metrics"]["revenue"]["statement_type"] = "quarterly_notes"
    elif mutation == "empty_synonyms":
        data["metrics"]["revenue"]["synonyms"] = []
    elif mutation == "scalar_synonyms":
        data["metrics"]["revenue"]["synonyms"] = "Umsatz"
    elif mutation == "nontext_synonym":
        data["metrics"]["revenue"]["synonyms"] = [123]
    elif mutation == "empty_synonym":
        data["metrics"]["revenue"]["synonyms"] = [" "]
    elif mutation == "punctuation_synonym":
        data["metrics"]["revenue"]["synonyms"] = ["..."]
    else:
        data["metrics"]["ebit"]["synonyms"].append(" Umsatz ")
    with pytest.raises(MetricConfigError):
        load_metric_config(_write(tmp_path, data))
