"""Cover letter, CV and PDF helper against generated neutral templates (no real documents)."""
import copy
import unittest

import _workspace as ws  # noqa: F401  (creates the scratch workspace before settings is imported)

import docx

import cover_letter as cl
import cv_tailor as cv
import docs_pdf

P1 = ("Sie suchen eine Teamleitung, die den Kundenservice der Muster GmbH an zwei Standorten zusammenführt. "
      "Bei der Beispiel AG leite ich seit zwei Jahren ein Team von zwölf Personen und habe dort eine ähnliche "
      "Zusammenlegung von Lager und Kundendienst begleitet.")
P2 = ("Die Bearbeitungszeit für Reklamationen ist in dieser Zeit von neun auf vier Tage gefallen. Erreicht habe "
      "ich das über ein gemeinsames Formular für beide Abteilungen und eine feste Übergabe am Vormittag. Die Zahl "
      "der Rückfragen sank um ein Drittel.")
P3 = ("Neue Kolleginnen und Kollegen arbeite ich selbst ein, zuletzt drei Personen innerhalb eines halben Jahres. "
      "Ab dem 1. März kann ich bei Ihnen anfangen und stelle Ihnen gern vor, wie ich die ersten drei Monate "
      "angehen würde.")
SPEC = {"company": "Muster GmbH", "role": "Teamleitung Kundenservice", "language": "de",
        "subject": "Bewerbung als Teamleitung Kundenservice", "salutation": "Sehr geehrter Herr Muster,",
        "paragraphs": [P1, P2, P3]}


def texts(path):
    return [cl.el_text(el) for _, el in cl.walk(docx.Document(str(path)).element.body)]


class Letter(unittest.TestCase):
    def build(self, layout, name, **over):
        ws.write_settings(ws.ROOT, layout)
        spec = {**copy.deepcopy(SPEC), "output": str(ws.ROOT / "03_Applications" / name), **over}
        out = cl.build(spec)
        return out, spec, cl.validate(out, spec)

    def test_table_layout_keeps_formatting(self):
        out, spec, report = self.build("table", "Anschreiben_Teamleitung_Kundenservice.docx")
        self.assertTrue(report["ok"], report)
        self.assertEqual(cl.fingerprint(out), cl.fingerprint(cl.template_path()))
        got = texts(out)
        self.assertEqual(got[0], "Erika Mustermann")                     # head untouched
        self.assertEqual(got[-1], "Erika Mustermann")                    # signature untouched
        self.assertRegex(got[2], r"^Musterstadt, \d{1,2}\. \w+ \d{4}$")  # date written into the table cell
        self.assertNotIn("Sehr geehrte Frau Beispiel,", got)

    def test_plain_layout_with_recipient(self):
        out, spec, report = self.build("plain", "Anschreiben_Teamleitung_Kundenservice.docx",
                                       recipient=["Muster GmbH", "Herr Muster", "Musterallee 5, 12345 Musterstadt"])
        self.assertTrue(report["ok"], report)
        self.assertEqual(cl.fingerprint(out), cl.fingerprint(cl.template_path()))
        got = texts(out)
        self.assertEqual(got[1:4], ["Muster GmbH", "Herr Muster", "Musterallee 5, 12345 Musterstadt"])
        self.assertRegex(got[4], r"^Musterstadt, \d\d\.\d\d\.\d{4}$")     # date_format from the slots

    def test_plain_layout_other_lengths(self):
        """Fewer recipient lines and one more paragraph: the validator compares with the fitted template."""
        out, spec, report = self.build("plain", "Anschreiben_Teamleitung_Kundenservice.docx", max_pages=2,
                                       recipient=["Muster GmbH", "Musterallee 5, 12345 Musterstadt"],
                                       paragraphs=[P1, P2, P3, "Über eine Einladung zum Gespräch freue ich mich."])
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["body_paragraphs"], 4)
        self.assertEqual(texts(out)[0], "Erika Mustermann · Musterstraße 1 · 12345 Musterstadt")

    def test_humanizer_block_fails(self):
        bad = "Mit großem Interesse habe ich Ihre Anzeige gelesen, denn ich bin ein absoluter Teamplayer. " + P1
        out, spec, report = self.build("table", "Anschreiben_Teamleitung_Kundenservice.docx", paragraphs=[bad, P2, P3])
        self.assertFalse(report["ok"])
        self.assertTrue(report["errors"])

    def test_template_leftover_fails(self):
        out, spec, report = self.build("table", "Anschreiben_Teamleitung_Kundenservice.docx",
                                       paragraphs=[ws.BODY[0], P2, P3])
        self.assertFalse(report["ok"], report)

    def test_wrong_filename_and_salutation(self):
        out, spec, report = self.build("table", "Brief.docx", salutation="Hallo Herr Max Muster,")
        self.assertFalse(report["ok"])
        self.assertGreaterEqual(len(report["errors"]), 2)

    def test_missing_slots_point_to_inspect(self):
        with self.assertRaises(SystemExit) as stop:
            cl.slot_map({})
        self.assertIn("inspect", str(stop.exception))

    def test_inspect_and_suggest(self):
        ws.write_settings(ws.ROOT, "plain")
        rows = cl.inspect(cl.template_path())["paragraphs"]
        self.assertEqual(rows[4]["loc"], "p:4")
        got = cl.suggest_slots(cl.template_path())["slots"]
        for key in ("salutation", "body_first", "body_last", "subject", "closing", "signature", "date"):
            self.assertEqual(got[key], ws.SLOTS["plain"][key], key)
        ws.write_settings(ws.ROOT, "table")
        got = cl.suggest_slots(cl.template_path())["slots"]
        self.assertEqual(got["date"], "tbl:0:0:1:0")
        self.assertEqual((got["salutation"], got["body_first"], got["body_last"]), ("p:2", "p:3", "p:5"))

    def test_browser_slots(self):
        ws.write_settings(ws.ROOT, "table")
        got = cl.browser_slots()
        self.assertEqual((got["subject"], got["salutation"], got["body_start"], got["body_end"], got["closing"]),
                         (0, 2, 3, 6, 6))
        self.assertEqual(got["date"], {"table": 0, "row": 0, "cell": 1, "paragraph": 0})
        self.assertEqual(got["date_prefix"], "Musterstadt, ")


