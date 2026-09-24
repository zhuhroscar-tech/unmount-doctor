"""Repository completeness contracts for release-ready maintenance.

These tests keep the small project-level files honest: users should be able to
find license/release history, CI should keep packaging artifacts covered, and
the current source version should have a matching changelog entry.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class RepositoryContractTests(unittest.TestCase):
    def _read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_required_project_files_exist(self):
        for relative in [
            "README.md",
            "README.zh-CN.md",
            "CHANGELOG.md",
            "LICENSE",
            "pyproject.toml",
            ".github/workflows/ci.yml",
            ".github/workflows/codeql.yml",
        ]:
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_file(), f"missing {relative}")

    def test_readmes_link_license_changelog_and_releases(self):
        expectations = {
            "README.md": ["CHANGELOG.md", "Releases", "LICENSE"],
            "README.zh-CN.md": ["CHANGELOG.md", "Releases", "LICENSE"],
        }
        for relative, required in expectations.items():
            text = self._read(relative)
            with self.subTest(relative=relative):
                for needle in required:
                    self.assertIn(needle, text)

    def test_current_version_has_changelog_entry(self):
        pyproject = self._read("pyproject.toml")
        match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
        if match is None:
            self.fail("pyproject.toml must declare project.version")
        version = match.group(1)
        changelog = self._read("CHANGELOG.md")
        self.assertIn(f"## v{version}", changelog)
        self.assertIn("Published wheel, sdist", changelog)

    def test_ci_builds_and_publishes_release_assets(self):
        ci = self._read(".github/workflows/ci.yml")
        for needle in [
            "python -m build",
            "python -m zipapp",
            "sha256sum *.whl *.tar.gz unmount-doctor.pyz",
            "softprops/action-gh-release@v2",
            "dist/unmount-doctor.pyz",
            "dist/SHA256SUMS.txt",
        ]:
            with self.subTest(needle=needle):
                self.assertIn(needle, ci)

    def test_codeql_workflow_keeps_security_scanning_enabled(self):
        codeql = self._read(".github/workflows/codeql.yml")
        self.assertIn("github/codeql-action/init", codeql)
        self.assertIn("github/codeql-action/analyze", codeql)


if __name__ == "__main__":
    unittest.main()
