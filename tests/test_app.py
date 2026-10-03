"""Prüfe, ob die Startseite ohne Fehler auf Deutsch erscheint."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_app_starts_with_german_content() -> None:
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=15).run()

    assert not app.exception
    assert app.title[0].value == "Research Update Assistant"
    assert app.markdown[0].value == (
        "Diese Anwendung unterstützt bei der strukturierten Auswertung "
        "von Unternehmensresultaten."
    )
    assert app.info[0].value == (
        "Aktueller Entwicklungsstand: Phase 1 – Finanzdatenmodell und Berechnungslogik"
    )
