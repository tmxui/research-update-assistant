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


@pytest.fixture
def synthetic_pdf_bytes() -> bytes:
    """Drei synthetische Seiten mit Unicode-Text und einer gezeichneten Tabelle.

    Das PDF entsteht im Speicher; kein Unternehmensbericht und kein Download.
    Die mit PyMuPDF gelieferte Schrift vermeidet systemabhängige Font-Dateien.
    """
    import pymupdf

    font = pymupdf.Font("cjk")
    with pymupdf.open() as pdf:
        pdf.set_metadata({"title": "Synthetischer Geschäftsbericht 2025", "author": "Research Update Assistant"})
        texts = (
            "Synthetic Industrial AG - Geschäftsbericht 2025\n\n"
            "Dieses Dokument enthält ausschliesslich synthetische Beispieldaten.\n"
            "Es dient der Prüfung der technischen PDF-Extraktion und Quellenherkunft.\n"
            "Finanzzahlen werden hier nicht automatisch verstanden oder übernommen.\n"
            "Prüfbegriffe: Vorräte, flüssige Mittel, Änderung, CHF 1’100,5.\n"
            "Die folgenden Seiten zeigen Rohtext und eine einfache Tabelle.",
            "Erfolgsrechnung - synthetische Angaben in CHF Mio.\n\n"
            "Nettoumsatz 2025 1'100\nNettoumsatz 2024 1'000\n"
            "Betriebsgewinn (EBIT) 2025 143\nBetriebsgewinn (EBIT) 2024 150\n\n"
            "Diese Angaben sind frei erfunden und keine Unternehmensinformationen.\n"
            "Die Seite demonstriert mehrere Treffer für eine einfache Textsuche.\n"
            "Der Parser speichert Zeichen und Seitenherkunft, ohne Perioden zuzuordnen.\n"
            "Ausgewiesene Rohtexte bleiben erhalten; eine fachliche Prüfung folgt später.",
            "Synthetische Roh-Tabelle\n\n"
            "Die Tabelle dient ausschliesslich der Prüfung von Zeilen, Spalten und Quellen.\n"
            "Ihre erste Zeile bleibt eine gewöhnliche Rohzeile und wird nicht interpretiert.\n"
            "Die Tabellenposition ist auf dieser dritten PDF-Seite nachvollziehbar.\n"
            "Auch leere Zellen und Schweizer Zahlenformate sollen erhalten bleiben.",
        )
        for text in texts:
            page = pdf.new_page()
            page.insert_font(fontname="synthetic", fontbuffer=font.buffer)
            page.insert_text((45, 55), text, fontname="synthetic", fontsize=10, lineheight=1.6)
        page = pdf[2]
        x_positions = (45, 310, 410, 530)
        y_positions = (210, 245, 280, 315)
        for x in x_positions:
            page.draw_line((x, y_positions[0]), (x, y_positions[-1]))
        for y in y_positions:
            page.draw_line((x_positions[0], y), (x_positions[-1], y))
        rows = (("Rohbezeichnung", "2025", "2024"), ("Nettoumsatz", "1’100", "1'000"), ("EBIT", "143", "150"))
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                page.insert_text(
                    (x_positions[column] + 8, y_positions[row_index] + 22),
                    value, fontname="synthetic", fontsize=10,
                )
        pdf.set_page_labels([{"startpage": 0, "prefix": "S-", "style": "D", "firstpagenum": 1}])
        pdf.subset_fonts()
        return pdf.tobytes(garbage=4, deflate=True)
