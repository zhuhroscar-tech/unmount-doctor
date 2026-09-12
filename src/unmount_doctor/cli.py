"""
unmount-doctor
==============

A small, read-only-by-default diagnostic CLI that explains *why* a Linux
mount point (or any path/device) is reported "busy" / "target is busy" when
you try to `umount` it, and offers safe, explicit next steps.

It does not invent information: it shells out to the standard `fuser` and
`lsof` utilities (already present on virtually every Linux distro) and
translates their raw, terse output into a human-readable report, matching
each blocking process to *why* it is blocking (open file, current working
directory, executable text, memory map, etc).

By default this tool is 100% read-only: it never kills a process or
unmounts anything unless you pass --kill or --lazy-unmount AND confirm
interactively (or pass --yes for non-interactive use, e.g. scripts you
already trust).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

from .style import Style, resolve_style, status_headline

# fuser's ACCESS column, per fuser(1). Not all letters are used on every
# platform build, but this covers the common Linux util-linux/psmisc set.
ACCESS_MEANINGS = {
    "c": "has this as its current working directory",
    "e": "is executing a program stored here",
    "f": "has an open file here (lowercase = read-only)",
    "F": "has an open file here for writing",
    "r": "has this as its root directory (chroot)",
    "m": "has this memory-mapped (e.g. a shared library)",
    ".": "(no meaning for this position)",
}


@dataclass
class BlockingProcess:
    pid: str
    access: str
    command: str = ""
    user: str = ""

    def access_explanations(self):
        return [ACCESS_MEANINGS[ch] for ch in self.access if ch in ACCESS_MEANINGS and ch != "."]


@dataclass
class DiagnosisResult:
    target: str
    fuser_available: bool = False
    lsof_available: bool = False
    fuser_raw: str = ""
    lsof_raw: str = ""
    processes: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    permission_hint: bool = False
    tool_error: bool = False


def _which(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _run(cmd: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{cmd[0]}: timed out"


def _parse_fuser_verbose(output: str) -> list[BlockingProcess]:
    """Parse `fuser -v` output.

    Typical format:
                         USER        PID ACCESS COMMAND
        /mnt/data:       root       1234 ..c.. bash
                         alice      5678 f....  tail
    """
    procs: list[BlockingProcess] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.upper().startswith("USER"):
            continue
        # A path/mountpoint header line looks like "/mnt/data:  root  1234 ..c.. bash"
        # (fuser prefixes the first matching line with "<path>:"). Strip that
        # prefix off before parsing the USER/PID/ACCESS/COMMAND columns.
        if ":" in stripped:
            prefix, sep, remainder = stripped.partition(":")
            if remainder.strip():
                stripped = remainder.strip()
            elif not sep or not remainder.strip():
                # header line with nothing after the colon on its own line
                if stripped.endswith(":"):
                    continue
        parts = stripped.split(None, 3)
        # Expect: USER PID ACCESS COMMAND (COMMAND may contain spaces, but
        # argparse-like split(None, 3) keeps the remainder intact)
        if len(parts) >= 3 and parts[1].isdigit():
            user, pid, access = parts[0], parts[1], parts[2]
            command = parts[3] if len(parts) > 3 else ""
            procs.append(BlockingProcess(pid=pid, access=access, command=command, user=user))
    return procs


def _parse_fuser_plain(output: str) -> list[BlockingProcess]:
    """Parse plain `fuser -m <path>` output: '<path>: 123c 456 789e'."""
    procs: list[BlockingProcess] = []
    for line in output.splitlines():
        if ":" not in line:
            continue
        _, _, rest = line.partition(":")
        for token in rest.split():
            access = ""
            digits = token
            while digits and not digits[-1].isdigit():
                access = digits[-1] + access
                digits = digits[:-1]
            if digits.isdigit():
                procs.append(BlockingProcess(pid=digits, access=access))
    return procs


def _enrich_with_ps(procs: list[BlockingProcess]) -> None:
    """Fill in command names via /proc/<pid>/comm when fuser -v wasn't used."""
    for p in procs:
        if p.command:
            continue
        comm_path = f"/proc/{p.pid}/comm"
        try:
            with open(comm_path, "r", encoding="utf-8", errors="replace") as fh:
                p.command = fh.read().strip()
        except OSError:
            rc, out, _ = _run(["ps", "-p", p.pid, "-o", "comm="])
            if rc == 0 and out.strip():
                p.command = out.strip()


