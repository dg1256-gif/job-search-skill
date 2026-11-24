#!/usr/bin/env python3
"""Humanizer check for application texts (cover letter, CV summary, form free text), German and English.

Deterministic half of the humanizer pass described in references/humanizer.md: it finds the
patterns readers recognise as machine-written and says how to fix them. It never rewrites text
itself - the rewrite is done by the writing agent, then this check runs again.

Method adapted from "linkedin-humanizer" V3 by Sergey Bulaev (MIT licence, see NOTICE.md),
reworked for application documents and extended with German rules.

  python 08_Scripts/humanizer.py check --file text.txt --lang de        exit 1 on a "block" finding
  python 08_Scripts/humanizer.py check --text "..." --lang en --json

  audit(text, lang)                  -> [{"level": "block"|"warn", "rule", "hit", "hint", "paragraph"}]
  audit_paragraphs(paragraphs, lang) -> same; "paragraph" is the index into the list

Principles (kept from the method):
  - Leakage is always an error; vocabulary is scored by density per paragraph (one marker is
    normal language, three in one paragraph are a signature and the paragraph is rewritten).
  - Dashes are capped, not banned. Staged rhythm (fragment stacks) is a tell, not a fix.
  - A text that is clean stays untouched: no finding, no edit.
"""
import argparse
import json
import re
import sys
from pathlib import Path

DENSITY_BLOCK = 3      # markers in one paragraph -> rewrite the paragraph
DENSITY_WARN = 2       # -> replace the weaker one
FRAGMENT_WORDS = 3     # a "sentence" of up to this many words is a fragment
FRAGMENT_CAP = 2       # standalone fragments allowed per text

# ---- always an error: model leakage and unfilled templates -------------------------------------
FORENSIC = [
    (r"\boaicite\b|\bcontentReference\b|\bturn\d+search\d+\b|\battached_file\b|\bgrok_card\b|\boai_citation\b",
     "Werkzeug-Rest eines KI-Modells"),
    (r"as of my (last update|knowledge cutoff|training cutoff)|my (knowledge|training data) (cuts off|extends to)"
     r"|i cannot provide (real-time|current|up-to-date)|as an ai (language )?model"
     r"|als ki(-sprachmodell| sprachmodell|-modell)?\b[^.]{0,40}\b(kann|habe|bin)\b|mein wissensstand (reicht|endet)",
     "Hinweis auf Wissensstand/KI-Modell"),
    (r"\[(your|ihr|ihre|dein|deine|name|date|datum|firma|company|topic|insert|describe|einfügen|unternehmen|position|stelle)\b[^\]]{0,40}\]"
     r"|\{\{[^}]{0,40}\}\}|<[A-ZÄÖÜ_ ]{3,}>|\b20\d\d-XX-XX\b|\bTBD\b|\bXXX+\b|lorem ipsum",
     "nicht ausgefüllter Platzhalter"),
    (r"^(here is|here's|sure[,!]|certainly[,!]|hier ist (dein|ihr|das|der|die)|gerne[,!]|natürlich[,!]) [^\n]{0,80}(anschreiben|cover letter|text|entwurf|draft|version)",
     "Antwort-Floskel eines Assistenten im Text"),
    (r"(i hope this (helps|letter finds you well)|let me know if you('d| would) like|ich hoffe,? das hilft|soll ich (noch )?etwas anpassen)",
     "Assistenten-Floskel"),
]

# ---- always an error in an application: generic phrases that say nothing about this candidate -----
GENERIC = {
    "en": [r"what attracts me", r"excited to apply", r"i am excited", r"passionate about", r"my passion",
           r"innovative company", r"dynamic environment", r"perfectly aligns?", r"strongly appeals to me",
           r"thrilled", r"i am writing to (apply|express)", r"fast-paced", r"team player",
           r"proven track record", r"hit the ground running", r"i am confident that", r"unique blend",
           r"in today'?s [a-z-]+ (world|market|landscape|economy)", r"game-?changer", r"testament to",
           r"deep dive", r"paradigm shift", r"at the end of the day", r"thinks? outside the box",
           r"results-driven", r"detail-oriented", r"self-starter", r"go-getter", r"wealth of experience"],
    "de": [r"weckt mein (großes |besonderes )?interesse", r"mit (großem|großer) (interesse|begeisterung|freude)",
           r"hiermit bewerbe ich mich", r"dynamisch(es|en|e)? (umfeld|unternehmen|team)",
           r"innovativ(es|en|e)? (unternehmen|umfeld)", r"leidenschaft", r"teamplayer", r"besonders reizt",
           r"hochmotiviert", r"schnelle auffassungsgabe", r"in der heutigen (zeit|welt|arbeitswelt)",
           r"in einer welt,? in der", r"bin ich (fest )?(davon )?überzeugt,? dass", r"perfekt(e)? (ergänzung|passung|zu)",
           r"über den tellerrand", r"hands-on-mentalität", r"brenne (ich )?für", r"begeistert mich seit jeher",
           r"stellt für mich (die|eine) ideale", r"spannende (herausforderung|aufgabe|position|stelle)",
           r"neue herausforderung", r"zu ihrem (erfolg|unternehmenserfolg) beitragen", r"mehrwert (schaffen|bieten|liefern)"],
}

