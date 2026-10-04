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


def _scale_suffix(scale: str) -> str:
    return {"unit": "", "thousand": "Tsd.", "million": "Mio.", "billion": "Mrd."}.get(scale, scale)


def format_currency_unit(currency: str, scale: str) -> str:
    """Beschrifte eine Geldachse, ohne Beträge umzurechnen."""
    return f"{currency} {_scale_suffix(scale)}".strip()


def format_money(value: float | None, currency: str, scale: str) -> str:
    """Zeige einen Betrag mit Währung und ursprünglicher Skalierung."""
    if value is None:
        return "–"
    return f"{currency} {format_amount(value)} {_scale_suffix(scale)}".strip()
