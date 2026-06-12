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
| Any other change to a tracked file (docs, data, CI config, comments/formatting) | **patch** |
| Packaging metadata changed (dependencies, entry points, extras, requires-python, name) | **patch** |

Only the importable surface can drive major or minor; everything else the
project ships is patch at most. The reasoning behind every rule lives in
[PRINCIPLES.md](PRINCIPLES.md).

**Public API** = top-level functions and classes (and their methods) whose
names don't start with `_`, in modules whose names don't start with `_` —
plus `__init__.py` and dunder names, which are public. Nested functions are
implementation detail. Type annotations are ignored in v1 (they don't change
runtime compatibility).

The full executable specification lives in [`features/`](features/) as
Gherkin scenarios, bound to tests with pytest-bdd.

> **What counts as a change:** the public API decides between major and
> minor; everything else decides whether a patch is due. The whole project
> tree is content-hashed into the baseline (built-in ignores: `.git`,
> `__pycache__`, `.venv`, `dist`, `build`, caches, `*.egg-info`), so no
> commit that changes the project can ship without moving the version. Two
> files are deliberately untracked because semverer rewrites them itself:
> `pyproject.toml` (its packaging fields — name, dependencies,
> requires-python, extras, entry points — are compared field-by-field
> instead, all patch-level) and `uv.lock`. Narrow the scan with
> `[tool.semverer] track_files = false` (package dirs only) or
> `exclude = ["notes/*", ...]` globs.

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

### Version formats

Versions are read with [PEP 440](https://peps.python.org/pep-0440/) — the
scheme pip and PyPI speak — but must resolve to the
[semver spec](https://semver.org)'s `MAJOR.MINOR.PATCH` before semverer will
manage them. Short releases are moved onto the spec (`1.4` → `1.4.0` at
init); epochs (`1!1.2.3`) and releases with extra components (`1.2.3.4`)
exit gracefully with a message to start from a compliant version first.

- **`0.x` is unstable** (SemVer §4). The leading zero never auto-increments;
  severity is demoted one level (a breaking change bumps `0.3.0 → 0.4.0`, a
  feature/fix bumps the patch). Declaring `1.0.0` — the act that defines your
  stable API (§5) — is always yours, never the robot's.
- **Pre-releases bump from their base.** `1.4.3rc1` is read as base `1.4.3`:
  a patch-level change lands on `1.4.4`, a breaking change on `2.0.0`.
  semverer accepts rc/dev/post suffixes but never iterates their counters —
  the next version is always a real one.

### Several packages in one distribution

If a single distribution ships more than one importable package, list them
with `packages`; their APIs are unioned into one baseline and share the one
`[project].version`:

```toml
[tool.semverer]
packages = ["src/foo", "src/bar"]
```

### Monorepos (independently-versioned members)

For a monorepo where each subproject has its own `pyproject.toml` and version,
list the members at the repo root. `check`/`update`/`init`/`audit` then operate
on every member; `--member <name>` limits to one:

```toml
# ./pyproject.toml  (the workspace root)
[tool.semverer]
members = ["packages/foo", "packages/bar"]
```

Without a root config, discovery is bounded by design: the top level, then
exactly **one** directory level deeper (each subdirectory with its own
versioned `pyproject.toml` becomes a member — handy for polyglot monorepos
with no Python root). Anything more nested must be named explicitly via
`members`, a path argument, or `--pyproject`; if nothing is found, semverer
says so and asks you to specify the project rather than guessing.

Each member is itself classic or a `packages` Layout-A unit, and may set
`tag_pattern` (with a `{name}` placeholder, default `v*`) so `audit --tags-only`
finds its release tags — e.g. `tag_pattern = "{name}-v*"` matches `foo-v1.2.0`.

If you bump the version by hand, semverer respects it: a manual bump at least
as large as the required severity is accepted instead of bumped again.

## Auditing existing history

```bash
semverer audit                      # every commit on the current branch
semverer audit --tags-only          # only published release tags (v* by default)
semverer audit --since v1.4.0      # from an adoption point forward
```

`audit` replays your git history: for each pair of consecutive commits (or
tags), it extracts both snapshots directly from the git blobs and checks
that the recorded version moved at least as far as the rules require —
exactly the rules `check`/`update` apply, nothing more. History is read
through the current layout; refs that predate it are skipped with a reason,
and a run that cannot evaluate a single transition fails loudly instead of
passing vacuously (start from the adoption point with `--since` for older
histories). Under-bumps and backward version moves are violations (exit 1);
over-bumps are allowed and noted. Run it before `init` on an existing
project to see how honest your versions have been — and run it in CI like
this repo does (`semverer audit --tags-only`), where semverer's own
published tags are its permanent integration test.

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
semverer skill install            # into ~/.claude/skills/ for all projects (default)
semverer skill install --project  # into this project's .claude/skills/
```

Claude Code then knows to run `semverer check`/`update` whenever it changes
Python code in a semverer-managed package.

## Known limitations (v1)

- **A literal version field is required.** semverer reads and rewrites the
  version, so dynamic versioning (`dynamic = ["version"]`, hatch-vcs,
  setuptools-scm) is rejected with a clear error. Both `[project].version` and
  the legacy `[tool.poetry].version` are supported. Versions must be valid
  PEP 440 (calver like `2026.1` is accepted; arbitrary strings are rejected).
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
