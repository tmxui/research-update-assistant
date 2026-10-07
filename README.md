# Research Update Assistant

Der **Research Update Assistant** ist ein Lern- und Portfolio-Projekt für einen
strukturierten Equity-Research-Workflow. Die lokale Streamlit-Anwendung extrahiert
Finanzdaten aus Geschäfts- und Ergebnisberichten, lässt sie durch einen Analysten
prüfen, baut eine mehrjährige Historie auf und erstellt kompakte Ergebnis-Updates.

Die Anwendung richtet sich in V1 vor allem an börsenkotierte Nicht-Finanzunternehmen
und deutsch- oder englischsprachige Berichte. Sie liefert nachvollziehbare Fakten
und **keine Investment-Empfehlung**.

## What it does

Ein Bericht kann Zahlen für mehrere Perioden enthalten. Der Assistant trennt daher
Dokumente, Perioden und einzelne Quellenbeobachtungen konsequent voneinander. Ein
Analyst bestätigt vorgeschlagene Werte, bevor sie in die Finanzhistorie gelangen.

Die App kann anschließend:

- bestätigte Finanzwerte aus mehreren Berichten zusammenführen,
- alternative Quellen und mögliche Restatements erhalten,
- bestehende Kennzahlen und Periodenvergleiche berechnen,
- ein kompaktes Ergebnis-Update erzeugen,
- manuelle Erwartungen und Unternehmens-Guidance gegenüberstellen,
- bestätigte Daten als modellfreundliche Excel- oder CSV-Datei exportieren.

Fehlende Werte bleiben `None` beziehungsweise leere Exportzellen. Ausgewiesene und
berechnete Kennzahlen werden nicht still miteinander vermischt.

## Why it exists

Ein Junior Equity Research Analyst verbringt nach einer Resultatpublikation viel
Zeit mit wiederkehrenden Schritten: Bericht durchsuchen, Zahlen übertragen,
Vergleichsperioden prüfen, Abweichungen berechnen und Quellen dokumentieren.
Dieses Projekt zeigt, wie sich diese Schritte technisch unterstützen lassen, ohne
die fachliche Kontrolle an eine Black Box abzugeben.

Der Human-in-the-loop-Ansatz ist zentral: Extraktion und Mapping liefern
Vorschläge. Die Verantwortung für Auswahl, Korrektur und Bestätigung bleibt beim
Analysten.

## Key features

- PDF-Text-, Tabellen- und Positionsauslesung mit technischer Qualitätsdiagnose
- konfigurierbares Mapping deutscher und englischer Finanzbegriffe
- explizite Bestätigung jeder übernommenen Kennzahl
- Provenance mit Dokument, PDF-Seite, Report-Label und Extraktionsmethode
- periodenorientierte Mehrbericht-Historie mit offener Konfliktbehandlung
- bestehende Finance Engine für Margen, Wachstum, Cashflow, Verschuldung und
  Working Capital
- kompaktes Ergebnis-Update plus ausführliche Detailanalyse
- regelbasierte Research-Prüfpunkte ohne Buy-/Sell-Aussagen
- manuelle Expectations- und Guidance-Snapshots
- In-Memory-Export nach XLSX und CSV
- vollständig synthetische automatisierte Testdaten

## Workflow

1. Einen öffentlichen Geschäfts-, Halbjahres- oder Ergebnisbericht hochladen.
2. Vorgeschlagene Finanzwerte und ihre PDF-Quellen prüfen.
3. Bestätigte Perioden zur Finanzhistorie hinzufügen.
4. Vergleichs- und Trendperioden wählen und das Ergebnis-Update ansehen.
5. Optional Erwartungen oder Unternehmens-Guidance ergänzen.
6. Bestätigte Daten und Quellen als Excel oder CSV exportieren.

Die manuelle Eingabe bleibt als alternativer Weg ohne PDF verfügbar.

## Architecture

```text
PDF
  → extraction
  → candidate mapping
  → analyst validation
  → history workspace
  → calculations
  → results update
  → expectations / guidance
  → export
```

Die Schichten haben getrennte Aufgaben:

- `pdf_extractor.py`, `layout_parser.py` und `financial_parser.py` lesen Dokumente
  und erzeugen unbestätigte Kandidaten.
- `validation.py` und `validation_ui.py` verwalten die Analystenprüfung und den
  Audit-Trail.
- `history_workspace.py` hält Reports, Perioden, Quellenalternativen und explizite
  Konfliktentscheidungen.
- `calculations.py`, `analysis_selection.py` und `flags.py` enthalten testbare
  Business-Logik ohne Streamlit-Abhängigkeit.
- `results_update.py` bereitet vorhandene Kennzahlen für die kompakte Darstellung
  vor; die Präsentationsschicht erfindet keine neuen Finanzformeln.
- `expectations.py` und `guidance.py` halten Schätzungen und Unternehmensaussagen
  fachlich getrennt.
