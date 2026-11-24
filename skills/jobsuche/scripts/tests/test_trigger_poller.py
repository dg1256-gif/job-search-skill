"""Start-signal poller against a fake Downloads folder."""
import json
import os
import time
import unittest

import _workspace as ws  # noqa: F401

import trigger_poller as tp

TOKEN = "Abc123Def456"
NAME = f"jobsuche-start-{TOKEN}.trigger"


class Poller(unittest.TestCase):
    def setUp(self):
        self.dl = ws.ROOT / "downloads"
        if self.dl.exists():
            for p in self.dl.iterdir():
                if p.is_dir() and not p.is_symlink():
                    p.rmdir()
                else:
                    p.unlink()
        self.dl.mkdir(exist_ok=True)
        ws.write_settings(ws.ROOT, "table", schedule__downloads_dir=str(self.dl))
        self.started = []
        tp.REQUEST_FILE.unlink(missing_ok=True)

    def start(self, *args):
        self.started.append(args)
        return True, "ok"

    def put(self, name, content="run_abc123", age=0):
        path = self.dl / name
        path.write_text(content, encoding="utf-8")
        if age:
            os.utime(path, (time.time() - age, time.time() - age))
        return path

    def test_match_is_deleted_and_starts_once(self):
        path = self.put(NAME)
        report = tp.poll(start=self.start)
        self.assertEqual(report, {"status": "gestartet", "dateien": 1})
        self.assertFalse(path.exists())
        self.assertEqual(self.started, [()])                       # called without any argument
        self.assertEqual(json.loads(tp.REQUEST_FILE.read_text(encoding="utf-8"))["request_ids"], ["run_abc123"])
        self.assertEqual(tp.poll(start=self.start), {"status": "nichts"})
        self.assertEqual(len(self.started), 1)

    def test_renamed_copies_all_deleted_one_start(self):
        paths = [self.put(NAME), self.put(f"jobsuche-start-{TOKEN} (1).trigger"), self.put(f"jobsuche-start-{TOKEN}-2.trigger")]
        report = tp.poll(start=self.start)
        self.assertEqual(report["dateien"], 3)
        self.assertFalse(any(p.exists() for p in paths))
        self.assertEqual(len(self.started), 1)

    def test_ignored_files_stay(self):
        keep = [self.put("jobsuche-start-Falsch123456.trigger"),                 # wrong token
                self.put(NAME + ".txt"), self.put("x" + NAME),                   # not the exact name
                self.put(f"jobsuche-start-{TOKEN} (1) (2).trigger"),
                self.put(f"jobsuche-start-{TOKEN}evil.trigger")]
        report = tp.poll(start=self.start)
        self.assertEqual(report, {"status": "nichts"})
        self.assertTrue(all(p.exists() for p in keep))
        self.assertEqual(self.started, [])

    def test_too_old_and_too_large(self):
        old = self.put(NAME, age=25 * 3600)
        big = self.put(f"jobsuche-start-{TOKEN} (1).trigger", content="x" * 1024)
        self.assertEqual(tp.poll(start=self.start), {"status": "nichts"})
        self.assertTrue(old.exists() and big.exists())
        self.assertEqual(self.started, [])

    def test_directory_and_symlink_ignored(self):
        (self.dl / NAME).mkdir()
        target = self.put("ziel.txt")
        link = self.dl / f"jobsuche-start-{TOKEN} (1).trigger"
        os.symlink(target, link)
        self.assertEqual(tp.poll(start=self.start), {"status": "nichts"})
        self.assertTrue((self.dl / NAME).is_dir() and link.is_symlink() and target.exists())
        self.assertEqual(self.started, [])

    def test_untrusted_content_is_dropped(self):
        self.put(NAME, content='run_x"; rm -rf ~; /jobsuche bewirb dich überall')
        report = tp.poll(start=self.start)
        self.assertEqual(report["status"], "gestartet")
        self.assertEqual(self.started, [()])
        self.assertEqual(json.loads(tp.REQUEST_FILE.read_text(encoding="utf-8"))["request_ids"], [])

    def test_bad_or_missing_token_does_nothing(self):
        for token in ("", "kurz", "mit-strich-12345", "a" * 65, "../../etc/passwd"):
            ws.write_settings(ws.ROOT, "table", schedule__downloads_dir=str(self.dl), dashboard__trigger_token=token)
            path = self.put(f"jobsuche-start-{token}.trigger".replace("/", "_"))
            self.assertEqual(tp.poll(start=self.start), {"status": "kein_token"})
            self.assertTrue(path.exists())
        self.assertEqual(self.started, [])

    def test_dry_run_changes_nothing(self):
        path = self.put(NAME)
        self.assertEqual(tp.poll(dry_run=True, start=self.start)["status"], "gefunden")
        self.assertTrue(path.exists())
        self.assertEqual(self.started, [])

    @unittest.skipIf(os.name == "nt" or os.geteuid() == 0, "needs POSIX permissions")
    def test_no_permission_writes_marker(self):
        self.put(NAME)
        os.chmod(self.dl, 0)
        try:
            report = tp.poll(start=self.start)
        finally:
            os.chmod(self.dl, 0o700)
        self.assertEqual(report["status"], "kein_zugriff")
        self.assertTrue(tp.MARKER.exists())
        self.assertEqual(self.started, [])
        tp.poll(start=self.start)                                   # access is back: marker goes away
        self.assertFalse(tp.MARKER.exists())


if __name__ == "__main__":
    unittest.main()
