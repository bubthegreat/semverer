"""Packaging metadata comparison: every difference is patch, never more.

The importable surface is the only public API (PRINCIPLES.md §1-2); the
install contract — name, dependencies, extras, entry points,
requires-python — is part of the shipped artifact, so changes to it are
patch-level by §3.
"""

from __future__ import annotations

import tomlkit

from semverer.metadata import compare_metadata, read_metadata
from semverer.models import Severity


def meta(text: str):
    return read_metadata(tomlkit.parse(text))


BASE = """\
[project]
name = "pkg"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = ["tomlkit>=0.13"]

[project.optional-dependencies]
cli = ["typer>=0.15"]

[project.scripts]
pkg = "pkg.cli:app"
"""


class TestReadMetadata:
    def test_extraction(self):
        snapshot = meta(BASE)
        assert snapshot.name == "pkg"
        assert snapshot.requires_python == ">=3.10"
        assert snapshot.dependencies == ("tomlkit>=0.13",)
        assert snapshot.optional_dependencies == ("cli::", "cli:: typer>=0.15")
        assert snapshot.scripts == ("scripts::pkg = pkg.cli:app",)

    def test_poetry_name_fallback(self):
        snapshot = meta('[tool.poetry]\nname = "poetic"\nversion = "1.0.0"\n')
        assert snapshot.name == "poetic"

    def test_entry_point_groups_flattened(self):
        snapshot = meta(
            '[project]\nname = "pkg"\n\n'
            '[project.entry-points."pkg.plugins"]\nalpha = "pkg.alpha:load"\n'
        )
        assert snapshot.scripts == ("pkg.plugins::alpha = pkg.alpha:load",)


class TestComparison:
    def test_identical_is_clean(self):
        assert compare_metadata(meta(BASE), meta(BASE)) == []

    def test_every_field_change_is_patch_and_nothing_more(self):
        variants = {
            "name": BASE.replace('"pkg"', '"newpkg"', 1),
            "requires-python": BASE.replace(">=3.10", ">=3.12"),
            "dependencies": BASE.replace('["tomlkit>=0.13"]', '["tomlkit>=0.13", "rich>=13"]'),
            "optional-dependencies": BASE.replace("typer>=0.15", "typer>=0.16"),
            "scripts": BASE.replace("pkg.cli:app", "pkg.main:app"),
        }
        for field_key, text in variants.items():
            changes = compare_metadata(meta(BASE), meta(text))
            assert len(changes) == 1, (field_key, changes)
            assert changes[0].severity is Severity.PATCH, field_key
            assert changes[0].key == f"pyproject.toml::{field_key}"

    def test_console_script_removed_is_patch_not_major(self):
        # Entry points are install conveniences, not the importable API.
        new = meta(BASE.replace('[project.scripts]\npkg = "pkg.cli:app"\n', ""))
        changes = compare_metadata(meta(BASE), new)
        assert [c.severity for c in changes] == [Severity.PATCH]

    def test_extra_removed_is_patch_not_major(self):
        new = meta(BASE.replace('[project.optional-dependencies]\ncli = ["typer>=0.15"]\n\n', ""))
        changes = compare_metadata(meta(BASE), new)
        assert [c.severity for c in changes] == [Severity.PATCH]

    def test_string_fields_describe_old_and_new(self):
        changes = compare_metadata(meta(BASE), meta(BASE.replace(">=3.10", ">=3.12")))
        assert ">=3.10 -> >=3.12" in changes[0].description
