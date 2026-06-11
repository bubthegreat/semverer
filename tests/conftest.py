"""Shared fixtures: a throwaway project factory and a CLI runner."""

from __future__ import annotations

import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomlkit
from typer.testing import CliRunner

from semverer.cli import app

PYPROJECT_WITH_CONFIG = """\
# managed by mypkg maintainers
[project]
name = "mypkg"
version = "{version}"

# semverer configuration
[tool.semverer]
package = "src/mypkg"
"""

PYPROJECT_WITHOUT_CONFIG = """\
# managed by mypkg maintainers
[project]
name = "mypkg"
version = "{version}"
"""

PYPROJECT_DYNAMIC = """\
[project]
name = "mypkg"
dynamic = ["version"]

[tool.semverer]
package = "src/mypkg"
"""


@dataclass
class Project:
    root: Path
    runner: CliRunner = field(default_factory=CliRunner)
    result: Any = None

    @property
    def pyproject(self) -> Path:
        return self.root / "pyproject.toml"

    @property
    def package_dir(self) -> Path:
        return self.root / "src" / "mypkg"

    def write_module(self, name: str, source: str) -> None:
        path = self.package_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source))

    def run(self, args: str) -> Any:
        self.result = self.runner.invoke(app, args.split())
        return self.result

    def read_pyproject(self) -> tomlkit.TOMLDocument:
        return tomlkit.parse(self.pyproject.read_text())

    def read_version(self) -> str:
        return str(self.read_pyproject()["project"]["version"])

    def read_baseline(self) -> dict | None:
        data = self.read_pyproject()
        return data.get("tool", {}).get("semverer", {}).get("baseline")

    def set_version(self, version: str) -> None:
        data = self.read_pyproject()
        data["project"]["version"] = version
        self.pyproject.write_text(tomlkit.dumps(data))

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True, check=True
        )
        return result.stdout

    def git_init(self) -> None:
        self.git("init", "-q")
        self.git("config", "user.email", "test@test")
        self.git("config", "user.name", "test")
        self.git("config", "commit.gpgsign", "false")


def make_project(
    tmp_path: Path,
    monkeypatch,
    version: str = "1.0.0",
    with_config: bool = True,
    dynamic: bool = False,
) -> Project:
    if dynamic:
        content = PYPROJECT_DYNAMIC
    else:
        template = PYPROJECT_WITH_CONFIG if with_config else PYPROJECT_WITHOUT_CONFIG
        content = template.format(version=version)
    (tmp_path / "pyproject.toml").write_text(content)
    project = Project(root=tmp_path)
    project.package_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return project