# ---- single hit is enough: reveal bridges, performed sincerity, "not only ... but also" -----------
REVEAL = {
    "en": [r"(?m)^the (result|outcome|answer|lesson|catch|kicker|truth)\?", r"(?m)^here'?s (what|how|why|the thing)\b",
           r"(?m)^(plot twist|spoiler|the twist)[:?]", r"\b(why|how)\? (because|simple|easy)\b",
           r"\bthe (harsh|hard|uncomfortable|simple) (truth|reality) is\b"],
    "de": [r"(?m)^das (ergebnis|resultat|fazit)\?", r"(?m)^die (antwort|lösung|erkenntnis|wahrheit|folge)\?",
           r"(?m)^(und )?(genau )?(hier|da) (kommt|liegt|setzt)\b[^.]{0,30}\b(ins spiel|der punkt|an)\b",
           r"\b(warum|wieso|weshalb)\? (weil|ganz einfach|einfach)\b", r"\bdie (harte|unbequeme|einfache) wahrheit (ist|lautet)\b",
           r"(?m)^kurz gesagt[:,]", r"(?m)^was (bedeutet|heißt) das( konkret)?\?"],
}
SINCERITY = {
    "en": [r"(?m)^(let me be (honest|real|direct|clear)|i'?ll be (honest|real|direct)|honestly[?,]|to be (direct|honest|fair|transparent)"
           r"|real talk|full transparency|not gonna lie|unpopular opinion)\b",
           r"\b(i (might|may|could) be wrong,? but|in my humble opinion|i think it'?s fair to say)\b"],
    "de": [r"(?m)^(ehrlich gesagt|offen gesagt|um ehrlich zu sein|ganz ehrlich|lassen sie mich (offen|ehrlich|direkt) sein"
           r"|um es (klar|direkt|offen) zu sagen|hand aufs herz)\b",
           r"\b(ich mag mich (täuschen|irren),? aber|meiner bescheidenen meinung nach|ich wage zu behaupten)\b"],
}
NEG_PARALLEL_HARD = {
    "en": [r"\bnot only\b.{0,80}\bbut also\b", r"\bit'?s not (just |about )?\w[^,.]{0,40}, it'?s\b",
           r"\b\w+ isn'?t (just )?\w[^,.]{0,40}, it'?s\b", r"\bthis isn'?t \w[^.]{0,40}\. this is\b",
           r"\bnot just\b.{0,60}\bbut\b"],
    "de": [r"\bnicht nur\b.{0,80}\bsondern (auch|vielmehr)\b", r"\bnicht (bloß|allein|lediglich)\b.{0,80}\bsondern\b",
           r"\bes geht nicht (nur )?um\b.{0,60}\bsondern um\b", r"\bdas ist (kein|keine|nicht)\b[^.]{0,40}\. das ist\b",
           r"\bweniger\b.{0,50}\bals vielmehr\b"],
}
NEG_PARALLEL_SOFT = {   # plain contrast; legitimate for facts ("nicht in A, sondern in B"), so only a warning
    "en": [r"\bnot \w[^,.]{0,40}, but \w"],
    "de": [r"\bnicht \w[^,.]{0,40}, sondern \w"],
}

