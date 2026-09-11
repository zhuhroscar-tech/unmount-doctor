"""Regression tests for unmount_doctor.cli.main().

Before this file, main() (argument parsing, --kill/--force-kill/
--lazy-unmount confirmation flows, PID validation, --version, and the
non-Linux warning) was entirely untested -- 76 of cli.py's 212 statements
(63% coverage). This is real, risk-carrying code: it is the path that
actually sends signals to processes and unmounts filesystems, so it is
exactly the kind of "risky code path" the audit is meant to catch.

All subprocess/interactive calls are monkeypatched; nothing here actually
signals a process or unmounts anything.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unmount_doctor import cli  # noqa: E402
from unmount_doctor.cli import BlockingProcess, DiagnosisResult, main  # noqa: E402


def _fake_diagnose_with_pid(pid="1234"):
    def _diagnose(target):
        result = DiagnosisResult(target=target, fuser_available=True, lsof_available=True)
        result.processes = [BlockingProcess(pid=pid, access="c", command="bash", user="alice")]
        return result

    return _diagnose


class ConfirmTests(unittest.TestCase):
    def test_confirm_assume_yes_skips_prompt(self):
        self.assertTrue(cli._confirm("Do it?", assume_yes=True))

    def test_confirm_yes_input(self):
        with mock.patch("builtins.input", return_value="y"):
            self.assertTrue(cli._confirm("Do it?", assume_yes=False))

    def test_confirm_no_input(self):
        with mock.patch("builtins.input", return_value="n"):
            self.assertFalse(cli._confirm("Do it?", assume_yes=False))

    def test_confirm_eof_treated_as_no(self):
        with mock.patch("builtins.input", side_effect=EOFError):
            self.assertFalse(cli._confirm("Do it?", assume_yes=False))


class MainVersionAndPlainReportTests(unittest.TestCase):
    def test_version_flag_exits_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                main(["/tmp/x", "--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("unmount-doctor", buf.getvalue())

    def test_plain_run_no_flags_returns_zero(self):
        with mock.patch.object(cli, "diagnose", side_effect=lambda t: DiagnosisResult(target=t)):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["/tmp/somewhere", "--no-color"])
        self.assertEqual(rc, 0)
        self.assertIn("/tmp/somewhere", buf.getvalue())

    def test_non_linux_prints_warning_to_stderr(self):
        with mock.patch.object(cli, "diagnose", side_effect=lambda t: DiagnosisResult(target=t)):
            with mock.patch.object(cli.sys, "platform", "darwin"):
                err = io.StringIO()
                with redirect_stderr(err), redirect_stdout(io.StringIO()):
                    main(["/tmp/x"])
        self.assertIn("not expected to work correctly", err.getvalue())


class MainKillFlowTests(unittest.TestCase):
    def test_kill_refuses_unknown_pid(self):
        with mock.patch.object(cli, "diagnose", side_effect=_fake_diagnose_with_pid("1234")):
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                rc = main(["/tmp/x", "--kill", "9999", "--yes"])
        self.assertEqual(rc, 2)
        self.assertIn("Refusing", err.getvalue())

    def test_kill_known_pid_confirmed_success(self):
        with mock.patch.object(cli, "diagnose", side_effect=_fake_diagnose_with_pid("1234")), \
             mock.patch.object(cli, "_run", return_value=(0, "", "")) as run_mock:
            out = io.StringIO()
            with redirect_stdout(out):
                rc = main(["/tmp/x", "--kill", "1234", "--yes"])
        self.assertEqual(rc, 0)
        self.assertIn("Sent SIGTERM", out.getvalue())
        run_mock.assert_called_once_with(["kill", "-TERM", "1234"])

    def test_force_kill_known_pid_confirmed_success(self):
        with mock.patch.object(cli, "diagnose", side_effect=_fake_diagnose_with_pid("1234")), \
             mock.patch.object(cli, "_run", return_value=(0, "", "")) as run_mock:
            out = io.StringIO()
            with redirect_stdout(out):
                rc = main(["/tmp/x", "--force-kill", "1234", "--yes"])
        self.assertEqual(rc, 0)
        self.assertIn("Sent SIGKILL", out.getvalue())
        run_mock.assert_called_once_with(["kill", "-KILL", "1234"])

    def test_kill_confirmed_but_underlying_kill_fails(self):
        with mock.patch.object(cli, "diagnose", side_effect=_fake_diagnose_with_pid("1234")), \
             mock.patch.object(cli, "_run", return_value=(1, "", "no such process")):
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                rc = main(["/tmp/x", "--kill", "1234", "--yes"])
        self.assertEqual(rc, 1)
        self.assertIn("kill failed", err.getvalue())

    def test_kill_aborted_when_user_declines(self):
        with mock.patch.object(cli, "diagnose", side_effect=_fake_diagnose_with_pid("1234")), \
             mock.patch("builtins.input", return_value="n"), \
             mock.patch.object(cli, "_run") as run_mock:
            out = io.StringIO()
            with redirect_stdout(out):
                rc = main(["/tmp/x", "--kill", "1234"])
        self.assertEqual(rc, 0)
        self.assertIn("Aborted, no signal sent.", out.getvalue())
        run_mock.assert_not_called()


class MainLazyUnmountFlowTests(unittest.TestCase):
    def test_lazy_unmount_confirmed_success(self):
        with mock.patch.object(cli, "diagnose", side_effect=lambda t: DiagnosisResult(target=t)), \
             mock.patch.object(cli, "_run", return_value=(0, "", "")) as run_mock:
            out = io.StringIO()
            with redirect_stdout(out):
                rc = main(["/mnt/x", "--lazy-unmount", "--yes"])
        self.assertEqual(rc, 0)
        self.assertIn("Lazily unmounted", out.getvalue())
        run_mock.assert_called_once_with(["umount", "-l", "/mnt/x"])

    def test_lazy_unmount_confirmed_but_fails(self):
        with mock.patch.object(cli, "diagnose", side_effect=lambda t: DiagnosisResult(target=t)), \
             mock.patch.object(cli, "_run", return_value=(1, "", "target is busy")):
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                rc = main(["/mnt/x", "--lazy-unmount", "--yes"])
        self.assertEqual(rc, 1)
        self.assertIn("umount -l failed", err.getvalue())

    def test_lazy_unmount_aborted_when_user_declines(self):
        with mock.patch.object(cli, "diagnose", side_effect=lambda t: DiagnosisResult(target=t)), \
             mock.patch("builtins.input", return_value="n"), \
             mock.patch.object(cli, "_run") as run_mock:
            out = io.StringIO()
            with redirect_stdout(out):
                rc = main(["/mnt/x", "--lazy-unmount"])
        self.assertEqual(rc, 0)
        self.assertIn("Aborted, filesystem left mounted.", out.getvalue())
        run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
