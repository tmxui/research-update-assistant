"""Zeige die synthetische Historie und zwei Vergleiche im Terminal.

Die erwähnten PDF-Namen sind fiktive Herkunftsbeispiele. Es werden nur
JSON-Daten gelesen, keine PDF-Dateien. Formatierung ist nur Ausgabeformatierung.
"""

import json
from datetime import date
from pathlib import Path

from research_update_assistant.calculations import compare_periods
from research_update_assistant.history import FinancialHistory
from research_update_assistant.models import FinancialPeriod, SourceMetadata


def load_synthetic_history() -> FinancialHistory:
    """Lade die drei Beispieldatensätze ohne Finanz- oder Konfliktlogik."""
    data_path = Path(__file__).resolve().parents[1] / "sample_data" / "synthetic_periods.json"
    records = json.loads(data_path.read_text(encoding="utf-8"))
    history = FinancialHistory()
    for record in records:
        record["period_end"] = date.fromisoformat(record["period_end"])
        source = record.pop("source", None)
        record["source"] = None if source is None else SourceMetadata(**source)
        history.add_period(FinancialPeriod(**record))
    return history


def main() -> None:
    """Verwende dieselbe Vergleichsfunktion für beide benachbarten Jahrespaare."""
    history = load_synthetic_history()
    print("Synthetische Historie (CHF Millionen):")
    for period in history.periods:
        print(f"  {period.period_label}: {period.period_end}, {period.period_months} Monate")

    for previous, current in zip(history.periods, history.periods[1:]):
        comparison = compare_periods(current, previous)
        before = comparison.previous_metrics
        after = comparison.current_metrics
        print(f"\n{current.period_label} vs. {previous.period_label}:")
        # Für diese vollständig vorgegebenen Beispiele sind die Werte vorhanden.
        print(f"  Umsatzwachstum: {comparison.revenue_growth:+.4%}")
        print(f"  EBITDA-Wachstum: {comparison.ebitda_growth:+.4%}")
        print(f"  EBIT-Marge: {before.ebit_margin:.4%} → {after.ebit_margin:.4%}")
        print(f"  EBIT-Margenänderung: {comparison.ebit_margin_change_bps:+.4f} Basispunkte")
        print(f"  Berechneter FCF: {before.calculated_free_cash_flow:g} → {after.calculated_free_cash_flow:g}")
        print(f"  FCF-Wachstum: {comparison.calculated_free_cash_flow_growth:+.4%}")
        print(f"  Berechnete Nettoverschuldung: {before.calculated_net_debt:g} → {after.calculated_net_debt:g}")
        print(f"  Net Debt / EBITDA: {before.calculated_net_debt_to_ebitda:.6f}x → {after.calculated_net_debt_to_ebitda:.6f}x")
        print(f"  Leverage-Änderung: {comparison.calculated_net_debt_to_ebitda_change:+.6f}x")


if __name__ == "__main__":
    main()
