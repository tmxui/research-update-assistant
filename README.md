# Research Update Assistant

Die Auswertung neuer Unternehmensberichte enthält viele repetitive Schritte.
Dieses Lern- und Portfolio-Projekt soll Junior Equity Research Analysts später
bei der strukturierten Auswertung unterstützen: von der Datenextraktion und
manuellen Zahlenprüfung bis zu Periodenvergleichen, Diagrammen und Excel-Exporten.

Der fachliche Fokus liegt auf Schweizer börsenkotierten Nicht-Finanzunternehmen
und deutschsprachigen Jahres- und Halbjahresberichten sowie Ergebnispräsentationen.
Banken und Versicherungen sind in Version 1 ausgeschlossen.

## Entwicklungsstand

**Phase 8A – Erwartungen und Surprise-Analyse:** Manuell erfasste
Erwartungs-Snapshots können einem Results Update ausdrücklich zugeordnet
werden. Die Ansicht zeigt Actual, Prior, Estimate und die neutrale numerische
Abweichung. Eine zusätzliche Ansicht fasst
bestätigte Resultate, Veränderungen, Research-Prüfpunkte, Trends und Quellen
für das ausdrücklich gewählte Vergleichspaar zusammen. Mehrere Reports eines
Unternehmens können in einer lokalen Historie zusammengeführt werden. Alle
Quellen bleiben erhalten; abweichende Werte erfordern eine Quellenauswahl.
Trendzeitraum und Vergleichspaar sind unabhängig wählbar. PDFs liefern
prüfpflichtige Kennzahl-Kandidaten aus Tabellen und Wortpositionen. Nach
ausdrücklicher Analystenbestätigung verwendet die App dieselbe Finanzanalyse
wie bei manuellen Eingaben. Dokumentbrowser und Textsuche bleiben verfügbar.
Der unabhängige manuelle Workflow erfasst weiterhin
zwei oder drei Perioden und zeigt eine chronologische Finanzübersicht sowie
aufeinanderfolgende Periodenvergleiche. Eine unabhängige Regel-Engine erzeugt
transparente Research-Prüfpunkte aus den bestehenden Phase-1-Berechnungen.
Fünf Kennzahlenkarten und Plotly-Diagramme machen die vorhandenen Daten sichtbar.
OCR, externe LLM/API-Extraktion, externe Consensus-Anbieter, Excel-Export
und Machine Learning sind noch nicht implementiert.

## Installation und Start (macOS / VS-Code-Terminal)

Voraussetzung: Python 3.11 oder neuer und Streamlit ab 1.65 (wie in
`pyproject.toml` definiert). Öffne diesen Projektordner in VS Code.
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
Phase-8A-Hinweis sowie die Tabs PDF-gestützte Analyse, Manuelle Eingabe,
Finanzhistorie und Erwartungen sehen. Beende den Server im Terminal mit `Ctrl+C`.
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

Die Tests prüfen synthetische PDFs, Seitenherkunft, Roh-Tabellen, Textsuche und
PDF-Fehler sowie Diagrammdaten und Kennzahlenkarten, die Research-Regeln und YAML-Validierung, den Formularablauf, Schweizer Zahlenformate, den App-Start,
die Formeln, fehlende Werte, Einheiten, Halbjahres-Leverage und die Historie
mit mehreren Quellen.
Git und der GitHub-Remote sind eingerichtet. Phase 6 wurde nach dem lokalen
Multi-Report-Test mit den konsolidierten Geberit-Abschlüssen 2025 und 2024
fachlich freigegeben.

## Erwartungen und Surprise-Analyse in Phase 8A

Ein `ExpectationSnapshot` speichert eine manuell erfasste Erwartung für genau
eine wirtschaftliche Zielperiode. Unternehmen, Stichtag und Periodendauer,
Währung, Skalierung, Bezeichnung, Typ und `as_of_date` bleiben erhalten.
Mehrere Snapshots dürfen dieselbe Zielperiode betreffen; im Ergebnis-Update ist
höchstens einer ausdrücklich aktiv. Die Snapshots leben nur in der aktuellen
Browser-Sitzung. Es gibt keine externe Consensus-API und keine proprietären
Consensus-Daten in den Tests.

Der Bereich **Erwartungen erfassen** verwendet bekannte, bereits analysierte
Perioden und fragt nur die relevanten Schätzwerte ab. Leere Felder bleiben
`None`. Die Eingabe einer EBIT-Marge erfolgt in Prozent, intern wird sie als
Dezimalzahl gespeichert. Aus Umsatz- und EBIT-Schätzungen wird keine vermeintliche
Consensus-Marge abgeleitet. Ausgewiesener Free Cashflow und ausgewiesene
Nettoverschuldung bleiben ausdrücklich reported Kennzahlen.

