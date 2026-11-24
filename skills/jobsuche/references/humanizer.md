# Humanizer – Pflichtdurchgang für jeden Text an einen Arbeitgeber

Gilt für Anschreiben, Kurzprofil im Lebenslauf, Freitext in Formularen und Mail-Entwürfe, auf
Deutsch und Englisch. Er läuft immer und ohne Aufforderung, bevor ein Text gezeigt, in ein
Dokument gebaut oder in ein Feld getippt wird. Der Nutzer muss ihn nie verlangen.

Zweck: Der Text soll klingen wie von einem Menschen geschrieben, der seine Arbeit kennt. Es
geht nicht darum, Erkennungsprogramme zu überlisten, sondern darum, was ein Personaler beim
dritten Anschreiben des Tages sofort als Baukasten erkennt.

Ablauf: Entwurf → Durchgang 1 bis 4 im Kopf → `humanizer.py check` → Befunde beheben →
erneut prüfen, bis kein FEHLER mehr bleibt.

```
$PY 08_Scripts/humanizer.py check --file <text.txt> --lang de|en
```

`cover_letter.py` und `cv_tailor.py` rufen dieselbe Prüfung beim Bauen auf; FEHLER brechen den
Bau ab, Hinweise erscheinen als Warnung. Für Formular-Freitext und Mail-Entwürfe rufst du die
Prüfung selbst auf.

## Grundsätze

- **Dichte statt Verbotsliste.** Ein einzelnes „darüber hinaus“ ist normale Sprache. Drei
  solche Marker in einem Absatz sind eine Handschrift. Deshalb: ein Marker bleibt, bei zweien
  wird der schwächere ersetzt, bei dreien wird der Absatz neu geschrieben – nicht Wort für
  Wort getauscht, denn das hinterlässt denselben Satzbau mit anderen Wörtern.
- **Nichts erfinden.** Konkreter wird ein Text nur mit Tatsachen aus
  `candidate_profile.md`. Gibt es keine passende Zahl, bleibt der Satz ohne Zahl oder du
  fragst den Nutzer. Keine erfundenen Beispiele, keine vorsichtigen Füllsel als Ersatz.
- **Sauberes bleibt unberührt.** Ein Absatz ohne Befund wird nicht „verbessert“.
- **Die Stimme des Nutzers gewinnt.** `01_Config/writing_style.md` hat Vorrang. Widerspricht
  dort eine belegte Gewohnheit einer Regel hier (er schreibt etwa bewusst mit Semikolon),
  gilt seine Gewohnheit; nenne den Konflikt in einer Zeile. Text, den der Nutzer selbst
  geschrieben oder im Dashboard bearbeitet hat, wird nie umformuliert – dort werden Befunde
  nur gemeldet.

## Durchgang 1 – Entfernen

**Immer, bei jedem Vorkommen:**

- Reste eines Modells oder Werkzeugs (Zitat-Marker, „Stand meines Wissens“, „als KI“),
  Assistenten-Sätze („Hier ist dein Anschreiben“, „Soll ich etwas anpassen?“).
- Nicht ausgefüllte Platzhalter (`[Ihr Name]`, `<FIRMA>`, `XXX`, `TBD`).
- Floskeln, die über diese Person nichts sagen: „hiermit bewerbe ich mich“, „mit großem
  Interesse“, „Leidenschaft“, „Teamplayer“, „hochmotiviert“, „spannende Herausforderung“,
  „excited to apply“, „passionate about“, „proven track record“, „team player“ … An ihre
  Stelle gehört eine belegte Tatsache oder nichts.
- Gedankenstriche über der Obergrenze: höchstens einer je rund 100 Wörter, nie mehr als zwei
  im Text. Überzählige werden zu Komma, Doppelpunkt oder Klammer, nie zu einem Punkt (das
  erzeugt Fragmente). Im Deutschen der Halbgeviertstrich mit Leerzeichen ( – ), kein
  Geviertstrich (—).
- Schluss-Zusammenfassungen („Zusammenfassend lässt sich sagen“, „Kurz gesagt:“).

**Schon beim ersten Vorkommen:**

- Enthüllungs-Brücken: „Das Ergebnis?“, „Die Antwort?“, „Warum? Weil …“, „Here’s what …“.
  Streichen; der folgende Satz trägt die Aussage allein.