# ---- density-scored vocabulary: one per paragraph is language, three are a signature -------------
VOCAB = {
    "en": [r"significant(ly)?", r"crucial(ly)?", r"notably", r"particularly", r"comprehensive", r"insights?", r"robust",
           r"leverag(e|es|ed|ing)", r"foster(s|ed|ing)?", r"landscape", r"nuanced", r"multifaceted", r"holistic",
           r"streamlin(e|es|ed|ing)", r"elevat(e|es|ed|ing)", r"empower(s|ed|ing)?", r"utiliz(e|es|ed|ing)",
           r"facilitat(e|es|ed|ing)", r"harness(es|ed|ing)?", r"unlock(s|ed|ing)?", r"navigat(e|es|ed|ing)",
           r"seamless(ly)?", r"ecosystem", r"spearhead(ed|ing)?", r"cutting-edge", r"synerg(y|ies)", r"pivotal",
           r"fundamentally", r"essentially", r"ultimately", r"arguably", r"undoubtedly", r"furthermore", r"moreover",
           r"additionally", r"delv(e|es|ed|ing)", r"tapestry", r"realm", r"showcas(e|es|ed|ing)", r"underscor(e|es|ed|ing)",
           r"rapidly evolving", r"fast-evolving", r"ever-changing", r"driv(e|es|ing) (innovation|growth|value|impact)"],
    "de": [r"maßgeblich", r"ganzheitlich\w*", r"nahtlos\w*", r"umfassend\w*", r"entscheidend\w*", r"wesentlich\w*",
           r"insbesondere", r"darüber hinaus", r"zudem", r"des weiteren", r"ferner", r"synergien?", r"mehrwert",
           r"zielgerichtet\w*", r"zielführend\w*", r"nachhaltig\w*", r"innovativ\w*", r"dynamisch\w*", r"spannend\w*",
           r"vielfältig\w*", r"facettenreich\w*", r"vielschichtig\w*", r"ökosystem\w*", r"befähig\w+", r"vorantreib\w+",
           r"voranzutreiben", r"vorangetrieben", r"optimal\w*", r"essenziell\w*", r"essentiell\w*", r"letztendlich",
           r"grundlegend\w*", r"zweifellos", r"zweifelsohne", r"fundiert\w*", r"tiefgreifend\w*", r"wertvoll\w*",
           r"schlüsselrolle", r"expertise", r"lösungsorientiert\w*", r"proaktiv\w*", r"agil\w* (umfeld|mindset)",
           r"schnelllebig\w*", r"robust\w*", r"hebel\w*", r"unter beweis (stellen|gestellt)"],
}
GRAMMAR = {
    "en": [("ing-Einstieg", r"(?m)(?:^|(?<=[.!?] ))[A-Z][a-z]+ing\b[^.]{0,60},"),
           ("Nominalisierung", r"\bthe \w+(?:tion|sion|ment|ance|ence|ization|isation) of\b"),
           ("Abstrakta-Kette", r"\b(alignment|transformation|optimization|innovation|efficiency|scalability|synergy)\b.{0,40}"
                               r"\b(alignment|transformation|optimization|innovation|efficiency|scalability|synergy)\b")],
    "de": [("Nominalisierung", r"\b(die|der|eine|einer) \w+(?:ierung|isierung) (der|des|von)\b"),
           ("Abstrakta-Kette", r"\b(transformation|optimierung|innovation|effizienz|skalierbarkeit|digitalisierung|exzellenz)\b.{0,40}"
                               r"\b(transformation|optimierung|innovation|effizienz|skalierbarkeit|digitalisierung|exzellenz)\b"),
           ("Partizip-Einstieg", r"(?m)(?:^|(?<=[.!?] ))(Aufbauend|Basierend|Ausgehend|Gestützt) auf\b[^.]{0,60},")],
}

HOLLOW = {
    "dynamic", "vibrant", "innovative", "faster", "cheaper", "better", "simple", "effective", "easy", "bold", "clear",
    "focused", "scalable", "powerful", "growth", "impact", "value", "alignment", "innovation", "efficiency", "results",
    "success", "clarity", "scale", "momentum", "consistency", "mindset", "strategy", "vision", "reliable", "motivated",
    "flexible", "dedicated", "committed", "structured", "analytical", "strategic", "creative",
    "dynamisch", "innovativ", "schnell", "einfach", "effektiv", "effizient", "klar", "fokussiert", "skalierbar",
    "wachstum", "wirkung", "wert", "erfolg", "klarheit", "strategie", "vision", "zuverlässig", "motiviert",
    "flexibel", "engagiert", "strukturiert", "analytisch", "strategisch", "kreativ", "belastbar", "teamfähig",
    "zielstrebig", "kommunikativ", "lösungsorientiert", "verantwortungsbewusst", "sorgfältig", "eigenständig",
}
SUBORDINATORS = re.compile(r"\b(because|which|when|after|while|although|since|that|whereas|weil|der|die|das|dass|als|"
                           r"nachdem|während|obwohl|wobei|wodurch|sodass|indem|da|wenn|bevor)\b", re.I)
