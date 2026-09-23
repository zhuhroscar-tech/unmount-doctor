"""Packaging metadata contract tests.

These guard against setuptools deprecation drift that made builds noisy and
would eventually become unsupported: project.license must be a SPDX string,
license-files must include LICENSE, and deprecated license classifiers must
not return.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"


def _pyproject_text() -> str:
    return PYPROJECT.read_text(encoding="utf-8")


def _project_block() -> str:
    text = _pyproject_text()
    match = re.search(r"^\[project\]\n(?P<body>.*?)(?:\n\[|\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "pyproject.toml must contain a [project] table"
    return match.group("body")


def test_license_metadata_uses_spdx_string_not_deprecated_table():
    project = _project_block()
    assert 'license = "MIT"' in project
    assert "license = {" not in project
    assert 'license-files = ["LICENSE"]' in project


def test_deprecated_license_classifier_is_not_reintroduced():
    text = _pyproject_text()
    assert "License :: OSI Approved :: MIT License" not in text


def test_build_backend_supports_spdx_license_metadata():
    text = _pyproject_text()
    match = re.search(r'^requires\s*=\s*\["setuptools>=(\d+)"\]', text, re.MULTILINE)
    assert match, "build-system.requires must pin a setuptools minimum"
    assert int(match.group(1)) >= 77
