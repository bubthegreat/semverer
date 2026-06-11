"""The Claude Code Agent Skill shipped with semverer."""

from __future__ import annotations

from pathlib import Path

SKILL_CONTENT = """\
---
name: semverer
description: >-
  Automatic semantic versioning for Python packages. Use when working in a
  Python package with a pyproject.toml — after adding, removing, or changing
  functions, classes, or methods — to determine and apply the correct
  major/minor/patch version bump from AST-level public API changes, or when
  the user asks what version a change should be.
---

# semverer: automatic semantic versioning

This package's version is managed by semverer, which derives the required
semver bump from changes to the package's public API (detected via AST).

## Commands

- `semverer check` — report the required bump without writing anything.
  Exit 0 = up to date, exit 1 = bump needed (or no baseline yet),
  exit 2 = configuration error.
- `semverer update` — apply the bump and refresh the baseline stored in
  `[tool.semverer.baseline]` in pyproject.toml. Exit 1 means it modified
  pyproject.toml; stage the file and continue.
- `semverer init` — establish a baseline for the current version
  (first-time setup, or after intentionally rewriting history).
- `semverer audit [--tags-only] [--since REF]` — replay git history and
  verify recorded versions satisfied the severity rules; use it to assess
  a project before adopting semverer.

## How to work in a semverer-managed package

- After changing Python source, run `semverer check` to see the impact;
  run `semverer update` before committing so the version and baseline stay
  in sync with the code.
- Never hand-edit `[tool.semverer.baseline]`; it is machine-managed.
- Do not hand-bump the version for API changes — semverer computes it.
  A hand-made bump at least as large as required is respected, not
  double-bumped.
- Severity rules: removing/breaking public signatures = major; adding
  public API or optional parameters = minor; implementation-only changes
  = patch; comment/formatting-only changes = no bump.
"""


def install(base_dir: Path) -> Path:
    """Write the skill under ``base_dir/.claude/skills/`` and return its path."""
    path = base_dir / ".claude" / "skills" / "semverer" / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SKILL_CONTENT, encoding="utf-8")
    return path