ABBREV = re.compile(r"\b(z\. ?B|d\. ?h|u\. ?a|bzw|ca|inkl|ggf|vgl|Nr|Dr|Prof|Dipl|Ing|M\. ?Sc|B\. ?Sc|e\. ?g|i\. ?e|"
                    r"etc|vs|Mr|Mrs|Ms|Inc|Ltd|Co|St|approx|No)\.", re.I)


def _lang(lang):
    return "de" if str(lang or "").lower().startswith("de") else "en"


def _sentences(paragraph):
    text = ABBREV.sub(lambda m: m.group(0).replace(".", "\u2024"), paragraph)
    text = re.sub(r"(\d)\.(?=\s?\d|\s[a-zäöü])", "\\1\u2024", text)        # 3. Quartal, 1.5
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.replace("\u2024", ".") for p in parts if p.strip()]


def _snip(text, limit=70):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _find(patterns, text):
    hits = []
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.I):
            hits.append(m.group(0))
    return hits


def _triads(text):
    found = []
    for m in re.finditer(r"\b([\wäöüÄÖÜß-]+), ([\wäöüÄÖÜß-]+),? (?:and|und|sowie) ([\wäöüÄÖÜß-]+)\b", text):
        found.append((m.group(0), [g.lower() for g in m.groups()]))
    return found


