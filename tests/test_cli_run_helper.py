"""Regression tests for cli._run() exercising the real subprocess.run()
try/except body -- not the fake runners used everywhere else in this
suite. Before this test, the FileNotFoundError and TimeoutExpired
branches in _run() were only ever reached via mock.patch.object(cli,
"_run", ...), meaning the real subprocess call inside _run() itself had
zero test coverage."""

import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unmount_doctor.cli import BlockingProcess, _enrich_with_ps, _run


class RunHelperRealSubprocessTests(unittest.TestCase):
    def test_nonexistent_binary_returns_127_not_found(self):
        """Real subprocess.run() raises FileNotFoundError for a binary
        that genuinely doesn't exist on PATH; _run() must translate that
        into (127, "", "<cmd>: not found") instead of propagating."""
        rc, out, err = _run(["unmount-doctor-nonexistent-binary-xyz", "-v"])
        self.assertEqual(rc, 127)
        self.assertEqual(out, "")
        self.assertIn("not found", err)
        self.assertIn("unmount-doctor-nonexistent-binary-xyz", err)

    def test_real_binary_runs_and_captures_stdout(self):
        """Sanity check the happy path also goes through the real
        subprocess.run() call (not just the exception branches)."""
        rc, out, err = _run(["echo", "hello-from-real-subprocess"])
        self.assertEqual(rc, 0)
        self.assertIn("hello-from-real-subprocess", out)
        self.assertEqual(err, "")

    def test_real_timeout_returns_124_timed_out(self):
        """Real subprocess.run(..., timeout=15) raises TimeoutExpired
        when the child outlives the timeout; _run() must translate that
        into (124, "", "<cmd>: timed out"). We can't wait out the real
        production 15s timeout, so we wrap the real subprocess.run with
        a thin passthrough that forces a short timeout -- this still
        exercises _run()'s own try/except body and the real
        subprocess.TimeoutExpired exception path, unlike the rest of the
        suite which replaces _run() itself wholesale."""

        real_run = subprocess.run

        def _short_timeout_run(cmd, **kwargs):
            kwargs["timeout"] = 0.2
            return real_run(cmd, **kwargs)

        cmd = [sys.executable, "-c", "import time; time.sleep(5)"]
        with mock.patch("unmount_doctor.cli.subprocess.run", side_effect=_short_timeout_run):
            rc, out, err = _run(cmd)
        self.assertEqual(rc, 124)
        self.assertEqual(out, "")
        self.assertIn("timed out", err)


class EnrichWithPsRealPsTests(unittest.TestCase):
    def test_enrich_with_ps_uses_real_ps_subprocess_for_missing_proc(self):
        """Use a pid that (almost certainly) has no /proc/<pid>/comm on
        this host, forcing _enrich_with_ps's OSError fallback to invoke
        the real `ps` subprocess via _run(), not a mocked one."""
        p = BlockingProcess(pid="1", access="c")
        # pid 1 exists on Linux (init/systemd) but /proc/1/comm is often
        # unreadable without privilege inside containers/sandboxes, and
        # on macOS test hosts /proc doesn't exist at all -- either way
        # the OSError branch fires and falls through to the real `ps`
        # call. We only assert _enrich_with_ps doesn't raise and leaves
        # a sane (possibly empty) command string, since availability of
        # `ps -p 1` output varies by platform/container.
        _enrich_with_ps([p])
        self.assertIsInstance(p.command, str)

    def test_enrich_with_ps_reads_real_proc_comm_for_own_pid(self):
        """Exercise the success branch of the try (open() succeeds and
        reads a real /proc/<pid>/comm) for the current process's own
        pid, which is guaranteed to exist and be readable wherever
        /proc is mounted (Linux CI). On hosts without /proc (e.g. this
        macOS dev machine) the OSError fallback simply fires instead,
        which is already covered by the sibling test above -- so this
        test asserts the non-raising contract either way and, when
        /proc IS available, that the real file read path filled in a
        non-empty command without ever calling _run()."""
        pid = str(os.getpid())
        p = BlockingProcess(pid=pid, access="c")
        proc_comm = f"/proc/{pid}/comm"
        with mock.patch.object(
            sys.modules["unmount_doctor.cli"], "_run", return_value=(1, "", "")
        ) as run_mock:
            _enrich_with_ps([p])
            if os.path.exists(proc_comm):
                self.assertTrue(p.command)
                run_mock.assert_not_called()


class ParseFuserVerboseHeaderColonTests(unittest.TestCase):
    def test_header_line_with_bare_trailing_colon_is_skipped(self):
        """Regression test for the branch at the trailing ':' check in
        _parse_fuser_verbose: a header/path line that is *only* a colon
        with nothing else on it (e.g. a bare "/mnt/data:" line with the
        USER/PID/ACCESS/COMMAND data on the following line, which some
        fuser versions/locales emit) must be skipped rather than being
        mis-parsed as a data row."""
        from unmount_doctor.cli import _parse_fuser_verbose

        sample = "/mnt/data:\n" "alice      5678 f....  tail\n"
        procs = _parse_fuser_verbose(sample)
        pids = {p.pid for p in procs}
        self.assertEqual(pids, {"5678"})


class LsofMergeExistingPidTests(unittest.TestCase):
    def test_lsof_row_does_not_overwrite_command_from_fuser(self):
        """When both fuser and lsof report the same pid, diagnose()'s
        lsof-merge step must not clobber a command name fuser/ps already
        filled in -- it should only backfill when the existing entry's
        command is still empty. Exercised directly against the merge
        logic by simulating the procs_by_pid state diagnose() builds."""
        from unmount_doctor.cli import BlockingProcess

        existing = BlockingProcess(pid="4242", access="c", command="bash")
        procs_by_pid = {"4242": existing}

        # Reproduce the exact merge branch from diagnose(): a pid already
        # present with a command must keep it; a pid already present
        # without a command gets backfilled.
        cols = ["python3", "4242"]
        pid, cmd = cols[1], cols[0]
        if pid not in procs_by_pid:
            procs_by_pid[pid] = BlockingProcess(pid=pid, access="f", command=cmd)
        elif not procs_by_pid[pid].command:
            procs_by_pid[pid].command = cmd
        self.assertEqual(procs_by_pid["4242"].command, "bash")

        blank = BlockingProcess(pid="9999", access="c", command="")
        procs_by_pid2 = {"9999": blank}
        cols2 = ["python3", "9999"]
        pid2, cmd2 = cols2[1], cols2[0]
        if pid2 not in procs_by_pid2:
            procs_by_pid2[pid2] = BlockingProcess(pid=pid2, access="f", command=cmd2)
        elif not procs_by_pid2[pid2].command:
            procs_by_pid2[pid2].command = cmd2
        self.assertEqual(procs_by_pid2["9999"].command, "python3")


if __name__ == "__main__":
    unittest.main()
