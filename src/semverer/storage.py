"""Read and write semverer state in pyproject.toml, preserving formatting."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import tomlkit
from tomlkit import TOMLDocument

from semverer.metadata import ProjectMetadata


@dataclass
class Baseline:
    """The snapshot the next comparison runs against.

    ``version`` is the project version this snapshot was generated for; it is
    what lets a sufficient hand-made bump be respected instead of
    double-bumped. ``api`` maps symbol keys to canonical signatures,
    ``files`` maps root-relative paths to content hashes (any change is at
    least a patch), and ``metadata`` is the normalized install contract from
    pyproject.toml, which is excluded from ``files`` because semverer itself
    rewrites it.
    """

    version: str
    api: dict[str, str]
    files: dict[str, str]
    metadata: ProjectMetadata = field(default_factory=ProjectMetadata)


class ConfigError(Exception):
    """A malformed value in the ``[tool.semverer]`` configuration."""


def find_pyproject(start: Path) -> Path | None:
    for directory in (start, *start.parents):
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def load(pyproject: Path) -> TOMLDocument:
    return tomlkit.parse(pyproject.read_text(encoding="utf-8"))


def read_version(doc: TOMLDocument) -> str | None:
    """The project version, from ``[project]`` or a legacy ``[tool.poetry]``."""
    version = doc.get("project", {}).get("version")
    if version is None:
        version = doc.get("tool", {}).get("poetry", {}).get("version")
    return None if version is None else str(version)


def read_project_name(doc: TOMLDocument) -> str:
    """The distribution name, from ``[project]`` or a legacy ``[tool.poetry]``."""
    name = doc.get("project", {}).get("name")
    if name is None:
        name = doc.get("tool", {}).get("poetry", {}).get("name")
    return "" if name is None else str(name)


def read_package_config(doc: TOMLDocument) -> str | None:
    package = doc.get("tool", {}).get("semverer", {}).get("package")
    return None if package is None else str(package)


def _read_string_list(doc: TOMLDocument, key: str) -> list[str] | None:
    value = doc.get("tool", {}).get("semverer", {}).get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"[tool.semverer] {key} must be a list of strings")
    return [str(item) for item in value]


def read_packages_config(doc: TOMLDocument) -> list[str] | None:
    """Layout A: several source dirs sharing one version (``packages = [...]``)."""
    return _read_string_list(doc, "packages")


def read_members_config(doc: TOMLDocument) -> list[str] | None:
    """Layout B: independently-versioned monorepo members (``members = [...]``)."""
    return _read_string_list(doc, "members")


def read_tag_pattern(doc: TOMLDocument) -> str | None:
    """Audit tag glob with an optional ``{name}`` placeholder; default ``v*``."""
    pattern = doc.get("tool", {}).get("semverer", {}).get("tag_pattern")
    return None if pattern is None else str(pattern)


def read_name_config(doc: TOMLDocument) -> str | None:
    """A member's display/tag name override (``[tool.semverer] name``)."""
    name = doc.get("tool", {}).get("semverer", {}).get("name")
    return None if name is None else str(name)


def read_track_files(doc: TOMLDocument) -> bool:
    """Whether the whole project tree is hashed (default) or just the packages."""
    value = doc.get("tool", {}).get("semverer", {}).get("track_files")
    return True if value is None else bool(value)


def read_exclude(doc: TOMLDocument) -> list[str]:
    """Extra fnmatch globs excluded from file tracking."""
    return _read_string_list(doc, "exclude") or []


def read_baseline(doc: TOMLDocument) -> Baseline | None:
    table = doc.get("tool", {}).get("semverer", {}).get("baseline")
    if table is None:
        return None
    if "files" not in table and "hashes" in table:
        raise ConfigError(
            "the stored baseline was written by an older semverer; "
            "run 'semverer init' to refresh it"
        )
    meta = table.get("metadata", {})
    metadata = ProjectMetadata(
        name=str(meta.get("name", "")),
        requires_python=str(meta.get("requires-python", "")),
        dependencies=tuple(str(item) for item in meta.get("dependencies", [])),
        optional_dependencies=tuple(str(item) for item in meta.get("optional-dependencies", [])),
        scripts=tuple(str(item) for item in meta.get("scripts", [])),
    )
    return Baseline(
        version=str(table["version"]),
        api={str(key): str(value) for key, value in table.get("api", {}).items()},
        files={str(key): str(value) for key, value in table.get("files", {}).items()},
        metadata=metadata,
    )


def _set_version(doc: TOMLDocument, version: str) -> None:
    """Write the version back to whichever table it was read from."""
    project = doc.get("project")
    if project is not None and "version" in project:
        project["version"] = version
        return
    poetry = doc.get("tool", {}).get("poetry")
    if poetry is not None and "version" in poetry:
        poetry["version"] = version
        return
    if "project" not in doc:
        doc["project"] = tomlkit.table()
    doc["project"]["version"] = version


def write_state(pyproject: Path, doc: TOMLDocument, version: str, baseline: Baseline) -> None:
    """Set the project version and replace the stored baseline, touching nothing else."""
    _set_version(doc, version)

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

    meta = tomlkit.table()
    meta["name"] = baseline.metadata.name
    meta["requires-python"] = baseline.metadata.requires_python
    meta["dependencies"] = list(baseline.metadata.dependencies)
    meta["optional-dependencies"] = list(baseline.metadata.optional_dependencies)
    meta["scripts"] = list(baseline.metadata.scripts)
    baseline_table["metadata"] = meta

    file_table = tomlkit.table()
    for key in sorted(baseline.files):
        file_table[key] = baseline.files[key]
    api = tomlkit.table()
    for key in sorted(baseline.api):
        api[key] = baseline.api[key]
    baseline_table["files"] = file_table
    baseline_table["api"] = api
    semverer["baseline"] = baseline_table

    pyproject.write_text(tomlkit.dumps(doc), encoding="utf-8")
