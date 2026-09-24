[![English](https://img.shields.io/badge/English-555555?style=flat)](README.md) [![简体中文](https://img.shields.io/badge/简体中文-555555?style=flat)](README.zh-CN.md)

# unmount-doctor

Explain Linux's `umount: target is busy` error with a process-by-process report. `unmount-doctor` translates `fuser`/`lsof` output into the PID, user where available, command, and reason a path is in use: an open file, current directory, executable, memory map, or another reference.

It is **read-only by default**. Optional process-signalling and lazy-unmount actions require explicit flags and confirmation.

## Install and inspect

Requires Linux and Python 3.8+. Install `fuser` (usually the `psmisc` package); optional `lsof` adds detail. On Debian/Ubuntu:

```bash
sudo apt-get install psmisc lsof
git clone https://github.com/zhuhroscar-tech/unmount-doctor.git
cd unmount-doctor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
unmount-doctor /mnt/usb
```

The target can be a mount point, directory, or device path. Run `unmount-doctor --help` for all flags. Standalone `.pyz` downloads are on [Releases](https://github.com/zhuhroscar-tech/unmount-doctor/releases); verify the matching release checksums before execution. See [CHANGELOG.md](CHANGELOG.md) for release history.

## Resolve carefully

Start by closing the listed application normally. If a shell is using the mount as its working directory, `cd` elsewhere. Inspect again before attempting a normal unmount.

Only when you understand the consequences, these optional commands perform changes:

```bash
unmount-doctor /mnt/usb --kill 4213       # SIGTERM; asks for confirmation
unmount-doctor /mnt/usb --force-kill 4213 # SIGKILL; may lose unsaved data
unmount-doctor /mnt/usb --lazy-unmount   # runs umount -l after confirmation
```

Replace the example PID with one in the current report. Unknown PIDs are refused. `--yes` bypasses confirmation; avoid it for interactive troubleshooting. Lazy unmount detaches the filesystem namespace immediately but does not mean all references are closed or a drive is safe to unplug.

## Limits and permissions

An empty report is not proof that a filesystem is idle. Other users' processes may be hidden without root privileges; tool errors can also leave incomplete evidence. Check nested mounts, swap, and loop devices if unmount still fails. Directory inspection through `lsof +D` can be expensive.

The CLI is Linux-specific, has no telemetry or network calls, and uses your existing privileges. Diagnostic-only invocations can return `0` even with blockers or tool errors: read the report rather than using that exit code as a health signal.

## Preview and development

[Example output](docs/images/example-output.png) · [Demo video](docs/demo.mp4)

```bash
python -m unittest discover -s tests -v
```

[Implementation](src/unmount_doctor/cli.py) · [CI](.github/workflows/ci.yml) · [MIT license](LICENSE)