`compare_actual_to_expectation()` validiert Unternehmen, Zielperiode, Währung
und Skalierung. Bei normalen Beträgen ist die absolute Surprise `Actual -
Estimate`. Eine prozentuale Surprise wird nur bei positiver Schätzbasis und
nichtnegativem Actual berechnet. Bei Schätzung null, negativer Basis oder
Vorzeichenwechsel bleibt sie `None`; die absolute Differenz bleibt sichtbar.
Margenabweichungen erscheinen als Prozentpunktdifferenz und Basispunkte,
Leverage als Differenz in x. Es gibt keine wirtschaftliche Wertung dieser
Richtungen.

Mit aktivem Snapshot ergänzt **Abweichung zu Erwartungen** höchstens sieben
Kennzahlen um Actual, Prior, YoY, Estimate und Surprise. Ohne Auswahl bleibt der
Phase-7-Screen unverändert. Research-Prüfpunkte und wichtigste Veränderungen
verwenden weiterhin ausschliesslich Actual vs Prior. Bezeichnung, Typ, Stand
und optionale Notizen dokumentieren die manuelle Herkunft der Erwartung; es
wird keine PDF-Quelle erfunden. Guidance, automatische Empfehlungen und eine
Revision-Historie für Erwartungen gehören nicht zu Phase 8A.

## Kompaktes Ergebnis-Update in Phase 7

Nach einer PDF- oder Historienanalyse stehen **Ergebnis-Update** und
**Detailanalyse** nebeneinander. Das Ergebnis-Update zeigt Actual vs Prior:
aktuelle bestätigte Resultate und ihren Vergleich mit der ausdrücklich
gewählten Basisperiode. Die bestehenden Tabellen und vollständigen Charts
bleiben in der Detailanalyse erhalten; die manuelle Eingabe bleibt unabhängig.

Oben erscheinen höchstens sieben verfügbare Headline-Kennzahlen: Umsatz,
EBITDA (sonst EBIT), EBIT-Marge, operativer Cashflow, FCF, Nettoverschuldung und
Net Debt / EBITDA. Fehlende Werte erzeugen keine Null-Karte; echte Nullwerte
bleiben sichtbar. Prozentveränderungen benötigen einen positiven Basiswert.
Margenänderungen werden in Basispunkten, Leverage-Differenzen in x angezeigt.
Alle Karten-Deltas sind neutral gefärbt.

FCF bevorzugt **Ausgewiesener FCF**, falls dieser vorhanden ist, andernfalls
**Berechneter FCF**. Vergleich und Delta verwenden immer dieselbe Definition;
ein fehlender reported-Vergleich wird nicht durch calculated FCF ersetzt.
Die Nettoverschuldungskarte ist ausdrücklich als ausgewiesen oder berechnet
bezeichnet. Leverage verwendet ausschliesslich die vorberechnete Kennzahl
`calculated_net_debt_to_ebitda` der Finance-Schicht: berechnete Nettoverschuldung
aus Bruttoschulden minus liquiden Mitteln, geteilt durch Jahres-EBITDA.
Ist nur ausgewiesene Nettoverschuldung verfügbar, erscheint diese Karte,
aber keine Net-Debt/EBITDA-Karte. Phase 7 bildet keinen Ersatz-Ratio aus dem
reported-Wert. Eine offene Quellenabweichung ist kein Anlass, still zur
anderen Definition zu wechseln.

**Wichtigste Veränderungen** enthält höchstens sieben deterministische
Zahlenzeilen. Die Grundreihenfolge ist Umsatz, Ergebnis/Marge, Cashflow,
Leverage und Working Capital. Kennzahlen mit vorhandenen Research-Prüfpunkten
können höher priorisiert werden. Es gibt keine erzeugte Interpretation.
**Research-Prüfpunkte** übernimmt die vorhandenen Flags des Vergleichspaars,
sortiert Rot vor Gelb vor Grün. Zunächst sind höchstens fünf sichtbar;
weitere stehen unter **Alle Prüfpunkte anzeigen**. Es gibt keinen Gesamtscore.

**Historischer Kontext** verwendet bis zu drei kompakte bestehende Charts
für Umsatz, Margen und Cashflow. Die Zahl der Trendperioden ist weiterhin
flexibel. Ein Fünfjahrestrend kann beispielsweise gleichzeitig mit einem
Vergleich FY2023 gegen FY2024 angezeigt werden: Karten, Deltas und Flags
beziehen sich dann auf FY2024; FY2025 bleibt lediglich Teil des Trends.