class CV(unittest.TestCase):
    SPEC = {"job_key": "muster-1", "company": "Muster GmbH", "role": "Teamleitung", "language": "de",
            "headline": "Teamleitung Kundenservice",
            "summary": "Teamleiterin im Kundendienst mit vier Jahren Erfahrung. Ich habe die Bearbeitungszeit für "
                       "Reklamationen von neun auf vier Tage gesenkt und führe zwölf Personen.",
            "order": {"station": ["Drei neue", "Team von"], "focus": ["Teamführung"]}}

    def setUp(self):
        ws.write_settings(ws.ROOT, "table")

    def test_build_keeps_bullets(self):
        out = cv.build(dict(self.SPEC))
        report = cv.validate(out, self.SPEC)
        self.assertTrue(report["ok"], report)
        got = texts(out)
        self.assertEqual(got[1], "TEAMLEITUNG KUNDENSERVICE")                 # capitals as in the CV
        start = got.index("Teamleiterin Kundendienst, 2021 bis heute") + 1
        bullets = got[start:start + 4]
        self.assertEqual(sorted(bullets), sorted(ws.CV_BULLETS))             # same set
        self.assertEqual(bullets[:2], [ws.CV_BULLETS[3], ws.CV_BULLETS[1]])  # requested order first
        self.assertEqual(got[got.index("SCHWERPUNKTE") + 1], "Teamführung")
        self.assertEqual(len(got), len(texts(cv.base_docx("de"))))

    def test_changed_bullet_is_an_error(self):
        out = cv.build(dict(self.SPEC))
        d = docx.Document(str(out))
        for p in d.paragraphs:
            if p.text == ws.CV_BULLETS[0]:
                p.runs[0].text = "Bearbeitungszeit halbiert und Umsatz verdoppelt"
        d.save(str(out))
        report = cv.validate(out, self.SPEC)
        self.assertFalse(report["ok"])
        self.assertTrue(any("bullets" in e for e in report["errors"]), report)

    def test_changed_other_paragraph_is_an_error(self):
        out = cv.build(dict(self.SPEC))
        d = docx.Document(str(out))
        d.paragraphs[-1].runs[0].text = "Master of Science, Musteruniversität"
        d.save(str(out))
        self.assertFalse(cv.validate(out, self.SPEC)["ok"])

    def test_ambiguous_or_unknown_order_stops(self):
        with self.assertRaises(SystemExit):
            cv.build({**self.SPEC, "order": {"station": ["Gibt es nicht"]}})
        with self.assertRaises(SystemExit):
            cv.build({**self.SPEC, "order": {"andere": ["Team von"]}})

    def test_without_slots_only_base(self):
        ws.write_settings(ws.ROOT, "table", templates__cv_slots={})
        with self.assertRaises(SystemExit) as stop:
            cv.build(dict(self.SPEC))
        self.assertIn("base", str(stop.exception))

    def test_inspect_marks_bullets(self):
        rows = cv.inspect("de")["paragraphs"]
        self.assertEqual(sum(1 for r in rows if r.get("bullet")), 7)


class Pdf(unittest.TestCase):
    def test_check_never_raises(self):
        report = docs_pdf.check(convert=False)
        self.assertIn("gefunden", report)
        self.assertIsNone(docs_pdf.to_pdf(ws.ROOT / "gibt_es_nicht.docx"))
        self.assertIsNone(docs_pdf.to_pdf(cl.template_path(), engine="none"))


if __name__ == "__main__":
    unittest.main()
