"""Multi-package discovery and the CLI loop over targets (Layouts A and B)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import tomlkit
from typer.testing import CliRunner

from semverer.audit import audit_repository
from semverer.cli import app
from semverer.discovery import DiscoveryError, discover
from semverer.extractor import DuplicateModuleError, extract_packages

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


def version_of(pyproject: Path) -> str:
    return str(tomlkit.parse(pyproject.read_text())["project"]["version"])


def baseline_of(pyproject: Path) -> dict:
    return tomlkit.parse(pyproject.read_text())["tool"]["semverer"]["baseline"]


# --- Layout A: several packages, one shared version -------------------------


def layout_a(root: Path, version: str = "1.0.0") -> Path:
    pyproject = root / "pyproject.toml"
    write(
        pyproject,
        f'[project]\nname = "combo"\nversion = "{version}"\n\n'
        '[tool.semverer]\npackages = ["src/foo", "src/bar"]\n',
    )
    write(root / "src" / "foo" / "__init__.py", "def foo_one():\n    return 1\n")
    write(root / "src" / "bar" / "__init__.py", "def bar_one():\n    return 1\n")
    return pyproject


class TestLayoutA:
    def test_discovers_single_target_with_two_dirs(self, tmp_path):
        layout_a(tmp_path)
        targets = discover(tmp_path)
        assert len(targets) == 1
        assert {p.name for p in targets[0].package_dirs} == {"foo", "bar"}

    def test_unions_api_into_one_baseline(self, tmp_path, monkeypatch):
        pyproject = layout_a(tmp_path)
        monkeypatch.chdir(tmp_path)
        assert runner.invoke(app, ["init"]).exit_code == 0
        keys = set(baseline_of(pyproject)["api"])
        assert "foo/__init__.py::foo_one" in keys
        assert "bar/__init__.py::bar_one" in keys

    def test_change_in_one_dir_bumps_the_shared_version(self, tmp_path, monkeypatch):
        pyproject = layout_a(tmp_path)
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init"])
        # Remove a public function from foo: a breaking change.
        write(tmp_path / "src" / "foo" / "__init__.py", "def renamed():\n    return 1\n")
        result = runner.invoke(app, ["update"])
        assert result.exit_code == 1
        assert version_of(pyproject) == "2.0.0"

    def test_leaf_name_collision_is_rejected(self, tmp_path, monkeypatch):
        write(
            tmp_path / "pyproject.toml",
            '[project]\nname = "combo"\nversion = "1.0.0"\n\n'
            '[tool.semverer]\npackages = ["src/foo", "vendored/foo"]\n',
        )
        write(tmp_path / "src" / "foo" / "__init__.py", "def a():\n    return 1\n")
        write(tmp_path / "vendored" / "foo" / "__init__.py", "def b():\n    return 1\n")
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 2
        assert "both map to module" in result.output

    def test_package_and_packages_are_mutually_exclusive(self, tmp_path):
        write(
            tmp_path / "pyproject.toml",
            '[project]\nname = "combo"\nversion = "1.0.0"\n\n'
            '[tool.semverer]\npackage = "src/foo"\npackages = ["src/foo"]\n',
        )
        write(tmp_path / "src" / "foo" / "__init__.py", "def a():\n    return 1\n")
        with pytest.raises(DiscoveryError, match="either"):
            discover(tmp_path)


# --- Layout B: monorepo of independently-versioned members ------------------


def layout_b(root: Path) -> dict[str, Path]:
    write(
        root / "pyproject.toml",
        '[tool.semverer]\nmembers = ["packages/a", "packages/b"]\n',
    )
    members = {}
    for name in ("a", "b"):
        member = root / "packages" / name
        write(
            member / "pyproject.toml",
            f'[project]\nname = "{name}"\nversion = "1.0.0"\n\n'
            f'[tool.semverer]\npackage = "src/{name}"\n',
        )
        write(member / "src" / name / "__init__.py", f"def {name}_one():\n    return 1\n")
        members[name] = member / "pyproject.toml"
    return members


class TestLayoutB:
    def test_discovers_one_target_per_member(self, tmp_path):
        layout_b(tmp_path)
        targets = discover(tmp_path)
        assert {t.name for t in targets} == {"a", "b"}

    def test_init_seeds_every_member_baseline(self, tmp_path, monkeypatch):
        members = layout_b(tmp_path)
        monkeypatch.chdir(tmp_path)
        assert runner.invoke(app, ["init"]).exit_code == 0
        assert "a/__init__.py::a_one" in set(baseline_of(members["a"])["api"])
        assert "b/__init__.py::b_one" in set(baseline_of(members["b"])["api"])

    def test_change_bumps_only_the_affected_member(self, tmp_path, monkeypatch):
        members = layout_b(tmp_path)
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init"])
        # Add a function to member a (minor); leave b untouched.
        write(
            tmp_path / "packages" / "a" / "src" / "a" / "__init__.py",
            "def a_one():\n    return 1\n\n\ndef a_two():\n    return 2\n",
        )
        result = runner.invoke(app, ["update"])
        assert result.exit_code == 1
        assert version_of(members["a"]) == "1.1.0"
        assert version_of(members["b"]) == "1.0.0"

    def test_member_filter_scopes_check(self, tmp_path, monkeypatch):
        layout_b(tmp_path)
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init"])
        write(
            tmp_path / "packages" / "a" / "src" / "a" / "__init__.py",
            "def a_one():\n    return 1\n\n\ndef a_two():\n    return 2\n",
        )
        assert runner.invoke(app, ["check", "--member", "a"]).exit_code == 1
        assert runner.invoke(app, ["check", "--member", "b"]).exit_code == 0

    def test_unknown_member_fails(self, tmp_path, monkeypatch):
        layout_b(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["check", "--member", "nope"])
        assert result.exit_code == 2
        assert "no member matching" in result.output

    def test_member_missing_pyproject_is_reported(self, tmp_path):
        write(
            tmp_path / "pyproject.toml",
            '[tool.semverer]\nmembers = ["packages/ghost"]\n',
        )
        with pytest.raises(DiscoveryError, match="ghost"):
            discover(tmp_path)


# --- Back-compat: classic single package still resolves to one target -------


class TestClassic:
    def test_single_package_auto_detect(self, tmp_path):
        write(tmp_path / "pyproject.toml", '[project]\nname = "solo"\nversion = "1.0.0"\n')
        write(tmp_path / "src" / "solo" / "__init__.py", "def f():\n    return 1\n")
        targets = discover(tmp_path)
        assert len(targets) == 1
        assert targets[0].package_dirs[0].name == "solo"


# --- Bounded discovery: top level and exactly one level deep -----------------


def one_deep_project(root: Path, name: str) -> None:
    write(
        root / name / "pyproject.toml",
        f'[project]\nname = "{name}"\nversion = "1.0.0"\n\n'
        f'[tool.semverer]\npackage = "src/{name}"\n',
    )
    write(root / name / "src" / name / "__init__.py", "def f(a): ...\n")


class TestOneDeepDiscovery:
    def test_projects_one_level_down_are_found(self, tmp_path):
        # A polyglot monorepo root with no pyproject of its own.
        one_deep_project(tmp_path, "alpha")
        one_deep_project(tmp_path, "beta")
        write(tmp_path / "frontend" / "package.json", "{}\n")  # other-language member
        targets = discover(tmp_path)
        assert {t.name for t in targets} == {"alpha", "beta"}

    def test_two_levels_down_is_out_of_scope(self, tmp_path):
        one_deep_project(tmp_path / "nested", "deep")
        with pytest.raises(DiscoveryError, match="one level deep"):
            discover(tmp_path)

    def test_nothing_found_gives_the_specify_it_message(self, tmp_path):
        write(tmp_path / "README.md", "not a python repo\n")
        with pytest.raises(DiscoveryError, match="specify the project"):
            discover(tmp_path)

    def test_versionless_pyprojects_are_not_clear_packages(self, tmp_path):
        # A tooling-only pyproject (ruff config, no version) doesn't count.
        write(tmp_path / "tools" / "pyproject.toml", "[tool.ruff]\nline-length = 100\n")
        with pytest.raises(DiscoveryError, match="no clear Python package"):
            discover(tmp_path)

    def test_tooling_only_root_pyproject_falls_through_to_one_deep(self, tmp_path):
        write(tmp_path / "pyproject.toml", "[tool.ruff]\nline-length = 100\n")
        one_deep_project(tmp_path, "alpha")
        targets = discover(tmp_path)
        assert [t.name for t in targets] == ["alpha"]


# --- Poetry (legacy [tool.poetry]) convention -------------------------------


class TestPoetry:
    def _project(self, root: Path, version: str = "1.0.0") -> Path:
        pyproject = root / "pyproject.toml"
        write(
            pyproject,
            f'[tool.poetry]\nname = "poetrypkg"\nversion = "{version}"\n\n'
            '[tool.semverer]\npackage = "src/poetrypkg"\n',
        )
        write(root / "src" / "poetrypkg" / "__init__.py", "def f(a): ...\n")
        return pyproject

    def test_discovers_via_poetry_metadata(self, tmp_path):
        self._project(tmp_path)
        targets = discover(tmp_path)
        assert len(targets) == 1
        assert targets[0].name == "poetrypkg"
        assert targets[0].version == "1.0.0"

    def test_bump_writes_back_to_poetry_table(self, tmp_path, monkeypatch):
        pyproject = self._project(tmp_path)
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init"])
        write(tmp_path / "src" / "poetrypkg" / "__init__.py", "def f(a, b): ...\n")
        result = runner.invoke(app, ["update"])
        assert result.exit_code == 1
        doc = tomlkit.parse(pyproject.read_text())
        assert str(doc["tool"]["poetry"]["version"]) == "2.0.0"
        assert "project" not in doc  # version stayed in [tool.poetry]


# --- extractor merge --------------------------------------------------------


def member_pyproject(name: str, version: str) -> str:
    return (
        f'[project]\nname = "{name}"\nversion = "{version}"\n\n'
        f'[tool.semverer]\npackage = "src/{name}"\ntag_pattern = "{{name}}-v*"\n'
    )


class TestAuditMonorepo:
    def _seed(self, root: Path) -> None:
        write(root / "pyproject.toml", '[tool.semverer]\nmembers = ["packages/a", "packages/b"]\n')
        for name in ("a", "b"):
            write(root / "packages" / name / "pyproject.toml", member_pyproject(name, "1.0.0"))
            write(root / "packages" / name / "src" / name / "__init__.py", "def f(a): ...\n")
        git_init(root)
        git(root, "add", "-A")
        git(root, "commit", "-qm", "v1")
        git(root, "tag", "a-v1.0.0")
        git(root, "tag", "b-v1.0.0")

    def test_per_member_tags_audit_independently(self, tmp_path):
        self._seed(tmp_path)
        # Member a adds a function (minor) and is bumped to 1.1.0; b is untouched.
        write(tmp_path / "packages" / "a" / "pyproject.toml", member_pyproject("a", "1.1.0"))
        write(
            tmp_path / "packages" / "a" / "src" / "a" / "__init__.py",
            "def f(a): ...\ndef g(): ...\n",
        )
        git(tmp_path, "add", "-A")
        git(tmp_path, "commit", "-qm", "v2")
        git(tmp_path, "tag", "a-v1.1.0")

        reports = audit_repository(tmp_path, tags_only=True)
        assert all(not report.violation for report in reports)
        assert any("[a]" in report.line for report in reports)

    def test_member_under_bump_is_flagged_with_label(self, tmp_path):
        self._seed(tmp_path)
        # Member a removes f (breaking) but only bumps to a minor 1.1.0.
        write(tmp_path / "packages" / "a" / "pyproject.toml", member_pyproject("a", "1.1.0"))
        write(tmp_path / "packages" / "a" / "src" / "a" / "__init__.py", "def other(a): ...\n")
        git(tmp_path, "add", "-A")
        git(tmp_path, "commit", "-qm", "v2")
        git(tmp_path, "tag", "a-v1.1.0")

        reports = audit_repository(tmp_path, tags_only=True)
        violations = [report for report in reports if report.violation]
        assert len(violations) == 1
        assert "[a]" in violations[0].line


class TestExtractPackages:
    def test_merges_distinct_leaf_dirs(self, tmp_path):
        write(tmp_path / "foo" / "__init__.py", "def a():\n    return 1\n")
        write(tmp_path / "bar" / "__init__.py", "def b():\n    return 1\n")
        api = extract_packages([tmp_path / "foo", tmp_path / "bar"])
        assert "foo/__init__.py::a" in api
        assert "bar/__init__.py::b" in api

    def test_raises_on_colliding_leaf(self, tmp_path):
        write(tmp_path / "x" / "foo" / "__init__.py", "def a():\n    return 1\n")
        write(tmp_path / "y" / "foo" / "__init__.py", "def b():\n    return 1\n")
        with pytest.raises(DuplicateModuleError):
            extract_packages([tmp_path / "x" / "foo", tmp_path / "y" / "foo"])