def diagnose(target: str) -> DiagnosisResult:
    result = DiagnosisResult(target=target)
    result.fuser_available = _which("fuser")
    result.lsof_available = _which("lsof")

    if not os.path.exists(target):
        result.errors.append(f"Path does not exist: {target}")

    procs_by_pid: dict[str, BlockingProcess] = {}

    if result.fuser_available:
        rc, out, err = _run(["fuser", "-vm", target])
        result.fuser_raw = out + err
        if rc not in (0, 1):
            result.errors.append(f"fuser exited with code {rc}: {err.strip()}")
            result.tool_error = True
        if "Permission denied" in err or "you must be root" in err.lower():
            result.permission_hint = True
        parsed = _parse_fuser_verbose(out) or _parse_fuser_verbose(err)
        if not parsed:
            rc2, out2, err2 = _run(["fuser", "-m", target])
            parsed = _parse_fuser_plain(out2 + err2)
        for p in parsed:
            procs_by_pid[p.pid] = p
    else:
        result.errors.append("`fuser` not found (install psmisc / util-linux).")

    if result.lsof_available:
        # `lsof +f` (file-system mode) only works when `target` is *exactly*
        # a mount point; for any other directory it refuses with
        # "not a file system" and produces nothing useful (see lsof(8) FAQ
        # 3.21.3), even though --help explicitly documents this tool as
        # accepting "Mount point, directory, or device path". For a
        # directory we instead recurse with `lsof +D`, which lists every
        # open file under it (mount point or plain directory alike). For a
        # device node or regular file we use plain `lsof TARGET`, which
        # lsof already matches by device/inode without needing +f.
        if os.path.isdir(target):
            rc, out, err = _run(["lsof", "+D", target])
        else:
            rc, out, err = _run(["lsof", "--", target])
        result.lsof_raw = out + err
        if "Permission denied" in err:
            result.permission_hint = True
        for line in out.splitlines()[1:]:
            cols = line.split(None, 8)
            if len(cols) >= 2 and cols[1].isdigit():
                pid = cols[1]
                cmd = cols[0]
                if pid not in procs_by_pid:
                    procs_by_pid[pid] = BlockingProcess(pid=pid, access="f", command=cmd)
                elif not procs_by_pid[pid].command:
                    procs_by_pid[pid].command = cmd
    else:
        result.errors.append("`lsof` not found (optional, but improves detail).")

    _enrich_with_ps(list(procs_by_pid.values()))
    result.processes = sorted(procs_by_pid.values(), key=lambda p: p.pid)
    return result


