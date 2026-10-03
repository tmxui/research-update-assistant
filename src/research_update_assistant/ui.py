"""Deutsche Benutzeroberfläche für Phase 0."""

import streamlit as st


def render_home_page() -> None:
    """Zeige die einfache Startseite ohne Finanzlogik."""
    st.set_page_config(page_title="Research Update Assistant", page_icon="📊")
    st.title("Research Update Assistant")
    st.write(
        "Diese Anwendung unterstützt bei der strukturierten Auswertung "
        "von Unternehmensresultaten."
    )
    st.info("Aktueller Entwicklungsstand: Phase 0 – Projektgrundlage")
