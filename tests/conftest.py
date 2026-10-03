"""Frische synthetische Perioden für jeden Test, ohne globalen Datenzustand."""

import json
from datetime import date
from pathlib import Path

import pytest

from research_update_assistant.models import FinancialPeriod, SourceMetadata


@pytest.fixture
def periods() -> dict[str, FinancialPeriod]:
    """Lade die öffentlichen Projektbeispiele; jedes Testobjekt ist unabhängig."""
    path = Path(__file__).resolve().parents[1] / "sample_data" / "synthetic_periods.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    result = {}
    for record in records:
        record["period_end"] = date.fromisoformat(record["period_end"])
        record["source"] = SourceMetadata(**record["source"])
        period = FinancialPeriod(**record)
        result[period.period_label] = period
    return result
