"""Kontrollierte synthetische Finanzstatements, vollständig im Arbeitsspeicher."""

import pymupdf


def make_financial_pdf(
    *, ruled: bool = False, split_values: bool = False,
    reverse_years: bool = False, include_capex: bool = True,
) -> bytes:
    """Drei Statements mit/ohne Linien und optional getrennten Label-/Zahlenzeilen."""
    statements = (
        ("Konzern-Erfolgsrechnung", (
            ("Nettoumsatz", "1’100", "1’000"),
            ("Operativer Cashflow (EBITDA)", "210", "200"),
            ("Betriebsergebnis (EBIT)", "143", "150"),
            ("Bereinigtes EBIT", "148", "155"),
            ("Reingewinn", "92", "100"),
        )),
        ("Konzernbilanz", (
            ("Flüssige Mittel", "90", "100"),
            ("Finanzverbindlichkeiten", "360", "300"),
            ("Vorräte", "190", "150"),
            ("Forderungen aus Lieferungen und Leistungen", "150", "120"),
            ("Verbindlichkeiten aus Lieferungen und Leistungen", "110", "100"),
            ("Bilanzsumme", "1’000", "900"),
            ("Eigenkapital", "550", "500"),
        )),
        ("Konzern-Geldflussrechnung", (
            ("Nettomittelfluss aus/für (-) Geschäftstätigkeit", "140", "160"),
            *((("Investitionen in Sachanlagen", "(80)", "(60)"),) if include_capex else ()),
            ("Free Cashflow", "60", "95"),
        )),
    )
    with pymupdf.open() as pdf:
        font = pymupdf.Font("cjk")
        for title, lines in statements:
            page = pdf.new_page(width=650, height=840)
            page.insert_font(fontname="financial", fontbuffer=font.buffer)

            def text(x: float, y: float, value: str, size: float = 10) -> None:
                page.insert_text((x, y), value, fontname="financial", fontsize=size)

            def right_text(x: float, y: float, value: str) -> None:
                text(x - font.text_length(value, fontsize=10), y, value)

            text(45, 55, title, 15)
            text(45, 85, "Synthetic Industrial AG – in Mio. CHF")
            text(45, 118, "Bezeichnung")
            text(365, 118, "Anhang")
            years = ("2024", "2025") if reverse_years else ("2025", "2024")
            if title == "Konzernbilanz":
                years = tuple(f"31.12.{year}" for year in years)
            right_text(490, 118, years[0])
            right_text(605, 118, years[1])
            height = 45 if split_values else 32
            for index, (label, current, previous) in enumerate(lines):
                y = 150 + index * height
                text(45, y, label)
                value_y = y + 14 if split_values else y
                text(370, value_y, str(index + 3))  # Notesnummer: kein Finanzwert.
                values = (previous, current) if reverse_years else (current, previous)
                right_text(490, value_y, values[0])
                right_text(605, value_y, values[1])
            if ruled and not split_values:
                bottom = 128 + len(lines) * 32
                for x in (40, 355, 415, 540, 620):
                    page.draw_line((x, 96), (x, bottom))
                for y in (96, 128, *(128 + i * 32 for i in range(1, len(lines) + 1))):
                    page.draw_line((40, y), (620, y))
        pdf.subset_fonts()
        return pdf.tobytes(garbage=4, deflate=True)
