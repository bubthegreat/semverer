# Guiding principles

semverer is an implementation of [Semantic Versioning 2.0.0](https://semver.org)
for Python packages. Every severity decision in this codebase must trace back
to one of the principles below, and each principle traces back to the spec.
When a proposed rule doesn't fit a principle, the rule is wrong — not the
principle.

## 1. The public API is the importable surface

SemVer §1 requires software to *declare* a public API. semverer's declaration:
**the top-level public functions, classes, and methods of the configured
package directory(ies)** — what a consumer reaches with `import`. Signatures
are the contract; names starting with `_` are not part of it; dunders are.

Nothing else is the public API. Not the distribution name, not entry points,
not dependencies, not the build system, not the repository layout.

## 2. Only the public API can drive major or minor

- **Major** (§8): a backward *incompatible* change to the public API — a
  consumer's working code can break. Removed symbols, removed or reordered
  parameters, lost defaults, sync/async flips, removed base classes.
- **Minor** (§7): new backward *compatible* functionality in the public
  API — something new a consumer can adopt, with nothing breaking. New
  symbols, new optional parameters, new `*args`/`**kwargs`, added bases.

If a change cannot break or extend an `import`-consumer's code, it is not
major and it is not minor. There are no exceptions for things that feel
important (dependencies, console scripts, supported Pythons): importance is
not incompatibility.

## 3. Everything else that ships is patch — at most

SemVer §3: a released version's contents must never change; any change ships
as a new version. §6 gives patch to backward compatible internal changes.
semverer generalizes: **if the shipped tree changed but the public API did
not, the release is a patch.** That covers implementation bodies, private
modules, comments and formatting, docs, data files, CI and build config,
dependency constraints, entry points, and the rest of the install contract.
A robot cannot tell a bug fix from a refactor — but both are "the artifact
changed, the contract didn't," and that is patch by definition.

## 4. If nothing changed, nothing bumps

The inverse of §3. semverer never bumps on a no-op, and never re-bumps a
version a human already raised far enough.

## 5. Unstable versions relax; they never tighten

§4: under 0.y.z anything may change. semverer demotes severity one level on
0.x (major→minor, minor→patch) and never auto-increments the leading zero —
reaching 1.0.0 *defines* the public API (§5) and is a human declaration, not
a robot's. Stable `>=1.0.0` versions get the full rules.

Pre-release, post, and dev suffixes are read as their **base** release and
bumps always land on a real version: `1.4.3rc1` means base `1.4.3`, so a
patch goes to `1.4.4` and a breaking change to `2.0.0`. semverer never
iterates candidate counters; release-candidate mechanics belong to release
managers, not version arithmetic.

## 6. The repository is not the package

semverer versions **the package a consumer imports**, not the git tree that
hosts it. File moves, directory restructures, and tooling churn matter only
through their effect on the shipped contents (patch) or the import surface
(major/minor via the API diff). semverer does not model file renames, history
shapes, or repository plumbing as version events in their own right.

## 7. Audit verifies; it never redefines

`semverer audit` replays the *same* rules over history as `check`/`update`
apply to the working tree — nothing more. It reads history through the
current layout; when it cannot see a ref's package it says so and skips
loudly, and a run that evaluates nothing **fails** rather than passing
vacuously. Audit is a verification convenience, not the product, and no
feature of audit may add severity rules the live commands don't have.

## 8. Prefer the simple rule

A severity decision must be explainable in one sentence that points at one
principle. When two designs detect the same thing, the one with less
machinery wins.

## 9. Bounded scope over best-effort guessing

semverer requires what it can verify and refuses what it can't, with
guidance instead of guesses:

- **Versions must resolve to MAJOR.MINOR.PATCH.** Short releases are moved
  onto the spec (`1.4` → `1.4.0`); epochs and 4+-component releases exit
  gracefully with a message to comply with semver first.
- **A package is something with a `pyproject.toml`.** That file is the
  scope marker; only packages that have one get versioned.
- **Discovery looks at the top level and exactly one level deep — never
  further.** Deeper or unconventional layouts must be named explicitly
  (`members`, a path argument, or `--pyproject`); when nothing is found,
  the user is told to specify the project, not guessed at.

Scope grows only by deliberate decision, never by accreting edge cases.

---

## The rules, derived

| Change | Bump | Principle |
|---|---|---|
| Public symbol/module removed; signature broken | **major** | 2 |
| New public symbol; optional parameter added | **minor** | 2 |
| Implementation changed, API identical | patch | 3 |
| Comments, formatting, docs, data, CI, build config | patch | 3 |
| Dependencies, entry points, extras, requires-python, name | patch | 1, 3 |
| Nothing changed | none | 4 |
| Any of the above on 0.x | one level relaxed | 5 |
| Any of the above on a pre-release (`1.4.3rc1`) | applied to the base (`1.4.3`) | 5 |
| Version can't resolve to MAJOR.MINOR.PATCH | graceful exit with guidance | 9 |