def audit_paragraphs(paragraphs, lang="de"):
    lang = _lang(lang)
    paragraphs = [str(p) for p in paragraphs if str(p).strip()]
    full = "\n".join(paragraphs)
    out = []

    def add(level, rule, hit, hint, paragraph=None):
        out.append({"level": level, "rule": rule, "hit": _snip(hit), "hint": hint, "paragraph": paragraph})

    fragments, triads_total = 0, 0
    for i, para in enumerate(paragraphs):
        for pat, label in FORENSIC:
            for m in re.finditer(pat, para, flags=re.I | re.M):
                add("block", "leakage", m.group(0), f"{label}: ersatzlos entfernen bzw. echten Inhalt einsetzen", i)
        for both in ("de", "en"):                       # a German letter may quote English phrases and vice versa
            for hit in _find(GENERIC[both], para):
                add("block", "generic", hit, "Floskel streichen; an ihre Stelle gehört eine belegte Tatsache aus dem Profil", i)
        always = 0
        for hit in _find(REVEAL[lang], para):
            always += 1
            add("block", "reveal_bridge", hit, "Überleitung streichen, der folgende Satz trägt die Aussage allein", i)
        for hit in _find(SINCERITY[lang], para):
            always += 1
            add("block", "sincerity", hit, "Ankündigung streichen und die Tatsache ohne Rahmen nennen", i)
        for hit in _find(NEG_PARALLEL_HARD[lang], para):
            always += 1
            add("block", "neg_parallel", hit, "als zwei einfache Aussagesätze schreiben", i)
        hard = " ".join(_find(NEG_PARALLEL_HARD[lang], para))
        for hit in _find(NEG_PARALLEL_SOFT[lang], para):
            if hit.lower() not in hard.lower():
                add("warn", "contrast", hit, "nur lassen, wenn es eine sachliche Abgrenzung ist; sonst zwei Aussagesätze", i)

        markers = [h for h in _find([rf"\b(?:{p})\b" for p in VOCAB[lang]], para)]
        for name, pat in GRAMMAR[lang]:
            if re.search(pat, para, flags=re.I if name != "ing-Einstieg" and name != "Partizip-Einstieg" else 0):
                markers.append(name)                    # each grammar marker counts once per paragraph
        if len(markers) >= DENSITY_BLOCK:
            add("block", "density", ", ".join(markers), f"{len(markers)} Marker in einem Absatz: den Absatz neu schreiben "
                "(Akteur zuerst, Verb statt Substantiv, Zahl statt Wertung), nicht Wort für Wort ersetzen", i)
        elif len(markers) == DENSITY_WARN:
            add("warn", "density", ", ".join(markers), "zwei Marker: den schwächeren ersetzen, den anderen lassen", i)

        sents = _sentences(para)
        words = [len(s.split()) for s in sents]
        if len(sents) == 1 and words[0] == 1 and len(paragraphs) > 1:
            add("block", "staccato", para, "Ein-Wort-Absatz: in den Nachbarsatz einbauen", i)
        run = 0
        for s, n in zip(sents, words):
            run = run + 1 if n <= FRAGMENT_WORDS else 0
            if n <= FRAGMENT_WORDS and len(sents) > 1:
                fragments += 1
            if run == 3:
                add("block", "staccato", s, "Fragment-Kette: zu einem vollständigen Satz mit echtem Nebensatz verbinden", i)
        if re.search(r"\b(no|kein|keine) \w+[.,] (no|kein|keine) \w+[.,] (just|only|nur|einfach) \w+", para, flags=re.I):
            add("block", "staccato", para, "„Kein X. Kein Y. Nur Z.“ ist eine gestellte Figur: als normalen Satz schreiben", i)
        if len(sents) >= 4 and all(abs(n - sum(words) / len(words)) <= 3 for n in words) \
                and not any(SUBORDINATORS.search(s) for s in sents):
            add("warn", "flat_rhythm", sents[0], "alle Sätze gleich lang und ohne Nebensatz: EINEN Satz mit seinem Nachbarn "
                "über weil/als/wodurch verbinden, sonst nichts ändern", i)

        for hit, items in _triads(para):
            triads_total += 1
            if all(x in HOLLOW for x in items):
                add("block", "hollow_triad", hit, "austauschbare Dreierreihe: zwei belegte Punkte nennen oder streichen", i)
        if re.search(r"[“”„‚‘]", para) and lang == "en" and re.search(r"„", para):
            add("warn", "quotes", "„", "deutsche Anführungszeichen im englischen Text", i)
        if ";" in para:
            add("warn", "semicolon", para[max(0, para.find(";") - 30):para.find(";") + 10], "Semikolon im Fließtext: lieber zwei Sätze", i)

    total_words = len(full.split())
    dashes = len(re.findall(r"\s[–—]\s|\w—\w|\s--\s", full))
    cap = max(1, min(2, round(total_words / 100)))
    if dashes > cap:
        add("block", "dash_density", f"{dashes} Gedankenstriche auf {total_words} Wörter",
            f"höchstens {cap}: die übrigen durch Komma, Doppelpunkt oder Klammern ersetzen, nie durch einen Punkt")
    if "—" in full:
        add("warn", "em_dash", "—", "Geviertstrich: in deutschen Texten den Halbgeviertstrich (–) mit Leerzeichen verwenden, sparsam")
    if fragments > FRAGMENT_CAP:
        add("warn", "fragments", f"{fragments} Kurz-Sätze", f"höchstens {FRAGMENT_CAP} alleinstehende Fragmente im ganzen Text")
    if triads_total >= 3:
        add("warn", "triads", f"{triads_total} Dreierreihen", "auf eine natürliche, konkrete Dreierreihe reduzieren")
    if total_words >= 150:
        if not re.search(r"\d", full):
            add("warn", "concreteness", "keine Zahl im Text", "eine belegte Zahl mit Bezug nennen (wer, was, wann) – nur aus dem "
                "Kandidatenprofil, nie erfinden; gibt es keine, den Nutzer fragen oder ohne Zahl lassen")
        starts = [re.match(r"\W*(\w+)", p).group(1).lower() for p in paragraphs if re.match(r"\W*(\w+)", p)]
        first = "ich" if lang == "de" else "i"
        if len(starts) >= 4 and sum(1 for s in starts if s == first) / len(starts) > 0.6:
            add("warn", "monotone_openers", f"{sum(1 for s in starts if s == first)} von {len(starts)} Absätzen beginnen mit „{first.capitalize()}“",
                "ein oder zwei Absätze mit der Sache statt mit der Person beginnen")
    return out


def audit(text, lang="de"):
    paragraphs = [p for p in re.split(r"\n\s*\n|\n", str(text)) if p.strip()]
    return audit_paragraphs(paragraphs, lang)


def verdict(findings):
    if any(f["level"] == "block" for f in findings):
        return "ueberarbeiten"
    return "pruefen" if findings else "sauber"


