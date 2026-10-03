"""Prüfe Sortierung, Zugriff und Erhaltung widersprüchlicher Quelldatensätze."""

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from research_update_assistant.history import AmbiguousPeriodError, FinancialHistory
from research_update_assistant.models import SourceMetadata


def test_history_sorts_three_years_by_date(periods) -> None:
    history = FinancialHistory((periods["FY2025"], periods["FY2023"], periods["FY2024"]))
    assert [period.period_label for period in history.periods] == ["FY2023", "FY2024", "FY2025"]
    assert history.get_period("FY2024") is periods["FY2024"]


def test_add_period_keeps_chronological_order(periods) -> None:
    history = FinancialHistory()
    history.add_period(periods["FY2025"])
    history.add_period(periods["FY2023"])
    history.add_period(periods["FY2024"])
    assert history.periods == (periods["FY2023"], periods["FY2024"], periods["FY2025"])


def test_sort_uses_date_not_label(periods) -> None:
    early = replace(periods["FY2023"], period_label="Z")
    late = replace(periods["FY2025"], period_label="A")
    assert FinancialHistory((late, early)).periods == (early, late)


def test_duplicate_periods_are_preserved_with_provenance(periods) -> None:
    original = replace(periods["FY2024"], ebit=500, source=SourceMetadata(
        source_document="annual_report_2024.pdf", source_document_period="FY2024",
        reported_as_comparative=False,
    ))
    comparative = replace(original, ebit=485, source=SourceMetadata(
        source_document="annual_report_2025.pdf", source_document_period="FY2025",
        reported_as_comparative=True, restated=True,
    ))
    history = FinancialHistory((original,))
    history.add_period(comparative)
    matches = history.get_periods("FY2024")
    assert len(matches) == 2
    assert [period.ebit for period in matches] == [500, 485]
    assert [period.source.source_document for period in matches] == [
        "annual_report_2024.pdf", "annual_report_2025.pdf",
    ]
    with pytest.raises(AmbiguousPeriodError, match="2 Datensätze"):
        history.get_period("FY2024")


def test_same_label_does_not_assume_same_period_or_company(periods) -> None:
    another = replace(periods["FY2023"], period_label="FY2024", company_name="Other AG")
    history = FinancialHistory((periods["FY2024"], another))
    assert len(history.get_periods("FY2024")) == 2
    with pytest.raises(AmbiguousPeriodError):
        history.get_period("FY2024")


def test_missing_period_has_no_implicit_default(periods) -> None:
    history = FinancialHistory((periods["FY2024"],))
    assert history.get_periods("FY2030") == ()
    with pytest.raises(KeyError, match="FY2030"):
        history.get_period("FY2030")


def test_histories_do_not_share_mutable_state(periods) -> None:
    first = FinancialHistory()
    second = FinancialHistory()
    first.add_period(periods["FY2024"])
    assert second.periods == ()


def test_example_runs_and_shows_both_comparisons() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "examples" / "compare_synthetic_periods.py")],
        cwd=root, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert "FY2024 vs. FY2023" in result.stdout
    assert "FY2025 vs. FY2024" in result.stdout
    assert "-200.0000 Basispunkte" in result.stdout
