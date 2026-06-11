"""Read and write semverer state in pyproject.toml, preserving formatting."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tomlkit
from tomlkit import TOMLDocument


@dataclass
class Baseline:
    """The API snapshot the next comparison runs against.

    ``version`` is the project version this snapshot was generated for; it is
    what lets a sufficient hand-made bump be respected instead of double-bumped.
    ``python`` is the interpreter minor that produced ``hashes`` — hashes from
    different minors are not comparable (see extractor.hash_module). ``None``
    means a baseline written before this field existed.
    """

    version: str
    api: dict[str, str]
    hashes: dict[str, str]
    python: str | None = None


def find_pyproject(start: Path) -> Path | None:
    for directory in (start, *start.parents):
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def load(pyproject: Path) -> TOMLDocument:
    return tomlkit.parse(pyproject.read_text(encoding="utf-8"))


def read_version(doc: TOMLDocument) -> str | None:
    version = doc.get("project", {}).get("version")
    return None if version is None else str(version)


def read_package_config(doc: TOMLDocument) -> str | None:
    package = doc.get("tool", {}).get("semverer", {}).get("package")
    return None if package is None else str(package)


def read_baseline(doc: TOMLDocument) -> Baseline | None:
    table = doc.get("tool", {}).get("semverer", {}).get("baseline")
    if table is None:
        return None
    python = table.get("python")
    return Baseline(
        version=str(table["version"]),
        api={str(key): str(value) for key, value in table.get("api", {}).items()},
        hashes={str(key): str(value) for key, value in table.get("hashes", {}).items()},
        python=None if python is None else str(python),
    )


def write_state(pyproject: Path, doc: TOMLDocument, version: str, baseline: Baseline) -> None:
    """Set project.version and replace the stored baseline, touching nothing else."""
    doc["project"]["version"] = version

    tool = doc.get("tool")
    if tool is None:
        tool = tomlkit.table(is_super_table=True)
        doc["tool"] = tool
    semverer = tool.get("semverer")
    if semverer is None:
        semverer = tomlkit.table()
        tool["semverer"] = semverer

    baseline_table = tomlkit.table()
    baseline_table["version"] = baseline.version
    if baseline.python is not None:
        baseline_table["python"] = baseline.python
    hashes = tomlkit.table()
    for key in sorted(baseline.hashes):
        hashes[key] = baseline.hashes[key]
    api = tomlkit.table()
    for key in sorted(baseline.api):
        api[key] = baseline.api[key]
    baseline_table["hashes"] = hashes
    baseline_table["api"] = api
    semverer["baseline"] = baseline_table

    pyproject.write_text(tomlkit.dumps(doc), encoding="utf-8")
