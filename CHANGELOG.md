# Changelog

## v0.1.8 — 2026-09-25

- Made release-tag CI explicit for `v*` tags so source-quality releases rerun the full validation path when tags are pushed.
- Added repository-contract coverage for tag-triggered release validation.

## v0.1.7 — 2026-09-24

- Added release-history documentation for the latest packaging metadata maintenance release.
- Added repository-contract coverage for required project files, README release links, CI, CodeQL, and release artifacts.

## v0.1.6 — 2026-09-23

- Modernized packaging license metadata to current SPDX form.
- Added regression tests covering license metadata and the setuptools minimum needed for `license-files`.
- Published wheel, sdist, standalone `unmount-doctor.pyz`, and checksums.

## v0.1.5 — 2026-09-20

- Fixed `fuser -m` fallback handling so failed probes are inspected instead of producing a silent false all-clear.

## v0.1.4 — 2026-09-18

- Fixed noisy `lsof` scan failures so timeouts and directory-scan errors are reported rather than treated as a clean result.