- `exports.py` erzeugt XLSX und CSV direkt im Arbeitsspeicher.

## Example use case

Ein öffentlicher Geberit-Geschäftsbericht 2025 enthält FY2025 und die
Vergleichsperiode FY2024. Der Bericht 2024 enthält FY2024 und FY2023. Nach der
Prüfung beider Berichte kann die App:

- FY2023 bis FY2025 chronologisch zusammenführen,
- beide FY2024-Quellen erhalten, statt eine davon zu überschreiben,
- gleiche Beobachtungen als übereinstimmend markieren,
- Abweichungen als offenen Konflikt zur Analystenentscheidung zeigen,
- FY2025 mit FY2024 vergleichen und den Dreijahrestrend darstellen,
- optionale Erwartungen und Guidance ergänzen,
- die bestätigte Historie mit Quellen exportieren.

Öffentliche Berichte dienen nur manuellen Integrationstests und werden nicht im
Repository gespeichert. Automatisierte Tests verwenden synthetische PDFs und
Finanzdaten.

## Installation

Voraussetzungen: Python 3.11 oder neuer und Git.

macOS oder Linux:

```bash
git clone <repository-url>
cd research-update-assistant
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Windows PowerShell:

```powershell
git clone <repository-url>
cd research-update-assistant
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Die virtuelle Umgebung isoliert die Projektabhängigkeiten von der globalen
Python-Installation.

## Run locally

Bei aktivierter virtueller Umgebung:

```bash
python -m streamlit run app.py
```

Streamlit zeigt anschließend eine lokale Adresse, üblicherweise
`http://localhost:8501`. Hochgeladene Dokumente, Historie, Erwartungen und
Guidance bleiben nur in der laufenden Browser-Sitzung.

Ein kleines Terminalbeispiel für FY2023 bis FY2025 steht ebenfalls bereit:

```bash
python examples/compare_synthetic_periods.py
```

## Testing

Die komplette Test-Suite startet mit:

```bash
python -m pytest
```

Die Tests decken Finance-Berechnungen, PDF-Verarbeitung, Mapping, Validierung,
Mehrbericht-Historie, Ergebnis-Update, Expectations, Guidance, Exporte und den
Streamlit-Workflow ab. PDF-Fixtures werden synthetisch im Arbeitsspeicher erzeugt.

## Screenshots

Für eine GitHub-Projektseite eignen sich fünf Ansichten besonders gut:

1. PDF-Prüfung mit synthetischem Bericht und sichtbarer Quellenstelle
2. Finanzhistorie über drei Perioden
3. kompaktes Ergebnis-Update
4. Expectations und Guidance mit synthetischen Werten
5. Exportbereich mit Periodenauswahl

Die Aufnahme- und Datenschutz-Checkliste liegt unter
[`docs/screenshots/README.md`](docs/screenshots/README.md). Screenshots dürfen nur
synthetische Daten oder öffentliche Berichte ohne lokale Dateipfade zeigen.

## Limitations

- Fokus auf Nicht-Finanzunternehmen; Banken und Versicherungen sind nicht Teil
  von V1.
- Die Extraktion ist primär für deutsch- und englischsprachige Berichte ausgelegt.
- Es gibt keine OCR. Reine Scan-PDFs benötigen eine textbasierte Version.
- Komplexe Tabellen, mehrspaltige Layouts und spezielle Schriftcodierungen können
  Parsergrenzen erreichen.
- Einzelne Kennzahlen oder Fußnoten können trotz gut lesbarem Bericht fehlen oder
  falsch priorisiert werden; Analystenprüfung bleibt erforderlich.
- Es gibt keine Bloomberg-, FactSet- oder andere externe Consensus-API.
- Expectations und Guidance werden derzeit manuell erfasst.
- Daten liegen im Streamlit Session State; es gibt keine dauerhafte Datenbank.
- Research-Prüfpunkte sind generische, transparente Regeln und keine Bewertung
  der Aktie oder des Unternehmens.
- Exportiert werden bestätigte beziehungsweise aufgelöste Werte. Offene Konflikte
  bleiben leer und werden in den Quellen dokumentiert.

## Roadmap

Mögliche spätere Erweiterungen sind robustere Parserabdeckung, OCR als klar
getrennter optionaler Schritt, persistente Arbeitsbereiche, zusätzliche
Exportprofile und eine breitere Abdeckung von Berichtsformaten. Diese Punkte sind
nicht Bestandteil der aktuellen V1.

## Data and security

In das Repository gehören nur öffentliche Berichte, öffentliche Daten oder
synthetische Testdaten. API-Schlüssel, Tokens, interne Research Reports,
proprietäre Finanzmodelle und lokale PDFs dürfen nicht versioniert werden.
`local_reports/`, `.env`, `.venv/` und Streamlit-Secrets sind deshalb in
`.gitignore` ausgeschlossen.
