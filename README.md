# Research Update Assistant

Die Auswertung neuer Unternehmensberichte enthält viele repetitive Schritte.
Dieses Lern- und Portfolio-Projekt soll Junior Equity Research Analysts später
bei der strukturierten Auswertung unterstützen: von der Datenextraktion und
manuellen Zahlenprüfung bis zu Periodenvergleichen, Diagrammen und Excel-Exporten.

Der fachliche Fokus liegt auf Schweizer börsenkotierten Nicht-Finanzunternehmen
und deutschsprachigen Jahres- und Halbjahresberichten sowie Ergebnispräsentationen.
Banken und Versicherungen sind in Version 1 ausgeschlossen.

## Entwicklungsstand

**Phase 1 – Finanzdatenmodell und Berechnungslogik:** Periodenwerte,
chronologische Historie, Kennzahlen und Vergleiche sind als unabhängige
Python-Module implementiert. Die Streamlit-App zeigt weiterhin nur eine
deutsche Startseite. PDF-Verarbeitung, Eingabemasken, Dashboards und
Machine Learning sind noch nicht implementiert.

## Installation und Start (macOS / VS-Code-Terminal)

Voraussetzung: Python 3.11 oder neuer. Öffne diesen Projektordner in VS Code.
Führe die folgenden Befehle im Terminal im Projektordner aus:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m streamlit run app.py
```

Die ersten drei Befehle richten das Projekt einmalig ein. Falls `.venv` bereits
eingerichtet ist, genügen bei einem neuen Terminal:

```bash
source .venv/bin/activate
python -m streamlit run app.py
```

Öffne `http://localhost:8501` im Browser, falls sich kein Fenster automatisch
öffnet. Du solltest den Projekttitel, die deutsche Beschreibung und den
Phase-1-Hinweis sehen. Beende den Server im Terminal mit `Ctrl+C`.
Mit `deactivate` verlässt du anschliessend die virtuelle Umgebung.

`.venv` enthält die Python-Pakete nur für dieses Projekt. Durch die Aktivierung
verwenden `python` und `pip` diese Umgebung. Die Installation mit `-e` bindet
den lokalen Code unter `src/` ein; Änderungen sind ohne Neuinstallation nutzbar.
`[dev]` installiert zusätzlich pytest für die Tests.

## Kontrolle

Bei aktivierter virtueller Umgebung:

```bash
python -m pytest
python -m pip check
git status
```

Die Tests prüfen den App-Start, die Formeln, fehlende Werte, Einheiten,
Halbjahres-Leverage und die Historie mit mehreren Quellen.
Git und der GitHub-Remote sind eingerichtet. Phase-1-Änderungen werden
erst nach gemeinsamer Prüfung committet und gepusht.

## Fachliches Fundament in Phase 1

Ein `FinancialPeriod` speichert die Werte eines Unternehmens für eine Periode,
mit Stichtag (`datetime.date`), Dauer, Währung und Skalierung. Fehlende Zahlen
bleiben `None`, echte Nullwerte bleiben `0`. Prozentwerte werden intern als
Dezimalzahlen gespeichert: `0.15` bedeutet 15 %. Die Formeln runden nicht.

Ein Dokument ist eine Quelle und kann mehrere Perioden liefern: Ein Bericht
FY2025 enthält beispielsweise FY2025 und FY2024 als Vergleich. Optionale
`SourceMetadata` speichern die Herkunft getrennt von den Zahlen. PDF-Namen in
den Beispielen sind fiktiv; es findet keine PDF-Verarbeitung statt.

Die `FinancialHistory` hält Datensätze chronologisch nach Stichtag sortiert und
kann weitere aufnehmen. Gleiche Periodenlabels sind erlaubt: Spätere Berichte
können historische Werte durch Restatements, Umklassifizierungen oder
Fehlerkorrekturen verändern. Beide Quellen bleiben erhalten. `get_periods()`
liefert alle Treffer; `get_period()` meldet mehrere Treffer als mehrdeutig.
Keine Quelle gewinnt automatisch. Die spätere Source-/Validation-Schicht
wählt die Datensätze für die normalisierte Historie ausdrücklich aus.

