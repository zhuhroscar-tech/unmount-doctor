# unmount-doctor

[![CI](https://github.com/zhuhroscar-tech/unmount-doctor/actions/workflows/ci.yml/badge.svg)](https://github.com/zhuhroscar-tech/unmount-doctor/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/zhuhroscar-tech/unmount-doctor?include_prereleases&label=release)](https://github.com/zhuhroscar-tech/unmount-doctor/releases)
![Linux](https://img.shields.io/badge/platform-Linux-111111?logo=linux)

A small, read-only-by-default CLI that explains **why** Linux says
`umount: /mnt/x: target is busy` (or `device is busy`) instead of making you
guess. It wraps the standard `fuser`/`lsof` utilities and turns their terse
output into a human-readable report: which process, which user, and *why*
it's blocking (open file, current directory, running executable, memory
map, ...), plus safe next steps.

## Simple explanation

When Linux refuses to eject or unmount a drive because it says the drive is
"busy", this tool tells you in plain English exactly which program is using
it and why, instead of leaving you to guess or force-kill things blindly.
It never changes anything unless you explicitly ask it to.

## Why this exists

"Target is busy" on `umount` is one of the most repeated Linux pain points
across forums in every language — English, Chinese, and Japanese threads all
show the same pattern: `fuser -vm` / `lsof` output is correct but cryptic,
so people default to blindly force-killing things or using `umount -l`
without understanding what they're detaching. See for example:

- r/linuxquestions: "Attempting to unmount a USB drive and getting a busy error"
  https://www.reddit.com/r/linuxquestions/comments/1nuat2c/
- r/linuxquestions: "Target is busy when unmounting"
  https://www.reddit.com/r/linuxquestions/comments/r5o326/
- Unix & Linux Stack Exchange, "Busy Device on Umount" (62 upvotes, still
  actively referenced): https://unix.stackexchange.com/questions/107885
- General guides confirming `fuser -vm` / `lsof +f` are the standard but
  low-level answer that most users don't run correctly on the first try:
  https://thelinuxcode.com/umount-target-busy

Existing solutions (`fuser`, `lsof`, `udiskie`) already exist and are not
being replaced — `unmount-doctor` is a thin, honest translation layer on
top of them for people who don't want to memorize the ACCESS column
(`c`/`e`/`f`/`F`/`r`/`m`) every time. It changes nothing by default; killing
a process or lazy-unmounting requires an explicit flag and confirmation.

## Install

Requires Python 3.8+ and a Linux system with `fuser` (psmisc) and,
optionally, `lsof`. Both ship by default or via one package on virtually
every distro:

```bash
# Debian/Ubuntu
sudo apt-get install -y psmisc lsof
# Fedora/RHEL
sudo dnf install -y psmisc lsof
# Arch
sudo pacman -S --needed psmisc lsof
```

### Option A — download the standalone artifact (no pip needed)

Grab `unmount-doctor.pyz` from the
[Releases page](https://github.com/zhuhroscar-tech/unmount-doctor/releases),
verify the checksum, and run it directly with any Python 3.8+:

```bash
curl -LO https://github.com/zhuhroscar-tech/unmount-doctor/releases/latest/download/unmount-doctor.pyz
curl -LO https://github.com/zhuhroscar-tech/unmount-doctor/releases/latest/download/SHA256SUMS.txt
sha256sum -c SHA256SUMS.txt --ignore-missing
chmod +x unmount-doctor.pyz
./unmount-doctor.pyz /mnt/usb
```

### Option B — pip / pipx from the release wheel

```bash
pip install --user https://github.com/zhuhroscar-tech/unmount-doctor/releases/latest/download/unmount_doctor-0.1.0-py3-none-any.whl
unmount-doctor /mnt/usb
```

### Option C — from source

```bash
git clone https://github.com/zhuhroscar-tech/unmount-doctor.git
cd unmount-doctor
pip install -e .
unmount-doctor /mnt/usb
```

## Usage

```bash
$ unmount-doctor /mnt/usb
unmount-doctor report for: /mnt/usb
------------------------------------------------------------
2 process(es) are keeping this busy:

  * PID 4213 (user oscar) — bash
      -> has this as its current working directory
  * PID 4310 (user oscar) — tail
      -> has an open file here for writing

Safe next steps:
  1. If a listed process is a shell with its cwd here, `cd` elsewhere.
  2. If it's an app (editor, file manager, media player), close it normally.
  3. Only if you understand the risk, ask this tool to signal a process:
       unmount-doctor /mnt/usb --kill PID
  4. As a last resort, a lazy unmount detaches now and finishes once handles close:
       unmount-doctor /mnt/usb --lazy-unmount
```

Optional actions (never run without an explicit flag + confirmation):

```bash
unmount-doctor /mnt/usb --kill 4213           # SIGTERM, asks y/N first
unmount-doctor /mnt/usb --force-kill 4213     # SIGKILL, asks y/N first
unmount-doctor /mnt/usb --lazy-unmount        # runs `umount -l`, asks y/N first
unmount-doctor /mnt/usb --kill 4213 --yes     # non-interactive (scripts you trust)
```

Some processes owned by other users are only visible to `fuser`/`lsof` when
run as root; if the report is empty but `umount` still fails, re-run with
`sudo unmount-doctor /mnt/usb`.

## Privacy / permissions

- No network access, no telemetry, no files written outside of what you
  explicitly request with `--kill`/`--force-kill`/`--lazy-unmount`.
- Runs entirely with your existing user privileges; only shows you what
  `fuser`/`lsof` would already show, translated.
- No secrets, no background services, no sudo required unless *you* choose
  to run it as root to see other users' processes.

## Supported platforms

Linux only (relies on `/proc`, `fuser`, `lsof`, and `umount -l` semantics
that don't exist on macOS/BSD in the same form). Tested on Ubuntu (GitHub
Actions `ubuntu-latest` runner) with Python 3.9 and 3.12. Architecture:
pure Python, no compiled extensions — runs on x86_64, arm64, or anything
with a Python 3.8+ interpreter.

## Uninstall

```bash
pip uninstall unmount-doctor        # if installed via pip
rm unmount-doctor.pyz               # if using the standalone artifact
```

No config files, caches, or system changes are made, so there is nothing
else to clean up.

## Development / reproducing the build and tests

```bash
git clone https://github.com/zhuhroscar-tech/unmount-doctor.git
cd unmount-doctor
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -v

# Build the same artifacts CI publishes:
pip install build
python -m build
mkdir -p dist_bundle/unmount_doctor
cp -r src/unmount_doctor/* dist_bundle/unmount_doctor/
printf 'from unmount_doctor.cli import main\nif __name__ == "__main__":\n    raise SystemExit(main())\n' > dist_bundle/__main__.py
python -m zipapp dist_bundle -o dist/unmount-doctor.pyz -p "/usr/bin/env python3"
sha256sum dist/*.whl dist/*.tar.gz dist/unmount-doctor.pyz > dist/SHA256SUMS.txt
```

CI (`.github/workflows/ci.yml`) runs the exact same steps on
`ubuntu-latest` for every push/PR, and attaches the wheel, sdist, zipapp,
and checksums to GitHub Releases automatically on publish.

## License

MIT — see [LICENSE](LICENSE).
