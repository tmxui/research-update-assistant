# Research Update Assistant

Die Auswertung neuer Unternehmensberichte enthält viele repetitive Schritte.
Dieses Lern- und Portfolio-Projekt soll Junior Equity Research Analysts später
bei der strukturierten Auswertung unterstützen: von der Datenextraktion und
manuellen Zahlenprüfung bis zu Periodenvergleichen, Diagrammen und Excel-Exporten.

Der fachliche Fokus liegt auf Schweizer börsenkotierten Nicht-Finanzunternehmen
und deutschsprachigen Jahres- und Halbjahresberichten sowie Ergebnispräsentationen.
Banken und Versicherungen sind in Version 1 ausgeschlossen.

## Entwicklungsstand

**Phase 0 – Projektgrundlage:** Eine lokale Streamlit-App mit deutscher
Startseite. Finanzberechnungen, PDF-Verarbeitung und Machine Learning sind
noch nicht implementiert.

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
Phase-0-Hinweis sehen. Beende den Server im Terminal mit `Ctrl+C`.
Mit `deactivate` verlässt du anschliessend die virtuelle Umgebung.

`.venv` enthält die Python-Pakete nur für dieses Projekt. Durch die Aktivierung
verwenden `python` und `pip` diese Umgebung. Die Installation mit `-e` bindet
den lokalen Code unter `src/` ein; Änderungen sind ohne Neuinstallation nutzbar.
`[dev]` installiert zusätzlich pytest für den Starttest.

## Kontrolle

Bei aktivierter virtueller Umgebung:

```bash
python -m pytest
python -m pip check
git status
```

Der Test prüft den fehlerfreien App-Start und die deutschen Texte.
Git ist lokal eingerichtet; ein erster Commit und die GitHub-Einrichtung
folgen gemeinsam in einem späteren Schritt.

## Struktur und Daten

- `app.py`: Startpunkt der Anwendung.
- `src/research_update_assistant/`: Python-Paket mit der Oberfläche; später weitere Module.
- `config/`: Platz für spätere Regeln und Finanzbegriffe.
- `tests/`: Automatisierte Tests.
- `sample_data/`: Nur öffentliche oder synthetische Beispieldaten.
- `docs/`: Platz für spätere Dokumentation.
- `pyproject.toml`: Projektinformationen, Abhängigkeiten und Werkzeugkonfiguration.
- `.gitignore`: Schliesst lokale Umgebungen, Zugangsdaten und generierte Dateien aus Git aus.

Die leeren `.gitkeep`-Dateien erhalten die noch ungenutzten Ordner in Git.
Verwende nur öffentliche Geschäftsberichte, öffentliche Daten oder synthetische
Testdaten. Speichere keine API-Schlüssel, Passwörter, Tokens, vertraulichen
Unternehmensdaten, internen Research Reports oder proprietären Finanzmodelle
im versionierten Projekt. `.gitignore` ist kein automatischer Vertraulichkeitsfilter.
