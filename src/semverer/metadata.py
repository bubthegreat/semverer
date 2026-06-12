"""Patch-level comparison of the packaging metadata in pyproject.toml.

The pyproject file is excluded from content hashing (semverer rewrites it on
every bump), so the fields that describe the shipped artifact are compared
here instead. None of them are part of the package's public API — the
importable surface is the only thing that can drive major or minor (see
PRINCIPLES.md) — so every difference is reported as a patch: the artifact
changed, the contract didn't.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from tomlkit import TOMLDocument

from semverer.models import Change, Severity

_LABEL = {
    "name": "distribution name",
    "requires_python": "requires-python",
    "dependencies": "dependencies",
    "optional_dependencies": "optional dependencies",
    "scripts": "entry points",
}


@dataclass(frozen=True)
class ProjectMetadata:
    """The packaging fields of one pyproject.toml, normalized for comparison.

    ``optional_dependencies`` entries are ``"extra:: dep"`` lines (plus an
    ``"extra::"`` marker per extra, so empty extras survive); ``scripts``
    entries are ``"group::name = target"`` lines covering
    ``[project.scripts]``, ``[project.gui-scripts]`` and every
    ``[project.entry-points.<group>]`` table.
    """

    name: str = ""
    requires_python: str = ""
    dependencies: tuple[str, ...] = ()
    optional_dependencies: tuple[str, ...] = ()
    scripts: tuple[str, ...] = ()


def read_metadata(doc: TOMLDocument) -> ProjectMetadata:
    """Extract the normalized packaging fields from a pyproject document."""
    project = doc.get("project", {})
    poetry = doc.get("tool", {}).get("poetry", {})
    name = str(project.get("name") or poetry.get("name") or "")
    requires_python = str(project.get("requires-python") or "")
    dependencies = tuple(sorted(str(dep) for dep in project.get("dependencies", [])))

    optional: list[str] = []
    extras = project.get("optional-dependencies", {})
    for extra in sorted(extras):
        optional.append(f"{extra}::")
        optional.extend(f"{extra}:: {dep}" for dep in sorted(str(d) for d in extras[extra]))

    scripts: list[str] = []
    groups = [
        ("scripts", project.get("scripts", {})),
        ("gui-scripts", project.get("gui-scripts", {})),
    ]
    entry_points = project.get("entry-points", {})
    groups += [(str(group), entry_points[group]) for group in entry_points]
    for group, table in groups:
        scripts.extend(f"{group}::{key} = {table[key]}" for key in table)

    return ProjectMetadata(
        name=name,
        requires_python=requires_python,
        dependencies=dependencies,
        optional_dependencies=tuple(optional),
        scripts=tuple(sorted(scripts)),
    )


def compare_metadata(old: ProjectMetadata, new: ProjectMetadata) -> list[Change]:
    """One patch-level change per packaging field that differs."""
    changes: list[Change] = []
    for spec in fields(ProjectMetadata):
        old_value, new_value = getattr(old, spec.name), getattr(new, spec.name)
        if old_value == new_value:
            continue
        label = _LABEL[spec.name]
        if isinstance(old_value, str):
            description = f"{label} changed ({old_value or 'unset'} -> {new_value or 'unset'})"
        else:
            description = f"{label} changed"
        key = f"pyproject.toml::{spec.name.replace('_', '-')}"
        changes.append(Change(Severity.PATCH, key, description))
    return changes