- Gegensatz-Figuren: „nicht nur …, sondern auch“, „Es geht nicht um X, sondern um Y“,
  „Das ist kein X. Das ist Y.“ → zwei schlichte Aussagesätze. Eine sachliche Abgrenzung
  („nicht in Hamburg, sondern in Bremen“) darf bleiben.
- Angekündigte Aufrichtigkeit: „Ehrlich gesagt“, „Um es offen zu sagen“, „To be honest“.
  Die Tatsache ohne Rahmen nennen.

**Nach Dichte je Absatz:**

- Füll- und Wertungswörter: maßgeblich, ganzheitlich, nahtlos, umfassend, nachhaltig,
  innovativ, zielgerichtet, Mehrwert, Synergien, darüber hinaus, zudem, insbesondere,
  letztendlich · leverage, robust, seamless, comprehensive, holistic, furthermore, moreover,
  pivotal, foster, streamline, delve …
- Satzbau-Marker: Nominalisierungen („die Optimierung der …“ statt „ich habe … verkürzt“),
  Ketten aus Abstrakta, Partizip-Einstiege („Aufbauend auf …,“ / „Leveraging …,“).
- Dreierreihen aus austauschbaren Eigenschaften („strukturiert, analytisch und zuverlässig“)
  sind immer ein Fehler. Eine Reihe aus konkreten Dingen („SAP, Jira und Confluence“) ist in
  Ordnung; mehr als zwei Dreierreihen im Text sind zu viel.

## Durchgang 2 – Rhythmus

Erst prüfen, dann nur das Nötige ändern. Gestellter Rhythmus fällt stärker auf als gleichmäßiger.

- Keine Fragment-Ketten („Schnell. Klar. Wirksam.“), keine Ein-Wort-Absätze, kein
  „Kein X. Kein Y. Nur Z.“. Höchstens zwei alleinstehende Kurzsätze im ganzen Text.
- Sind in einem Absatz alle Sätze gleich lang und ohne Nebensatz: **einen** Satz mit seinem
  Nachbarn über einen echten Nebensatz verbinden (weil, als, wodurch, nachdem). Mehr nicht.
- Nie einen Satz zerhacken, um Abwechslung zu erzeugen.
- Beginnen fast alle Absätze mit „Ich“ / „I“: ein oder zwei mit der Sache beginnen.

## Durchgang 3 – Konkret machen

Für jede allgemeine Aussage prüfen, ob das Profil sie belegen kann:

- Wertung → Tatsache: „umfangreiche Erfahrung im Projektmanagement“ → was, wie viele, wann,
  mit welchem Ergebnis – in den Worten des Profils.
- Mindestens eine Zahl mit Bezug (wer, was, wann), wenn das Profil eine hergibt.
- Substantiv → Verb mit Akteur: „Verantwortung für die Einführung“ → „Ich habe … eingeführt“.
- Bezug zur Anzeige über eine konkrete Aufgabe aus der Anzeige, nicht über Lob für das
  Unternehmen.
- Eine Lücke offen benennen und einordnen, statt sie zu umschreiben.

Gibt das Profil nichts her: die Aussage streichen oder den Nutzer fragen. Nie auffüllen.

## Durchgang 4 – Gegenprobe

Vor der Prüfung einmal ganz lesen, als wärst du der Empfänger:

1. Stimmt jede Aussage mit `candidate_profile.md` überein? Keine neue Tatsache hineingerutscht?
2. Überkorrektur? Zu knapp, abgehackt, betont lässig, künstlich „menschliche“ Fehler? Dann
   zurück zur schlichten Fassung. Ein Anschreiben bleibt förmlich.
3. Würde der Nutzer den Satz so am Telefon sagen? Wenn nicht, einfacher schreiben.
4. Länge, Anrede, Betreff und Sprache passen zu `references/anschreiben-cv.md`.

Dann `humanizer.py check`. FEHLER beheben und erneut prüfen. Hinweise einzeln abwägen: Ein
Hinweis darf stehen bleiben, wenn die Stelle sachlich richtig und natürlich ist.

## Was dem Nutzer gezeigt wird

Den fertigen Text. Darunter höchstens eine Zeile, wenn etwas offen ist – etwa „Keine belegte
Zahl für Absatz 3 im Profil; soll eine ergänzt werden?“ oder ein Stilkonflikt mit
`writing_style.md`. Keine Liste der vorgenommenen Korrekturen, außer er fragt danach.