Der Expander **Quellen** zeigt die Belege für Headline-Werte und deren
Vergleichsbasis. Für berechnete Kennzahlen werden die Eingangsgrössen als
Quellen gezeigt, ohne einen berechneten Wert als PDF-Zitat auszugeben.
Ausgewählte und äquivalente Quellen sowie Alternativen bleiben nachvollziehbar
und über den bestehenden Seitenbrowser prüfbar. Manuelle Werte erhalten keine
erfundene PDF-Herkunft. Offene Konflikte werden als **Historischer Wert
ungeklärt** markiert; betroffene Werte oder Deltas werden nicht still verwendet.

`build_results_update()` erzeugt ein unveränderliches Präsentationsmodell aus
vorhandenen Perioden, Metrics, Comparison, Flags und Quellen. Es implementiert
keine neuen Finanzformeln und ist unabhängig von Streamlit. Es gibt weiterhin
keinen Consensus, keine Guidance, kein LLM und keine Investment-Empfehlungen.

## Mehrjährige Finanzhistorie in Phase 6

Ein Bericht ist eine **Quelle**, eine Periode ein wirtschaftlicher Zeitraum.
Ein Geschäftsbericht 2025 enthält beispielsweise FY2025 und den Vergleich
FY2024; der Bericht 2024 ergänzt FY2023 und eine weitere Quelle für FY2024.
Die wirtschaftliche Identität verwendet **Stichtag und Monatsanzahl**, nicht
nur das Label. Jahres- und Halbjahresperioden bleiben unterscheidbar.

**Ablauf:** Bericht wie bisher prüfen → **Bestätigte Daten übernehmen** →
Unternehmenszugehörigkeit bestätigen → **Zur Finanzhistorie hinzufügen** →
**Weiteren Bericht hinzufügen**. Die bestehende Historie bleibt beim neuen
Upload, bei Reset oder Ablehnung im PDF-Editor erhalten. Unternehmen, Währung
und Skalierung müssen übereinstimmen; keine automatische Zusammenführung
ähnlicher Unternehmensnamen oder Umrechnung. Die Einzelreport-Analyse und
der manuelle Workflow bleiben zusätzlich verfügbar.

`HistoryWorkspace` speichert bestätigte Report-Snapshots und einzelne
`MetricObservation`-Quellwerte. Eine `PeriodMetricResolution` bündelt die
Observations derselben Kennzahl/Periode:

- Eine bestätigte Quelle liefert einen aktiven Wert (`resolved`).
- Exakt gleiche Werte sind `equivalent`: durch mehrere Quellen bestätigt.
  Wiederholtes Hinzufügen desselben unveränderten Reports ist idempotent.
- Unterschiedliche Werte bleiben `unresolved`. Eine Abweichung ist noch kein
  bewiesenes Restatement; auch Umklassifizierung oder Fehler sind möglich.
- `rounding_difference` bedeutet **mögliche** Rundung: Nur mit nachgewiesenen
  Dezimalstellen wird geprüft, ob sich kaufmännische Rundungsintervalle
  überschneiden. Es gibt keine allgemeine Betrags- oder Prozenttoleranz.
  Beispielsweise passen 1000.0 und 999.96 zur gleichen gerundeten Zahl.
  Ohne Präzisionsnachweis bleibt die Abweichung ein offener Konflikt.
  Analystisch korrigierte Zahlen erhalten keine Präzision aus dem alten Rohtext.

Für Rundungsdifferenzen und sonstige Konflikte entscheidet der Analyst im
Bereich **Abweichende historische Werte prüfen**. Die Quellen mit Werten,
Seiten und Bezeichnungen bleiben sichtbar. **Quelle prüfen** verwendet den
bestehenden Seitenbrowser für genau den archivierten Report. Auswahl und
optional Grund werden protokolliert; alternative Observations, Originalwerte,
Korrekturen und Quellen werden nicht gelöscht. Eine neue abweichende Quelle
öffnet eine frühere Entscheidung erneut. Frühere Entscheidungen bleiben im
Auflösungsverlauf nachvollziehbar. Geänderte Daten unter einer bereits
verwendeten Berichts-ID werden abgewiesen und benötigen eine neue Report-ID.

Offene Kennzahlen gehen als `None` in die normalisierte Historie ein. Davon
abhängige Formeln bleiben nicht verfügbar; fehlende Werte werden weder als 0
noch durch Interpolation ergänzt. **Historientabelle** zeigt alle gespeicherten
Perioden. Die Auflösung erzeugt normale `FinancialPeriod`-Objekte und eine
`FinancialHistory`; bestehende Berechnungen, Flags und Charts werden verwendet.

**Perioden für Analyse auswählen** bestimmt nur den Trendzeitraum: zwei, drei,
fünf oder beliebig viele vergleichbare Perioden. Standard sind die zwei
neuesten kompatiblen Jahresperioden, andernfalls Halbjahre. **Vergleichsperioden**
legt separat Basisperiode und aktuelle Periode fest. Charts verwenden den
Trendzeitraum, Research-Prüfpunkte genau dieses eine Paar. Kennzahlenkarten
zeigen die jüngste Trendperiode; Deltas erscheinen nur, wenn sie der aktuellen
Vergleichsperiode entspricht. H1 wird mit H1, FY mit FY verglichen. Auch die
Trenddarstellung trennt Jahres- und Halbjahresperioden konservativ.

