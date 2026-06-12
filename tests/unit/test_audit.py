"""Audit behavior: history is read through the current layout, never vacuously.

Audit verifies; it never redefines (PRINCIPLES.md §7). The member list comes
from the working tree; refs where a member's package cannot be found skip
loudly, and a run that evaluates nothing fails instead of passing — the
original bug was 48/48 transitions skipped with exit 0.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from semverer.audit import audit_repository
from semverer.cli import app

runner = CliRunner()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def git_init(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    git(root, "config", "commit.gpgsign", "false")


def commit_all(root: Path, message: str) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-qm", message)


class TestMigratedLayoutFailsLoudly:
    """History in an older layout is skipped loudly, never silently passed."""

    def _migrated_repo(self, root: Path) -> None:
        # Commits 1-2 use a monorepo layout that no longer exists.
        git_init(root)
        write(root / "pyproject.toml", '[tool.semverer]\nmembers = ["packages/a"]\n')
        write(
            root / "packages" / "a" / "pyproject.toml",
            '[project]\nname = "a"\nversion = "1.0.0"\n\n[tool.semverer]\npackage = "src/a"\n',
        )
        write(root / "packages" / "a" / "src" / "a" / "__init__.py", "def f(a): ...\n")
        commit_all(root, "monorepo v1")
        write(root / "packages" / "a" / "src" / "a" / "__init__.py", "def f(a, b=1): ...\n")
        commit_all(root, "monorepo v2")

        # Commit 3: migrate to a single root package.
        git(root, "rm", "-rq", "packages")
        write(
            root / "pyproject.toml",
            '[project]\nname = "merged"\nversion = "2.0.0"\n\n'
            '[tool.semverer]\npackage = "src/merged"\n',
        )
        write(root / "src" / "merged" / "__init__.py", "def f(a, b=1): ...\n")
        commit_all(root, "merged layout")

    def test_pre_migration_refs_skip_with_a_reason(self, tmp_path):
        self._migrated_repo(tmp_path)
        reports = audit_repository(tmp_path)
        assert reports, "skipped transitions must be reported, not dropped"
        assert all(r.skipped for r in reports)
        assert any("package directory not found" in r.line for r in reports)

    def test_cli_fails_instead_of_passing_vacuously(self, tmp_path, monkeypatch):
        self._migrated_repo(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["audit"])
        assert result.exit_code == 1
        assert "could not evaluate any transition" in result.output

    def test_since_from_the_adoption_point_works(self, tmp_path, monkeypatch):
        self._migrated_repo(tmp_path)
        # One more commit in the current layout gives --since a transition.
        write(tmp_path / "src" / "merged" / "__init__.py", "def f(a, b=1):\n    return b\n")
        write(
            tmp_path / "pyproject.toml",
            '[project]\nname = "merged"\nversion = "2.0.1"\n\n'
            '[tool.semverer]\npackage = "src/merged"\n',
        )
        commit_all(tmp_path, "patch in new layout")
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["audit", "--since", "HEAD~1"])
        assert result.exit_code == 0
        assert "audit passed" in result.output


class TestSingleProjectRename:
    def test_rename_is_evaluated_as_a_patch_level_change(self, tmp_path):
        # The distribution name is not the public API (PRINCIPLES.md §1);
        # renaming it is a patch like any other metadata change.
        git_init(tmp_path)
        write(
            tmp_path / "pyproject.toml",
            '[project]\nname = "before"\nversion = "1.0.0"\n\n'
            '[tool.semverer]\npackage = "src/pkg"\n',
        )
        write(tmp_path / "src" / "pkg" / "__init__.py", "def f(a): ...\n")
        commit_all(tmp_path, "v1")
        write(
            tmp_path / "pyproject.toml",
            '[project]\nname = "after"\nversion = "1.0.1"\n\n'
            '[tool.semverer]\npackage = "src/pkg"\n',
        )
        commit_all(tmp_path, "renamed")

        reports = audit_repository(tmp_path)
        assert any("required patch" in r.line and not r.violation for r in reports), [
            r.line for r in reports
        ]


class TestVacuousPass:
    def _skipped_history(self, root: Path) -> None:
        """Two commits whose package dir never resolves: all transitions skip."""
        git_init(root)
        write(root / "pyproject.toml", '[project]\nname = "ghost"\nversion = "1.0.0"\n')
        write(root / "README.md", "one\n")
        commit_all(root, "v1")
        write(root / "README.md", "two\n")
        commit_all(root, "v2")

    def test_all_skipped_exits_nonzero(self, tmp_path, monkeypatch):
        self._skipped_history(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["audit"])
        assert result.exit_code == 1
        assert "could not evaluate any transition" in result.output

    def test_no_transitions_is_an_explicit_note_not_a_pass(self, tmp_path, monkeypatch):
        git_init(tmp_path)
        write(tmp_path / "pyproject.toml", '[project]\nname = "solo"\nversion = "1.0.0"\n')
        write(tmp_path / "src" / "solo" / "__init__.py", "def f(): ...\n")
        commit_all(tmp_path, "only commit")
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["audit"])
        assert result.exit_code == 0
        assert "nothing to audit" in result.output

    def test_tags_only_without_tags_says_nothing_to_audit(self, tmp_path, monkeypatch):
        self._skipped_history(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["audit", "--tags-only"])
        assert result.exit_code == 0
        assert "nothing to audit" in result.output


class TestMetadataInAudit:
    def test_dependency_change_requires_a_patch_historically(self, tmp_path):
        git_init(tmp_path)
        write(
            tmp_path / "pyproject.toml",
            '[project]\nname = "pkg"\nversion = "1.0.0"\ndependencies = []\n\n'
            '[tool.semverer]\npackage = "src/pkg"\n',
        )
        write(tmp_path / "src" / "pkg" / "__init__.py", "def f(a): ...\n")
        commit_all(tmp_path, "v1")
        # Identical code, but a new runtime dependency and no version move.
        write(
            tmp_path / "pyproject.toml",
            '[project]\nname = "pkg"\nversion = "1.0.0"\ndependencies = ["requests>=2"]\n\n'
            '[tool.semverer]\npackage = "src/pkg"\n',
        )
        commit_all(tmp_path, "dep added, no bump")

        reports = audit_repository(tmp_path)
        assert any(r.violation and "required patch" in r.line for r in reports), [
            r.line for r in reports
        ]
