"""Assistant start command, lock and scheduler output (dry runs only; nothing is installed)."""
import os
import plistlib
import time
import unittest
from unittest import mock

import _workspace as ws  # noqa: F401

import run_local as rl
import schedule_install as si


def found(name):
    return f"/opt/test/bin/{name}"


class AgentCommand(unittest.TestCase):
    def cmd(self, kind="daily", **conf):
        with mock.patch.object(rl, "find_binary", side_effect=found):
            return rl.agent_command(kind, conf)

    def test_presets(self):
        self.assertEqual(self.cmd(cli="claude"), ["/opt/test/bin/claude", "/jobsuche lauf"])
        self.assertEqual(self.cmd("requested", cli="claude", model="opus"),
                         ["/opt/test/bin/claude", "--model", "opus", "/jobsuche lauf --angefragt"])
        other = rl.PROMPTS["other"]
        self.assertEqual(self.cmd(cli="codex", model="gpt-5"), ["/opt/test/bin/codex", "-m", "gpt-5", other["daily"]])
        self.assertEqual(self.cmd(cli="gemini"), ["/opt/test/bin/gemini", "-i", other["daily"]])
        self.assertEqual(self.cmd("requested", cli="grok"), ["/opt/test/bin/grok", other["requested"]])
        self.assertEqual(set(rl.AGENT_PRESETS), {"claude", "codex", "gemini", "grok"})

    def test_custom_command(self):
        got = self.cmd(cli="custom", model="org/model:1", command='mein-agent --modell {model} --start "{prompt}"')
        self.assertEqual(got, ["/opt/test/bin/mein-agent", "--modell", "org/model:1", "--start", rl.PROMPTS["other"]["daily"]])
        with self.assertRaises(rl.StartError):
            self.cmd(cli="custom", command="mein-agent --ohne-platzhalter")
        with self.assertRaises(rl.StartError):
            self.cmd(cli="custom", command="mein-agent {model} {prompt}")
        with self.assertRaises(rl.StartError):
            self.cmd(cli="custom")

    def test_model_is_validated(self):
        for bad in ("opus; rm -rf ~", "a b", "$(id)", "x" * 81, "modell`id`", '"'):
            with self.assertRaises(rl.StartError):
                self.cmd(cli="claude", model=bad)

    def test_missing_binary_names_it_and_the_key(self):
        with mock.patch.object(rl, "find_binary", return_value=None):
            with self.assertRaises(rl.StartError) as stop:
                rl.agent_command("daily", {"cli": "codex"})
        self.assertIn("'codex'", str(stop.exception))
        self.assertIn("agent.cli", str(stop.exception))

    def test_prompts_are_constants(self):
        allowed = {p for group in rl.PROMPTS.values() for p in group.values()}
        self.assertEqual(len(allowed), 4)
        for cli in list(rl.AGENT_PRESETS):
            for kind in ("daily", "requested"):
                self.assertIn(self.cmd(kind, cli=cli)[-1], allowed)


class Start(unittest.TestCase):
    def setUp(self):
        ws.write_settings(ws.ROOT, "table")
        rl.LOCK.unlink(missing_ok=True)

    def test_lock_blocks_second_start_and_expires(self):
        self.assertTrue(rl.acquire_lock())
        self.assertFalse(rl.acquire_lock())
        old = time.time() - rl.LOCK_SECONDS - 60
        os.utime(rl.LOCK, (old, old))
        self.assertTrue(rl.acquire_lock())

    def test_start_returns_ok_and_message(self):
        with mock.patch.object(rl, "find_binary", side_effect=found), mock.patch.object(rl, "open_terminal") as window:
            first = rl.start_requested()
            second = rl.start_daily()
        self.assertEqual(first[0], True)
        self.assertIsInstance(first[1], str)
        self.assertEqual(second[0], False)                           # lock: within 30 minutes
        self.assertIn("30 Minuten", second[1])
        window.assert_called_once_with(["/opt/test/bin/claude", "/jobsuche lauf --angefragt"])

    def test_failed_start_releases_lock_and_never_raises(self):
        with mock.patch.object(rl, "find_binary", side_effect=found), \
                mock.patch.object(rl, "open_terminal", side_effect=OSError("no terminal")):
            ok, message = rl.start_daily()
        self.assertFalse(ok)
        self.assertFalse(rl.LOCK.exists())
        with mock.patch.object(rl, "find_binary", return_value=None):
            ok, message = rl.start_daily()
        self.assertFalse(ok)
        self.assertIn("claude", message)

    @unittest.skipIf(os.name == "nt", "POSIX launcher")
    def test_launcher_file(self):
        script, opener = rl._launcher(["/opt/test/bin/claude", "/jobsuche lauf"])
        text = script.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/bin/sh\n"))
        self.assertIn("exec /opt/test/bin/claude '/jobsuche lauf'", text)
        self.assertEqual(oct(script.stat().st_mode & 0o777), "0o700")

    def test_mail_without_local_bridge_does_nothing(self):
        ws.write_settings(ws.ROOT, "table", mail__mode="gmail")
        with mock.patch.object(rl, "_run") as run:
            self.assertEqual(rl.mail(wait=False), 0)
        run.assert_not_called()

    def test_mail_runs_bridge_without_git(self):
        with mock.patch.object(rl, "_run", return_value=(0, '{"new_messages": 0}', "")) as run:
            self.assertEqual(rl.mail(wait=False), 0)
        self.assertEqual(run.call_count, 1)                          # git.sync false: no git command
        cmd = run.call_args[0][0]
        self.assertTrue(cmd[1].endswith("mail_bridge_imap.py") and cmd[2] == "fetch")


