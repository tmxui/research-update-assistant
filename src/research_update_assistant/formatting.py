"""Nur Anzeigeformatierung; die ursprünglichen Zahlen werden nicht verändert."""


def format_amount(value: float | None) -> str:
    """Zeige Beträge mit Schweizer Gruppierung und höchstens zwei Dezimalstellen."""
    if value is None:
        return "–"
    return f"{value:,.2f}".replace(",", "'").rstrip("0").rstrip(".")


def format_percentage(value: float | None, *, signed: bool = False) -> str:
    """Formatiere eine Dezimalquote als Prozentwert mit einer Dezimalstelle."""
    if value is None:
        return "–"
    return f"{value:+.1%}".replace("%", " %") if signed else f"{value:.1%}".replace("%", " %")


def format_multiple(value: float | None, *, signed: bool = False) -> str:
    """Formatiere einen Multiplikator oder seine absolute Änderung."""
    if value is None:
        return "–"
    return f"{value:+.2f}x" if signed else f"{value:.2f}x"


def format_basis_points(value: float | None) -> str:
    """Zeige die bereits berechneten Basispunkte als vorzeichenbehaftete Zahl."""
    return "–" if value is None else f"{value:+.0f} bps"