Die Historie und archivierten Seitentexte leben nur in dieser Browser-Sitzung.
Ein neuer Upload löscht sie nicht; Schliessen der Sitzung oder Server-Neustart
kann sie verlieren. **Finanzhistorie zurücksetzen** erfordert eine bewusste
Bestätigung. Es gibt noch keine dauerhafte Speicherung oder Datenbank.
Der unabhängige Kern unterstützt bereits bestätigte manuelle Perioden über
`add_periods`; dafür wird keine PDF-Herkunft erfunden.

**Bekannte Parsergrenzen (Backlog):** Im Geberit-Test wurden `gross_debt`,
`total_assets` und `equity` sowie die EBITDA-Fussnote im Report 2024 noch nicht
zuverlässig extrahiert. Nicht bestätigte Werte bleiben `None`. Diese Punkte
blockieren die freigegebene Phase 6 nicht und werden später separat behandelt.

## Finanzkennzahlen-Extraktion in Phase 5B

**Ablauf:** PDF hochladen → Kandidaten prüfen → gewünschte Kennzahlen einzeln
bestätigen → Unternehmen und zwei Vergleichsperioden prüfen →
**Bestätigte Daten übernehmen** → **Analyse aus bestätigten PDF-Daten starten**.
Ein Upload allein erzeugt keine Finanzperioden; die Übernahme bereitet bestätigte
Daten vor und startet noch keine Berechnung.

**Phase 5B.2:** Zwei Tabs trennen **PDF-gestützte Analyse** und **Manuelle Eingabe**.
Der PDF-Tab zeigt nach der Übernahme Unternehmen, Perioden, Währung, Einheit und
die Anzahl bestätigter Kennzahlen. Die Analyse startet daraus ohne erneute
manuelle Dateneingabe. Im manuellen Tab bleiben Beispieldaten, zwei oder drei
Perioden und **Analyse berechnen** verfügbar. Beide Wege verwenden dieselbe
Analyse-Engine, bewahren ihre Entwürfe und Ergebnisse aber unabhängig voneinander.

Statement-Seiten werden aus Überschriften, typischen Zeilenbezeichnungen,
Jahresangaben und numerischen Werten erkannt. Primäre Erfolgsrechnung, Bilanz
und Geldflussrechnung haben Vorrang vor Notes, Kennzahlen-/Mehrjahresübersichten,
APM-Tabellen, Highlights und Fliesstext. Innerhalb einer Quellenart werden
sicherere Zuordnungen zuerst angeboten. Eine zahlenreiche Kennzahlenübersicht
wird dadurch nicht zum Primärstatement. Segmentquellen stehen am Ende und sind
für Konzernwerte gesperrt.
Eine Heuristik kann eine Seite falsch einordnen; deshalb bleibt die Prüfung nötig.

Der Parser kombiniert pdfplumber-Tabellen mit PyMuPDF-Wortpositionen.
Wörter nahe derselben Grundlinie werden sortiert; Jahres- und Datumsheader
legen die Betragsspalten fest. Zuordnungen folgen deren x-Positionen,
auch bei umgekehrter Jahresreihenfolge oder separaten Label-/Wertzeilen.
Die benannten Toleranzen stehen in `layout_parser.py`. Ohne brauchbare
Positionen/Tabellen ist ein konservativer Textfallback möglich: Die Perioden
bleiben dann unbekannt und müssen ausdrücklich zugeordnet werden.

`config/metrics.yaml` enthält 19 stabile Kennzahl-IDs mit deutschen Schweizer
und englischen Synonymen. Explizite Kürzel haben Vorrang:
**Operativer Cashflow (EBITDA)** ist EBITDA, nicht Geldfluss aus Geschäftstätigkeit.
Bereinigtes EBIT/EBITDA bleiben eigene Kennzahlen. Margen und Wachstumsraten
werden nicht als absolute Beträge behandelt. Segmentzusätze wie Europa sperren
die Konzernübernahme. Ähnliche Schreibweisen erhalten nur niedrige Sicherheit.
Umsatz je Beschäftigten ist kein Konzernumsatz und wird ausgeschlossen.
Die Originalbezeichnung bleibt erhalten; ein separates Mapping-Label entfernt
dekorative PDF-Zeichen. Note-Nummern werden nur bei belegtem Spalten- oder
Verweiskontext entfernt, nicht pauschal aus jeder Bezeichnung.

