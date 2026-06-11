# semverer

[![CI](https://github.com/bubthegreat/semverer/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/bubthegreat/semverer/actions/workflows/ci.yml)
[![Publish](https://github.com/bubthegreat/semverer/actions/workflows/publish.yml/badge.svg?branch=main)](https://github.com/bubthegreat/semverer/actions/workflows/publish.yml)
[![PyPI](https://img.shields.io/pypi/v/semverer)](https://pypi.org/project/semverer/)
[![Python versions](https://img.shields.io/pypi/pyversions/semverer)](https://pypi.org/project/semverer/)
[![License: MIT](https://img.shields.io/pypi/l/semverer)](LICENSE)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-blue)](https://mypy-lang.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Automatic [semantic versioning](https://semver.org/) for Python packages.
semverer inspects your package's AST, compares its **public API** against a
stored baseline, and bumps the version in `pyproject.toml` accordingly — so
you get correct major/minor/patch bumps for free, without having to think
about it. Run it standalone, in CI, or as a pre-commit hook.

## How it works

1. `semverer init` snapshots your package's public API (function/class/method
   signatures plus per-module implementation hashes) into
   `[tool.semverer.baseline]` in your `pyproject.toml`.
2. On every subsequent `semverer check`/`semverer update`, the current AST is
   compared against that baseline and each difference is classified.
3. The highest-severity difference decides the bump; `update` writes the new
   version and refreshes the baseline. Writes go through
   [tomlkit](https://github.com/python-poetry/tomlkit), so your file's
   formatting and comments are preserved.

The baseline is stored as flat, human-readable signature strings — diffs of
your `pyproject.toml` show exactly which API surface changed:

```toml
[tool.semverer.baseline.api]
"mypkg/cli.py::update" = "def update(package_path, *, dry_run=...)"
"mypkg/core.py::Engine" = "class Engine(Base)"
"mypkg/core.py::Engine.start" = "async def start(self, timeout=...)"
```

(Default values are normalized to `...`; changing a default's *value* is a
patch-level implementation change, not an API change.)

## Severity rules

| Change | Bump |
|---|---|
| Public symbol or module removed | **major** |
| Required parameter added; parameter removed, renamed, or reordered | **major** |
| Default removed (parameter becomes required) | **major** |
| `*args`/`**kwargs` removed; `def` ↔ `async def`; parameter kind changed | **major** |
| Base class removed or reordered | **major** |
| New public symbol or module | **minor** |
| New parameter with a default; new `*args`/`**kwargs` | **minor** |
| Parameter gains a default; base class added | **minor** |
| Implementation changed, public API identical (incl. private code) | **patch** |
| Comments/formatting only | none |

**Public API** = top-level functions and classes (and their methods) whose
names don't start with `_`, in modules whose names don't start with `_` —
plus `__init__.py` and dunder names, which are public. Nested functions are
implementation detail. Type annotations are ignored in v1 (they don't change
runtime compatibility).

The full executable specification lives in [`features/`](features/) as
Gherkin scenarios, bound to tests with pytest-bdd.

> **Note:** implementation hashes come from a canonical structural
> serialization of the AST, designed to be stable across Python minor
> versions (rendered text like `ast.unparse` is not — f-string quoting
> changed in 3.12, for example). The baseline records which interpreter
> wrote it (`python = "3.14"`); if a future Python ever changes AST shape
> for existing syntax, patch findings made under a mismatched interpreter
> are annotated with a note suggesting `semverer init` under the project's
> pinned Python.

## Install

```bash
pip install semverer   # or: uv tool install semverer
```

## Usage

```bash
semverer init     # one-time: establish the baseline for the current version
semverer check    # report the required bump (exit 1 if one is needed) — CI gate
semverer update   # apply the bump and refresh the baseline — pre-commit hook
```

The package directory is auto-detected from `[project].name` (`src/<name>/`
or `<name>/` layout). Override it in config or per-invocation:

```toml
[tool.semverer]
package = "src/mypkg"
```

```bash
semverer check src/mypkg --pyproject path/to/pyproject.toml
```

Exit codes follow the pre-commit convention: `0` nothing to do, `1` action
needed / files modified, `2` configuration error.

If you bump the version by hand, semverer respects it: a manual bump at least
as large as the required severity is accepted instead of bumped again.

## Auditing existing history

```bash
semverer audit                      # every commit on the current branch
semverer audit --tags-only          # only published v* release tags
semverer audit --since v1.4.0      # from an adoption point forward
```

`audit` replays your git history: for each pair of consecutive commits (or
tags), it extracts both API snapshots directly from the git blobs and checks
that the recorded version moved at least as far as the rules require. Under-
bumps are violations (exit 1); over-bumps are allowed and noted. Run it
before `init` on an existing project to see how honest your versions have
been — and run it in CI like this repo does (`semverer audit --tags-only`),
where semverer's own published tags are its permanent integration test.

```
  v0.1.0..v0.2.0: required minor, version 0.1.0 -> 0.2.0  OK
semverer: audit passed (1 OK, 0 skipped)
```

## As a pre-commit hook

```yaml
repos:
  - repo: https://github.com/bubthegreat/semverer
    rev: v0.1.0
    hooks:
      - id: semverer
```

When your public API changes, the hook updates `pyproject.toml` and fails the
commit; `git add pyproject.toml` and commit again. Use the `semverer-check`
hook id instead if you only want enforcement without writes.

**Ordering tip:** list semverer *after* your lint/type/test hooks and set
`fail_fast: true` at the top of your `.pre-commit-config.yaml` — pre-commit
runs all hooks even after a failure by default, so without `fail_fast` a
version bump could land alongside failing tests. This repo's own
[`.pre-commit-config.yaml`](.pre-commit-config.yaml) shows the pattern
(ruff → mypy → pytest → semverer).

## As a Claude Code skill

```bash
semverer skill install          # into this project's .claude/skills/
semverer skill install --user   # into ~/.claude/skills/ for all projects
```

Claude Code then knows to run `semverer check`/`update` whenever it changes
Python code in a semverer-managed package.

## Known limitations (v1)

- **Literal `[project] version` required.** Dynamic versioning
  (`dynamic = ["version"]`, hatch-vcs, setuptools-scm) and Poetry's
  `[tool.poetry]` metadata are not supported; semverer needs a version field
  it can read and rewrite. Versions must be valid semver
  (`MAJOR.MINOR.PATCH` — calver like `2026.1` is rejected with a clear error).
- **One package per pyproject.** Monorepos with several published packages
  under one `pyproject.toml` are out of scope.
- **Only statically visible definitions are API.** Symbols defined inside
  `if`/`try` blocks (e.g. `TYPE_CHECKING` stubs, import fallbacks), lambdas
  assigned to names, and anything built dynamically are invisible to
  signature comparison — changes to them surface as patch-level via the
  implementation hash.
- **Same-name redefinitions collapse.** `@typing.overload` stacks and
  `@property`/setter pairs share one name; the last definition's signature
  wins. Changes to the others are patch-level.
- **`__all__` is not consulted.** Public/private is determined by naming
  convention only (leading underscore).
- **Decorators are not interpreted.** A decorator that rewrites a function's
  real signature (e.g. some wrappers) is not seen through.

## Development

```bash
uv sync --all-groups
uv run pre-commit install   # one-time: makes git commit run the hook chain
uv run pytest
```

The Gherkin features in `features/` are the spec; new behavior starts with a
scenario there. Unit tests in `tests/unit/` cover extraction and
classification edge cases.
