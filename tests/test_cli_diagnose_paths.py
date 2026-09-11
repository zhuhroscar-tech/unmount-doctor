"""Regression tests for unmount_doctor.cli.diagnose()/format_report() error
paths and branches that were previously unexercised: fuser/lsof error exit
codes, permission-denied hints, the /proc-then-ps fallback in
_enrich_with_ps, lsof output parsing, and the permission-hint/no-processes
report branches.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unmount_doctor import cli  # noqa: E402
from unmount_doctor.cli import BlockingProcess, DiagnosisResult, diagnose, format_report  # noqa: E402


def _run_side_effect(table):
    """table: dict mapping first-arg-tuple-prefix -> (rc, out, err)."""

    def _run(cmd):
        for prefix, result in table.items():
            if tuple(cmd[: len(prefix)]) == prefix:
                return result
        raise AssertionError(f"unexpected _run call: {cmd}")

    return _run


class EnrichWithPsTests(unittest.TestCase):
    def test_proc_comm_read_failure_falls_back_to_ps(self):
        p = BlockingProcess(pid="424242", access="c")
        with mock.patch("builtins.open", side_effect=OSError("no such file")), \
             mock.patch.object(cli, "_run", return_value=(0, "bash\n", "")) as run_mock:
            cli._enrich_with_ps([p])
        self.assertEqual(p.command, "bash")
        run_mock.assert_called_once_with(["ps", "-p", "424242", "-o", "comm="])

    def test_proc_comm_and_ps_both_fail_leaves_command_empty(self):
        p = BlockingProcess(pid="424242", access="c")
        with mock.patch("builtins.open", side_effect=OSError("no such file")), \
             mock.patch.object(cli, "_run", return_value=(1, "", "no such pid")):
            cli._enrich_with_ps([p])
        self.assertEqual(p.command, "")

    def test_existing_command_not_overwritten(self):
        p = BlockingProcess(pid="1", access="c", command="already-known")
        with mock.patch("builtins.open") as open_mock:
            cli._enrich_with_ps([p])
        open_mock.assert_not_called()
        self.assertEqual(p.command, "already-known")


class DiagnoseErrorPathTests(unittest.TestCase):
    def test_fuser_unexpected_exit_code_recorded_as_error(self):
        table = {
            ("fuser", "-vm"): (2, "", "some unexpected failure"),
            ("fuser", "-m"): (1, "", ""),
        }
        with mock.patch.object(cli, "_which", side_effect=lambda c: c == "fuser"), \
             mock.patch.object(cli, "_run", side_effect=_run_side_effect(table)), \
             mock.patch.object(cli, "_enrich_with_ps"):
            result = diagnose("/tmp")
        self.assertTrue(any("fuser exited with code 2" in e for e in result.errors))

    def test_fuser_permission_denied_sets_hint(self):
        table = {
            ("fuser", "-vm"): (1, "", "Permission denied"),
            ("fuser", "-m"): (1, "", ""),
        }
        with mock.patch.object(cli, "_which", side_effect=lambda c: c == "fuser"), \
             mock.patch.object(cli, "_run", side_effect=_run_side_effect(table)), \
             mock.patch.object(cli, "_enrich_with_ps"):
            result = diagnose("/tmp")
        self.assertTrue(result.permission_hint)

    def test_fuser_verbose_empty_falls_back_to_plain(self):
        table = {
            ("fuser", "-vm"): (0, "", ""),
            ("fuser", "-m"): (0, "/tmp: 4242c\n", ""),
        }
        with mock.patch.object(cli, "_which", side_effect=lambda c: c == "fuser"), \
             mock.patch.object(cli, "_run", side_effect=_run_side_effect(table)), \
             mock.patch.object(cli, "_enrich_with_ps"):
            result = diagnose("/tmp")
        self.assertEqual({p.pid for p in result.processes}, {"4242"})

    def test_fuser_unavailable_records_error(self):
        with mock.patch.object(cli, "_which", return_value=False), \
             mock.patch.object(cli, "_enrich_with_ps"):
            result = diagnose("/tmp")
        self.assertTrue(any("`fuser` not found" in e for e in result.errors))
        self.assertTrue(any("`lsof` not found" in e for e in result.errors))

    def test_lsof_directory_uses_plus_d_and_permission_hint(self):
        lsof_output = (
            "COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\n"
            "bash     5555 alice cwd    DIR  8,1     4096    2 /tmp\n"
        )
        table = {
            ("fuser", "-vm"): (0, "", ""),
            ("fuser", "-m"): (0, "", ""),
            ("lsof", "+D"): (0, lsof_output, "Permission denied"),
        }
        with mock.patch.object(cli, "_which", return_value=True), \
             mock.patch("os.path.isdir", return_value=True), \
             mock.patch.object(cli, "_run", side_effect=_run_side_effect(table)), \
             mock.patch.object(cli, "_enrich_with_ps"):
            result = diagnose("/tmp")
        self.assertTrue(result.permission_hint)
        self.assertIn("5555", {p.pid for p in result.processes})

    def test_lsof_non_directory_target_uses_plain_lsof(self):
        lsof_output = (
            "COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\n"
            "bash     6666 alice   3r   REG  8,1     4096    2 /dev/sdb1\n"
        )
        table = {
            ("fuser", "-vm"): (0, "", ""),
            ("fuser", "-m"): (0, "", ""),
            ("lsof", "--"): (0, lsof_output, ""),
        }
        with mock.patch.object(cli, "_which", return_value=True), \
             mock.patch("os.path.isdir", return_value=False), \
             mock.patch.object(cli, "_run", side_effect=_run_side_effect(table)), \
             mock.patch.object(cli, "_enrich_with_ps"):
            result = diagnose("/dev/sdb1")
        self.assertIn("6666", {p.pid for p in result.processes})


class FormatReportBranchTests(unittest.TestCase):
    def test_no_processes_with_permission_hint(self):
        result = DiagnosisResult(target="/mnt/x", fuser_available=True, lsof_available=True, permission_hint=True)
        report = format_report(result)
        self.assertIn("WITHOUT root privileges", report)
        self.assertIn("sudo unmount-doctor /mnt/x", report)

    def test_errors_section_rendered(self):
        result = DiagnosisResult(target="/mnt/x", fuser_available=True, lsof_available=True)
        result.errors.append("something odd happened")
        report = format_report(result)
        self.assertIn("Notes:", report)
        self.assertIn("something odd happened", report)


if __name__ == "__main__":
    unittest.main()