Kandidaten zeigen **Hoch / Mittel / Niedrig** mit Gründen, keine vermeintlichen
Wahrscheinlichkeiten. Unterschiedliche Werte oder Quellen bleiben auswählbar;
identische Werte derselben Seite können kanalübergreifend gruppiert werden.
Einheiten werden nicht still umgerechnet. Schweizer Gruppierungen und
Dezimalzeichen bleiben nachvollziehbar; numerische Accounting-Klammern
werden als negatives Vorzeichen gelesen. EPS bleibt ein Währungsbetrag je Aktie,
unabhängig von Millionen/Tausend bei den übrigen Beträgen.

Im Prüfbereich kannst du Quellen wählen, die Kennzahl-Zuordnung ändern,
Werte korrigieren, ablehnen oder fehlende Angaben manuell ergänzen.
Ein gemeinsamer Aktionsbereich gilt für die gesamte Kennzahl und beide Perioden.
**Änderungen zurücksetzen** stellt die Originalwerte, Kennzahl-Zuordnung, Währung
und Einheit der gewählten Quelle wieder her. **Kandidat ablehnen** stellt ebenfalls
die Originale wieder her und entfernt die aktive Bestätigung. Erneute Bearbeitung
und Bestätigung bleiben möglich; frühere Bestätigungen werden separat in der
Sitzung bewahrt und nicht als aktive Finanzdaten verwendet. Andere Kennzahlen
werden durch Reset oder Ablehnung nicht verändert.
Standardmässig erscheinen die besten fünf Quellen; **Weitere Quellen anzeigen**
öffnet die übrigen Alternativen. Auch gerundete und präzise Beträge bleiben
getrennt erhalten. Eine bereits gewählte weitere Quelle bleibt beim Einklappen sichtbar.
Vorgeschlagene/abgelehnte Werte werden nicht übernommen. Änderungen verlangen
eine neue Bestätigung. Zwei gleich lange Jahres- oder Halbjahresperioden sowie
deren Stichtage werden vor Übernahme geprüft. Unvollständige Finanzdaten sind
erlaubt und bleiben `None`; Halbjahres-Leverage wird weiterhin nicht annualisiert.
Änderungen an PDF-Prüfdaten machen deren Übernahme und Analyse ungültig; bitte
erneut übernehmen und starten. Ein neuer Upload verwirft den vorherigen
PDF-Prüfstand, erhält aber manuelle Eingaben und Ergebnisse.

Jede bestätigte Zahl bewahrt einen separaten Audit-Trail mit Rohwert,
ursprünglicher Zuordnung, bestätigtem Wert, Dokument, Seite, Quelltext,
Extraktionsmethode und optionaler Position. Manuelle Ergänzungen erhalten keine
erfundene PDF-Quelle. `FinancialPeriod` enthält weiterhin einfache Zahlen;
`FinancialHistory`, Berechnungen, Research-Regeln und Charts werden gemeinsam genutzt.
Die Quellen bleiben unter **Quellen und bestätigte Korrekturen** einsehbar.

Die synthetischen Tests decken alle drei Statements, Linien- und Positionslayouts,
Mapping, Einheiten, Korrekturen, Bestätigung und das bestehende Dashboard ab.
Ranking-Regressionsfälle bilden frühe gerundete Kennzahlenübersichten,
spätere präzise Primärstatements, PDF-Verweise und Umsatz je Beschäftigten nach.
Es werden keine externen Berichte als Testfixtures benötigt. Öffentliche
Schweizer Berichte prüfen wir zusätzlich manuell, insbesondere EBITDA,
tatsächlichen Operating Cash Flow, Free Cashflow, Vorräte und Forderungen.
Noch kein Commit/Push.
Es gibt keine LLM/API-Extraktion, automatische Ursachenerklärung oder Investment-Empfehlung.

## PDF-Dokumentbrowser aus Phase 5A

Unter **Geschäftsbericht einlesen** kannst du ein PDF hochladen. PyMuPDF liest
Text und Dokumentinformationen; pdfplumber versucht, Tabellen mit seiner
Standarderkennung zu finden. Die Übersicht nennt Seiten, Textseiten, erkannte
Tabellen und eine technische Qualitätskategorie. **Ein Upload startet keine
Finanzanalyse und erzeugt keine FinancialPeriod-Objekte.**

Im **Seitenbrowser** wählst du eine physische PDF-Seite (erste Seite = 1).
Gedruckte Seitenzahlen können davon abweichen. Der extrahierte Text bleibt mit
Zeilenumbrüchen und Unicode-Zeichen erhalten. Tabellen speichern rohe Strings
oder fehlende Zellen, Seitennummer, Tabellenindex und Position in PDF-Punkten.
Die erste Tabellenzeile wird nicht automatisch als Header interpretiert.
Nicht erkannte Tabellen werden nicht als Beweis für ihre Abwesenheit behandelt;
komplexe Layouts und Texte ohne Zeichencodierung können unvollständig ausgelesen werden.