def format_findings(findings):
    lines = []
    for f in findings:
        where = "" if f.get("paragraph") is None else f" [Absatz {f['paragraph'] + 1}]"
        lines.append(f"{'FEHLER ' if f['level'] == 'block' else 'Hinweis'}{where} {f['rule']}: „{f['hit']}“ → {f['hint']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--file")
    c.add_argument("--text")
    c.add_argument("--lang", default="de")
    c.add_argument("--json", action="store_true")
    sub.add_parser("selftest")
    args = ap.parse_args()
    if args.cmd == "selftest":
        return selftest()
    if not args.file and args.text is None:
        print("Fehler: --file oder --text angeben.")
        sys.exit(2)
    text = Path(args.file).read_text(encoding="utf-8") if args.file else args.text
    findings = audit(text, args.lang)
    if args.json:
        print(json.dumps({"verdict": verdict(findings), "findings": findings}, ensure_ascii=False))
    else:
        print(format_findings(findings) or "keine Auffälligkeiten")
        print("Ergebnis:", verdict(findings))
    sys.exit(1 if verdict(findings) == "ueberarbeiten" else 0)


def selftest():
    def rules(text, lang):
        return {(f["level"], f["rule"]) for f in audit(text, lang)}
    clean_de = ("Bei der Muster GmbH habe ich 2023 die Umstellung von 14 Werken auf ein gemeinsames Planungssystem geleitet. "
                "Der Zeitplan hielt, weil wir die Werksleiter früh eingebunden haben.\n"
                "Ihre Anzeige nennt die Einführung eines Portfolio-Prozesses als erste Aufgabe. Einen solchen Prozess habe ich "
                "zweimal aufgebaut, zuletzt für ein Budget von 12 Mio. Euro.")
    clean_en = ("At Example Ltd I led the move of 14 plants to one planning system in 2023. The schedule held because we "
                "involved the plant managers early.\nYour posting names a portfolio process as the first task. I have built "
                "one twice, most recently for a budget of EUR 12 million.")
    cases = [
        (clean_de, "de", set(), "sauberer deutscher Text"),
        (clean_en, "en", set(), "sauberer englischer Text"),
        ("Hiermit bewerbe ich mich mit großem Interesse.", "de", {("block", "generic")}, "Floskeln"),
        ("I am excited to apply. I am a team player.", "en", {("block", "generic")}, "generic phrases"),
        ("Ich habe nicht nur Projekte geleitet, sondern auch Teams aufgebaut.", "de", {("block", "neg_parallel")}, "nicht nur … sondern auch"),
        ("Der Standort liegt nicht in Hamburg, sondern in Bremen.", "de", {("warn", "contrast")}, "sachlicher Gegensatz nur Hinweis"),
        ("Das Ergebnis? 30 Prozent weniger Durchlaufzeit.", "de", {("block", "reveal_bridge")}, "Enthüllungs-Brücke"),
        ("Ehrlich gesagt war das Projekt schwierig und dauerte elf Monate länger als geplant.", "de", {("block", "sincerity")}, "Aufrichtigkeits-Ankündigung"),
        ("Ich habe maßgeblich und ganzheitlich die nachhaltige Transformation vorangetrieben.", "de", {("block", "density")}, "Dichte 3+"),
        ("Darüber hinaus habe ich das Budget von 3 Mio. Euro verantwortet.", "de", set(), "ein Marker bleibt stehen"),
        ("Dear [Your Name], this is the letter.", "en", {("block", "leakage")}, "Platzhalter"),
        ("Schnell. Klar. Wirksam. So arbeite ich in jedem Projekt seit vielen Jahren.", "de", {("block", "staccato")}, "Fragment-Kette"),
        ("Ich arbeite strukturiert, analytisch und zuverlässig in allen Projekten des Hauses.", "de", {("block", "hollow_triad")}, "hohle Dreierreihe"),
        ("Ich habe SAP, Jira und Confluence in 14 Werken eingeführt.", "de", set(), "konkrete Dreierreihe bleibt"),
        ("Das Projekt – ein großes – lief gut – wirklich gut – bis zum Schluss – und darüber hinaus.", "de", {("block", "dash_density")}, "Gedankenstrich-Dichte"),
        ("Leveraging robust insights, I streamlined the comprehensive process.", "en", {("block", "density")}, "density EN"),
    ]
    failed = 0
    for text, lang, expected, name in cases:
        got = rules(text, lang)
        ok = (got == set()) if not expected else expected <= got
        failed += not ok
        print(("OK   " if ok else "FAIL ") + name + ("" if ok else f" → {sorted(got)}"))
    print(f"{len(cases) - failed} von {len(cases)} OK")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