class Schedule(unittest.TestCase):
    def setUp(self):
        ws.write_settings(ws.ROOT, "table")

    def test_mac_dry_run(self):
        for job, key in (("daily", "StartCalendarInterval"), ("mail", "StartCalendarInterval"), ("poller", "StartInterval")):
            out = si.apply("install", job, "darwin", dry_run=True)
            plist = plistlib.loads(out["inhalt"].encode("utf-8"))
            self.assertEqual(plist["Label"], f"com.jobsuche.{job}")
            self.assertIn(key, plist)
            self.assertTrue(out["datei"].endswith(f"Library/LaunchAgents/com.jobsuche.{job}.plist"))
            self.assertIn("launchctl bootstrap", out["befehle"][1])
            self.assertEqual(plist["ProgramArguments"][0], str(si.cfg.venv_python()))
        self.assertEqual(plistlib.loads(si.mac_plist("daily").encode())["StartCalendarInterval"], [{"Hour": 7, "Minute": 30}])
        self.assertEqual(len(plistlib.loads(si.mac_plist("mail").encode())["StartCalendarInterval"]), 2)
        self.assertEqual(plistlib.loads(si.mac_plist("poller").encode())["StartInterval"], 120)
        self.assertEqual(plistlib.loads(si.mac_plist("poller", "selftest").encode())["Label"], "com.jobsuche.poller.selftest")

    def test_windows_dry_run(self):
        daily = si.apply("install", "daily", "win32", dry_run=True)["befehle"]
        self.assertEqual(len(daily), 1)
        self.assertIn("/TN Jobsuche-daily", daily[0])
        self.assertIn("/SC DAILY /ST 07:30", daily[0])
        self.assertNotIn("/RU", daily[0])
        self.assertNotIn("/RP", daily[0])
        mail = si.apply("install", "mail", "win32", dry_run=True)["befehle"]
        self.assertEqual([("Jobsuche-mail-1" in mail[0], "08:30" in mail[0]), ("Jobsuche-mail-2" in mail[1], "18:30" in mail[1])],
                         [(True, True), (True, True)])
        poller = si.apply("install", "poller", "win32", dry_run=True)["befehle"][0]
        self.assertIn("/SC MINUTE /MO 2", poller)
        self.assertIn("trigger_poller.py", poller)
        self.assertIn("/Delete /TN Jobsuche-poller /F", si.apply("remove", "poller", "win32", dry_run=True)["befehle"][0])

    def test_linux_prints_cron_lines(self):
        out = si.apply("install", "daily", "linux", dry_run=True)
        self.assertTrue(out["zeilen"][0].startswith("30 7 * * * "))
        self.assertTrue(si.apply("install", "poller", "linux", dry_run=True)["zeilen"][0].startswith("*/2 * * * * "))

    def test_foreign_platform_only_as_dry_run(self):
        other = "win32" if os.name != "nt" else "darwin"
        with self.assertRaises(si.ScheduleError):
            si.apply("install", "poller", other)

    def test_bad_time_is_reported(self):
        ws.write_settings(ws.ROOT, "table", schedule__time="25:99")
        with self.assertRaises(si.ScheduleError):
            si.plan("daily")


if __name__ == "__main__":
    unittest.main()