**Dokument durchsuchen** sucht wörtlich und ohne Beachtung der Gross-/Kleinschreibung
im Seitentext. Pro Trefferseite erscheinen die Anzahl Treffer und ein kurzer
Originaltext-Ausschnitt um den ersten Treffer. Mit **PDF-Seite … anzeigen**
wechselst du zur Quelle. Diese Textsuche bleibt wörtlich; das separate Kennzahl-Mapping
findet im Phase-5B-Prüfbereich statt.

Die Diagnose verwendet eine transparente Heuristik: Weniger als 40
Nicht-Leerzeichen gelten als textarme Seite. Mindestens 80 % textarme Seiten
und weniger als 80 Zeichen pro Seite im Mittel ergeben **möglicherweise gescannt**.
Mindestens 25 % textarme Seiten, weniger als 200 Zeichen im Mittel oder
Parser-Warnungen ergeben **eingeschränkt**; andernfalls erscheint **gut**.
Auch kurze, leere oder teilweise nicht lesbare PDFs können Scan-Verdacht auslösen.
Die Kategorie bestätigt weder einen Scan noch die Richtigkeit von Finanzzahlen.
Gescannte PDFs werden aktuell **nicht per OCR** verarbeitet.

Bytes und Ergebnisse bleiben im Arbeitsspeicher der lokalen App und der
jeweiligen Browser-Sitzung. Hochgeladene PDFs werden nicht dauerhaft gespeichert
oder automatisch in Git abgelegt. Die Extraktion erfolgt einmal je Upload;
Suche und Seitenauswahl verwenden das vorhandene Ergebnis. Ein Dateiwechsel
setzt den Dokumentbrowser zurück, lässt aber die manuelle Analyse bestehen.
Passwortpflichtige, ungültige oder seitenlose PDFs zeigen verständliche Fehler.
Einzelne Seiten-/Tabellenfehler erscheinen als Warnungen; andere Seiten bleiben verfügbar.

Die automatisierten Tests erzeugen synthetische PDFs im Speicher und benötigen
keine externen Geschäftsberichte. Der nächste gemeinsame Praxistest ist ein
öffentliches Schweizer Geschäftsbericht-PDF: Seitenzahl, konkrete Textstellen,
Tabellen und Suchtreffer sowie Phase-5B-Kandidaten mit dem Original vergleichen.

## Analyst-Dashboard und Trendanalyse in Phase 4

Nach **Analyse berechnen** folgen Research-Prüfpunkte, Kennzahlenüberblick,
Finanzübersicht, Trendanalyse und Periodenvergleich. Die fünf Karten zeigen die
neueste Periode: Umsatz, EBIT-Marge, berechneten FCF, berechnete Nettoverschuldung
und Net Debt / EBITDA. Vorhandene Deltas kommen aus `PeriodComparison` und sind
neutral dargestellt. Die Research-Prüfpunkte bleiben einzelne Prüfanlässe,
keine Investment-Empfehlungen.

Die Trendanalyse besitzt vier Tabs:

| Tab | Diagramme und Research-Frage |
| --- | --- |
| Ergebnis & Margen | Umsatz separat sowie EBITDA/EBIT gemeinsam: Wie entwickeln sich Geschäft und Ergebnis? Margenlinien: Wie verändert sich die Profitabilität relativ zum Umsatz? |
| Cashflow | Geldfluss und berechneter FCF: Wie entwickelt sich die Cashflow-Erzeugung? Ein vorhandener ausgewiesener FCF bleibt eine separate Reihe. |
| Bilanz & Verschuldung | Nettoverschuldung und Net Debt / EBITDA: Wie entwickeln sich Schulden nach Abzug der flüssigen Mittel und das Verhältnis zum Jahres-EBITDA? |
| Working Capital | Vorräte, Forderungen und operatives Working Capital relativ zum Umsatz: Wie verändert sich die Kapitalbindung relativ zum Geschäft? |

Umsatz und Ergebnis verwenden getrennte Betragsachsen statt einer Doppelachse,
damit kleinere Ergebniswerte lesbar bleiben. Geldachsen und Hover-Texte nennen
Währung und Einheit. Prozentachsen verwenden unveränderte Dezimalquoten.
Die Charts zeigen zwei oder drei erfasste Perioden, ohne darüber hinausgehende
Trends oder Prognosen zu behaupten.

`FinancialHistory` liefert die chronologische Reihenfolge. Bereits berechnete
`CalculatedPeriodMetrics` werden ihrem jeweiligen Periodenobjekt zugeordnet;
die Chart-Funktionen geben Plotly-Figures zurück. **Charts berechnen keine
Finanzkennzahlen selbst.** `None` bleibt fehlend: Linien haben Lücken, fehlende
Balken werden nicht als null dargestellt. Leverage enthält nur vorhandene
Jahreswerte; bei komplett fehlenden Daten erscheint ein sachlicher Hinweis.
Nullwerte bleiben echte Nullwerte. Nur Anzeigen und Hover-Texte werden gerundet.

