"""Gemeinsamer Loader für die synthetischen JSON-Daten von UI und Terminal."""

import json
from datetime import date
from pathlib import Path

from .history import FinancialHistory
from .models import FinancialPeriod, SourceMetadata


def load_synthetic_history() -> FinancialHistory:
    """Lade die Beispieldaten inklusive ihrer fiktiven Source-Metadaten."""
    path = Path(__file__).resolve().parents[2] / "sample_data" / "synthetic_periods.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    history = FinancialHistory()
    for record in records:
        record["period_end"] = date.fromisoformat(record["period_end"])
        source = record.pop("source", None)
        record["source"] = None if source is None else SourceMetadata(**source)
        history.add_period(FinancialPeriod(**record))
    return history
