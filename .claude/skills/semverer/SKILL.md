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