## Research-Auffälligkeiten in Phase 3

Nach **Analyse berechnen** stehen die **Research-Prüfpunkte** am Anfang des
Analysebereichs. Der jüngste Vergleich steht zuerst. Pro Vergleich
werden rote Hinweise vor gelben und grünen angezeigt. Jeder Hinweis nennt
die Kategorie, relevante Zahlen, Regel-ID und auslösende Schwelle.
Rot bedeutet **deutliche Veränderung zur Prüfung**, Gelb **prüfen**, Grün
**Verbesserung**. Es gibt keinen Gesamtscore und keine Anlageempfehlungen.
Eine nicht ausgelöste Regel ist keine Aussage über die Qualität eines Unternehmens.

Die Schwellen liegen in `config/flag_rules.yaml`. **Diese Schwellenwerte sind
generische Research-Heuristiken und keine universell gültigen Investmentregeln.**
Ein Prozentwert wie `-0.40` bedeutet −40 %. Margenschwellen stehen in Basispunkten,
Leverage-Schwellen in Multiplikatoren. Rückgänge sind grundsätzlich inklusiv
(`<=`), Anstiege ebenfalls (`>=`); nur die gelbe Umsatzregel ist strikt `< 0`.
EBIT-Wachstumsspreads werden nur bei steigendem Umsatz geprüft.
Die Cashflow-Divergenzregel verlangt für Gelb steigenden EBIT, für Rot genügt
unveränderter EBIT bei einem OCF-Rückgang von mindestens 30 %.

Fehlende Kennzahlen lösen keine Regel aus. FCF und Leverage verwenden
ausschliesslich **calculated**-Werte. Es gibt keinen stillen Wechsel zu reported-
oder adjusted-Werten. Leverage setzt zwölf Monate und positives EBITDA voraus;
bei Halbjahresdaten erfolgt keine Annualisierung. Wachstumsbasierte Hinweise
benötigen positive Ausgangswerte: Prozentwachstum aus negativem FCF oder
Verlusten könnte sonst die tatsächliche Richtung falsch beschreiben.
Margenregeln können auch negative Margen vergleichen.

Die YAML-Datei wird sicher eingelesen und auf Vollständigkeit, eindeutige
Schlüssel, endliche Zahlen und sinnvolle Schwellenreihenfolge geprüft.
Bei einer fehlenden oder ungültigen Konfiguration zeigt die App einen
verständlichen Fehler im Research-Bereich; Finanzübersicht und Vergleich bleiben
verfügbar. Es werden keine Ersatzschwellen verwendet.

Beispiel: In `ebit_margin_decline` ändert `red: -250` die rote Schwelle auf
−250 Basispunkte. Danach **Analyse berechnen** erneut klicken; erst dann werden
die Regeln neu eingelesen. Der bisherige Rückgang von −200 bps wäre nun gelb.
Später kann `load_flag_rules(path)` beispielsweise getrennte Dateien für
Industrie oder Healthcare laden. Die Engine und ihre Finanzformeln bleiben gleich;
eine automatische Sektorauswahl ist noch nicht implementiert.

## Manuelle Analyse in Phase 2

1. Wähle zuerst zwei oder drei Perioden. Mit **Synthetische Beispieldaten
   verwenden** werden die vorhandenen JSON-Beispiele geladen: bei zwei Perioden
   FY2024/FY2025, bei drei FY2023/FY2024/FY2025. Dieser Button berechnet noch nichts.
2. Trage Unternehmen, Währung und Einheit ein. Erfasse in jedem Perioden-Tab
   Bezeichnung, Stichtag, Monatsanzahl und die verfügbaren Finanzwerte.
3. Prüfe deine Eingaben und klicke **Analyse berechnen**. Fehler werden auf
   Deutsch angezeigt. Gleiche Labels und inkompatible Periodendauern verhindern
   die Analyse; es gibt keine automatische Umrechnung oder Annualisierung.
4. Die **Finanzübersicht** zeigt Beträge, Margen, Free Cashflow, Nettoverschuldung,
   Leverage und Working-Capital-Kennzahlen. Der **Periodenvergleich** zeigt
   Wachstum, Margenänderungen in Basispunkten und Leverage-Differenzen. Auch
   unsortierte Eingaben werden durch `FinancialHistory` chronologisch angeordnet.