def format_report(result: DiagnosisResult, style: Style | None = None) -> str:
    style = style if style is not None else Style(False)
    lines = []
    lines.append(f"unmount-doctor report for: {style.bold(result.target)}")

    if not result.fuser_available and not result.lsof_available:
        lines.append("")
        lines.append(status_headline(style, "fail", "Neither `fuser` nor `lsof` is installed -- cannot diagnose."))
        lines.append("Install with e.g.: sudo apt install psmisc lsof")
        return "\n".join(lines)

    if not result.processes:
        lines.append("")
        if result.permission_hint:
            lines.append(status_headline(
                style, "warn",
                "No blocking processes found WITHOUT root privileges, but some "
                "processes may be hidden.",
            ))
            lines.append(f"Re-run with sudo for a complete picture:  sudo unmount-doctor {result.target}")
        elif result.tool_error:
            lines.append(status_headline(
                style, "warn",
                "No blocking processes found, but a diagnostic tool failed -- "
                "this result may be incomplete, not a confirmed all-clear.",
            ))
            lines.append("See Notes below for the tool error; consider re-running or checking manually.")
        else:
            lines.append(status_headline(style, "ok", "No process appears to be holding this path open."))
            lines.append(
                "If `umount` still reports busy, check for:\n"
                "  - a filesystem mounted *inside* this one (nested mount)\n"
                "  - active swap on this device\n"
                "  - a loop device backed by a file here\n"
                "Try: findmnt -R " + result.target
            )
    else:
        lines.append("")
        lines.append(status_headline(
            style, "warn", f"{len(result.processes)} process(es) are keeping this busy"
        ))
        for p in result.processes:
            who = f"PID {p.pid}"
            if p.user:
                who += f" (user {p.user})"
            cmd = p.command or "(unknown command)"
            lines.append(f"\n  {style.bold(who)} -- {cmd}")
            reasons = p.access_explanations() or ["has an open reference here"]
            for reason in reasons:
                lines.append(f"    {style.dim('->')} {reason}")
        lines.append("")
        lines.append(style.dim("Safe next steps:"))
        lines.append("  1. If a listed process is a shell with its cwd here, `cd` elsewhere.")
        lines.append("  2. If it's an app (editor, file manager, media player), close it normally.")
        lines.append(
            "  3. Only if you understand the risk, ask this tool to signal a process:\n"
            "       unmount-doctor " + result.target + " --kill PID"
        )
        lines.append(
            "  4. As a last resort, a lazy unmount detaches now and finishes once handles close:\n"
            "       unmount-doctor " + result.target + " --lazy-unmount"
        )

    if result.errors:
        lines.append("")
        lines.append(style.dim("Notes:"))
        for e in result.errors:
            lines.append(f"  - {e}")

    return "\n".join(lines)


def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        reply = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return reply in ("y", "yes")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="unmount-doctor",
        description=(
            "Explain which process is holding a mount point/path busy and why, "
            "so 'umount: target is busy' stops being a guessing game."
        ),
    )
    parser.add_argument("target", help="Mount point, directory, or device path to inspect")
    parser.add_argument(
        "--kill",
        metavar="PID",
        help="Send SIGTERM to this PID after confirmation (must be one reported above)",
    )
    parser.add_argument(
        "--force-kill",
        metavar="PID",
        help="Send SIGKILL to this PID after confirmation (last resort; may lose data)",
    )
    parser.add_argument(
        "--lazy-unmount",
        action="store_true",
        help="Run `umount -l TARGET` after confirmation (detaches now, finishes once idle)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Do not prompt for confirmation on --kill/--force-kill/--lazy-unmount (scripting use)",
    )
    parser.add_argument("--no-color", action="store_true", help="Disable colored output.")
    parser.add_argument("--version", action="version", version=f"unmount-doctor {__import__('unmount_doctor').__version__}")

    args = parser.parse_args(argv)

    if sys.platform != "linux":
        print(
            "unmount-doctor relies on Linux-specific tools (fuser, lsof, /proc) "
            "and mount semantics; it is not expected to work correctly on this "
            f"platform ({sys.platform}).",
            file=sys.stderr,
        )

    style = resolve_style(no_color_flag=args.no_color)
    result = diagnose(args.target)
    print(format_report(result, style=style))

    exit_code = 0

    if args.kill or args.force_kill:
        pid = args.kill or args.force_kill
        sig_name = "SIGTERM" if args.kill else "SIGKILL"
        known_pids = {p.pid for p in result.processes}
        if pid not in known_pids:
            print(f"\nRefusing: PID {pid} was not among the processes reported above.", file=sys.stderr)
            return 2
        if _confirm(f"\nSend {sig_name} to PID {pid}?", args.yes):
            rc, _, err = _run(["kill", "-TERM" if args.kill else "-KILL", pid])
            if rc != 0:
                print(f"kill failed: {err.strip()}", file=sys.stderr)
                exit_code = 1
            else:
                print(f"Sent {sig_name} to PID {pid}.")
        else:
            print("Aborted, no signal sent.")

    if args.lazy_unmount:
        if _confirm(f"\nRun `umount -l {args.target}` now?", args.yes):
            rc, out, err = _run(["umount", "-l", args.target])
            if rc != 0:
                print(f"umount -l failed: {err.strip()}", file=sys.stderr)
                exit_code = 1
            else:
                print(f"Lazily unmounted {args.target}.")
        else:
            print("Aborted, filesystem left mounted.")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