`CalculatedPeriodMetrics` hält die abgeleiteten Kennzahlen separat:
`reported_free_cash_flow` stammt vom Unternehmen;
`calculated_free_cash_flow` ist hier stets operativer Cashflow minus absoluter
Capex-Betrag. Entsprechend bleiben `reported_net_debt` und
`calculated_net_debt` (Finanzschulden minus liquide Mittel) getrennt.
Adjusted EBITDA/EBIT werden niemals als Ersatz für EBITDA/EBIT verwendet.

Net Debt ist eine Stichtagsgrösse, EBITDA eine Periodengrösse. Net Debt / EBITDA
wird deshalb nur für zwölfmonatige Perioden berechnet, sowohl mit berechneter
als auch ausgewiesener Nettoverschuldung. Sechsmonats-EBITDA wird nicht verdoppelt;
für Halbjahres-Leverage wäre später ein tatsächliches LTM-EBITDA nötig.

`compare_periods(current, previous)` vergleicht genau zwei Perioden desselben
Unternehmens mit gleicher Währung, Skalierung und Monatsanzahl. Die aktuelle
Periode muss später enden. Mehrjährige Abstände sind erlaubt, aber die
Veränderung ist dann die Veränderung über den gesamten Abstand, kein CAGR.
H1 gegen H1 ist möglich; H1 gegen ein Geschäftsjahr wird verhindert.
Es gibt keine stillen Umrechnungen oder Annualisierungen.

EBIT-Marge 15 % → 13 % ergibt `-0.02`, also −2 Prozentpunkte bzw. −200 Basispunkte.
Eine relative Veränderung wäre dagegen `13 / 15 - 1`, also etwa −13.33 %.
Wachstumsraten folgen auch bei negativen Ausgangswerten der angegebenen Formel;
Phase 1 nimmt keine wirtschaftliche Bewertung vor.

## Synthetisches Drei-Jahres-Beispiel

Bei aktivierter virtueller Umgebung:

```bash
python examples/compare_synthetic_periods.py
```

Das Beispiel lädt `sample_data/synthetic_periods.json`, organisiert FY2023,
FY2024 und FY2025 und verwendet dieselbe Funktion für beide Jahresvergleiche.
Alle Geldbeträge sind CHF Millionen. Nur die Terminalausgabe wird formatiert.

| Kennzahl | FY2024 vs. FY2023 | FY2025 vs. FY2024 |
|---|---:|---:|
| Umsatzwachstum | +8.6957 % | +10.0000 % |
| EBIT-Marge vorher → aktuell | 15.7609 % → 15.0000 % | 15.0000 % → 13.0000 % |
| EBIT-Margenänderung | −76.0870 Basispunkte | −200.0000 Basispunkte |
| Berechneter Free Cashflow | 95 → 100 | 100 → 60 |
| Berechnete Nettoverschuldung | 185 → 200 | 200 → 270 |
| Net Debt / EBITDA | 0.973684x → 1.000000x | 1.000000x → 1.285714x |

## Struktur und Daten

- `app.py`: Startpunkt der Anwendung.
- `src/research_update_assistant/models.py`: Periodenwerte, Source-Metadaten und Ergebnis-Dataclasses.
- `src/research_update_assistant/calculations.py`: Formeln und Zwei-Perioden-Vergleich.
- `src/research_update_assistant/history.py`: Chronologische Historie ohne Konfliktauflösung.
- `src/research_update_assistant/ui.py`: Streamlit-Startseite, ohne Finanzlogik.
- `config/`: Platz für spätere Regeln und Finanzbegriffe.
- `tests/`: Automatisierte Tests.
- `sample_data/`: Nur öffentliche oder synthetische Beispieldaten.
- `examples/`: Ausführbares Terminal-Beispiel für die drei synthetischen Jahre.
- `docs/`: Platz für spätere Dokumentation.
- `pyproject.toml`: Projektinformationen, Abhängigkeiten und Werkzeugkonfiguration.
- `.gitignore`: Schliesst lokale Umgebungen, Zugangsdaten und generierte Dateien aus Git aus.

Die leeren `.gitkeep`-Dateien erhalten die noch ungenutzten Ordner in Git.
Verwende nur öffentliche Geschäftsberichte, öffentliche Daten oder synthetische
Testdaten. Speichere keine API-Schlüssel, Passwörter, Tokens, vertraulichen
Unternehmensdaten, internen Research Reports oder proprietären Finanzmodelle
im versionierten Projekt. `.gitignore` ist kein automatischer Vertraulichkeitsfilter.