Leere Finanzfelder ergeben `None`, nicht null. `0` bleibt ein echter Nullwert.
Akzeptierte Formate sind beispielsweise `1100`, `1'100`, `1’100`, `1 100`,
`1100.5`, `1100,5` und `1’100,5`. Punkt oder Komma ist ausschliesslich ein
Dezimaltrenner; Tausendergruppen müssen vollständig sein. Mehrdeutige Mischformen
wie `1.100,5` werden abgewiesen. Capex darf positiv oder negativ eingegeben werden;
seine Normalisierung übernimmt ausschliesslich die bestehende Finanzlogik.

Ausgewiesene und berechnete Werte werden getrennt angezeigt. Vollständig fehlende
optionale Zeilen werden ausgeblendet; sonst bedeutet `–`: fehlend oder nicht
berechenbar. Nur die Anzeige wird gerundet. Die Eingaben und Ergebnisse bleiben
ungerundet. Die Ergebnisse beziehen sich auf den letzten erfolgreichen Klick
auf **Analyse berechnen**; nach Änderungen musst du erneut berechnen.

Die manuelle Eingabe erzwingt keine PDF-Herkunft und übernimmt keine Werte aus
dem separaten Dokumentbrowser. Daten und Ergebnisse bleiben in der jeweiligen Browser-Sitzung;
eine dauerhafte Speicherung oder ein Export ist noch nicht enthalten.

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
- `src/research_update_assistant/history_workspace.py`: Report-Snapshots, Observations, Rundungsprüfung und Quellenauflösung.
- `src/research_update_assistant/analysis_selection.py`: Flexibler Trendzeitraum und genau ein ausgewähltes Vergleichspaar.
- `src/research_update_assistant/results_update.py`: Testbarer Builder und unveränderliche Präsentationsmodelle für das Ergebnis-Update.
- `src/research_update_assistant/results_update_ui.py`: Kompakte Headline-Karten, Veränderungen, Flags, Charts und Quellen.
- `src/research_update_assistant/expectation_models.py`: Unveränderliche Erwartungs-Snapshots und Surprise-Ergebnisse.
- `src/research_update_assistant/expectations.py`: Validierung und neutrale Actual-vs-Estimate-Berechnungen.
- `src/research_update_assistant/expectations_ui.py`: Kompakte Erfassung, Auswahl und Herkunftsanzeige der Erwartungen.
- `src/research_update_assistant/history_ui.py`: Lokaler Historienbereich, Konfliktprüfung und Periodenauswahl.
- `src/research_update_assistant/source_ui.py`: Gemeinsame Anzeige der Provenance und Analystenkorrekturen.
- `src/research_update_assistant/ui.py`: Manuelles Formular, Analyst-Dashboard und Ergebnistabellen, ohne Finanzformeln.
- `src/research_update_assistant/document_models.py`: Dokumente, Seiten, Roh-Tabellen und Suchtreffer.
- `src/research_update_assistant/pdf_extractor.py`: Unabhängige PDF-Extraktion, Qualitätsdiagnose und Textsuche.
- `src/research_update_assistant/pdf_ui.py`: PDF-Uploader, Dokumentübersicht und Seiten-/Suchbrowser.
- `config/metrics.yaml`: Stabile Kennzahl-IDs und konfigurierbare Synonyme.
- `src/research_update_assistant/candidate_models.py`: Unbestätigte Kennzahl-/Periodenvorschläge mit Quellen.
- `src/research_update_assistant/metric_mapping.py`: Geprüfte YAML-Konfiguration und Label-Zuordnung.
- `src/research_update_assistant/statement_detection.py`: Mehrere Signale für Statement-Seiten und Quellenpriorität.
- `src/research_update_assistant/layout_parser.py`: Zeilen, Spaltenheader und numerische Zellen.
- `src/research_update_assistant/financial_parser.py`: Kandidaten aus Tabellen, Layout und Textfallback.
- `src/research_update_assistant/validation.py`: Bestätigte Observations und explizite Historienübernahme.
- `src/research_update_assistant/validation_ui.py`: Analystenprüfung, Korrektur und Bestätigung.
- `src/research_update_assistant/charts.py`: Unabhängige Plotly-Figures aus vorhandenen Periodenwerten und Kennzahlen.
- `src/research_update_assistant/input_parsing.py`: Zahlen-Parsing, Eingabevalidierung und Periodenerstellung.
- `src/research_update_assistant/formatting.py`: Anzeige von Beträgen, Prozentwerten, Multiplikatoren und Basispunkten.
- `src/research_update_assistant/sample_data.py`: Gemeinsamer Loader der JSON-Beispiele für UI und Terminal.
- `src/research_update_assistant/flags.py`: ResearchFlag-Dataclass und unabhängige Regel-Engine.
- `src/research_update_assistant/flag_config.py`: Geprüfte Konfiguration und sicherer YAML-Loader.
- `config/flag_rules.yaml`: Konfigurierbare Research-Schwellen.
- `config/`: Regeln und Platz für spätere Finanzbegriffe.
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
