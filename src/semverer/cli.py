"""Command line interface: check, update, and init."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import semver
import typer
from tomlkit import TOMLDocument

from semverer import skill, storage
from semverer.audit import AuditError, audit_repository
from semverer.comparator import compare
from semverer.extractor import extract_package, running_python
from semverer.models import Change, Severity
from semverer.storage import Baseline
from semverer.versioning import next_version

app = typer.Typer(no_args_is_help=True, add_completion=False)

skill_app = typer.Typer(no_args_is_help=True, help="Manage the Claude Code skill.")
app.add_typer(skill_app, name="skill")

SEVERITY_LABEL = {
    Severity.MAJOR: "major",
    Severity.MINOR: "minor",
    Severity.PATCH: "patch",
    Severity.NONE: "none",
}


@dataclass
class ProjectContext:
    pyproject: Path
    doc: TOMLDocument
    version: str
    package_dir: Path


def _fail(message: str) -> typer.Exit:
    typer.echo(f"semverer: error: {message}")
    return typer.Exit(2)


def _require_semver(version: str, what: str, hint: str = "") -> None:
    try:
        semver.Version.parse(version)
    except ValueError:
        raise _fail(
            f"{what} {version!r} is not a valid semantic version (expected MAJOR.MINOR.PATCH){hint}"
        ) from None


def _extract(context: ProjectContext) -> tuple[dict[str, str], dict[str, str]]:
    try:
        return extract_package(context.package_dir)
    except SyntaxError as error:
        raise _fail(f"cannot parse {error.filename}, line {error.lineno}: {error.msg}") from None


def _resolve(package_path: str | None, pyproject_option: Path | None) -> ProjectContext:
    pyproject = pyproject_option or storage.find_pyproject(Path.cwd())
    if pyproject is None or not pyproject.is_file():
        raise _fail("no pyproject.toml found")
    doc = storage.load(pyproject)
    version = storage.read_version(doc)
    if version is None:
        if "version" in doc.get("project", {}).get("dynamic", []):
            raise _fail(
                "dynamic [project] version is not supported; semverer needs a "
                "literal version field it can read and update"
            )
        raise _fail(f"no [project] version in {pyproject}")
    _require_semver(version, "project version")

    root = pyproject.parent
    if package_path is not None:
        package_dir = (root / package_path).resolve()
        if not package_dir.is_dir():
            raise _fail(f"package directory not found: {package_path}")
        return ProjectContext(pyproject, doc, version, package_dir)

    configured = storage.read_package_config(doc)
    if configured is not None:
        package_dir = (root / configured).resolve()
        if not package_dir.is_dir():
            raise _fail(f"[tool.semverer] package directory not found: {configured}")
        return ProjectContext(pyproject, doc, version, package_dir)

    name = str(doc.get("project", {}).get("name", "")).replace("-", "_")
    for candidate in (root / "src" / name, root / name):
        if name and candidate.is_dir():
            return ProjectContext(pyproject, doc, version, candidate)
    raise _fail("could not locate the package; set [tool.semverer] package or pass a path argument")


def _note_python_mismatch(baseline: Baseline, changes: list[Change]) -> None:
    """Flag patch findings whose hashes were written by a different Python.

    Structural hashing (see extractor.hash_module) is designed to be
    version-stable, so cross-version patch detection normally just works.
    This note exists for the unguaranteed case — a future minor changing AST
    shape for existing syntax — so that if it ever happens, the user sees why
    the patch findings might be spurious instead of getting silent bumps.
    """
    if baseline.python is None or baseline.python == running_python():
        return
    if not any(change.severity is Severity.PATCH for change in changes):
        return
    typer.echo(
        f"semverer: note: the baseline was hashed by Python {baseline.python}, which "
        f"differs from the running Python {running_python()}; if the patch-level "
        "changes below look spurious, re-run 'semverer init' under the project's "
        "pinned Python"
    )


def _print_changes(changes: list[Change]) -> None:
    for change in sorted(changes, key=lambda c: (-c.severity, c.key)):
        typer.echo(f"  [{SEVERITY_LABEL[change.severity]}] {change.key}: {change.description}")


@app.command()
def check(
    package_path: str | None = typer.Argument(None, help="Package directory to scan."),
    pyproject: Path | None = typer.Option(None, help="Path to pyproject.toml."),
) -> None:
    """Report the required version bump without writing anything (CI gate)."""
    context = _resolve(package_path, pyproject)
    api, hashes = _extract(context)
    baseline = storage.read_baseline(context.doc)
    if baseline is None:
        typer.echo("semverer: no baseline found; run 'semverer init' to establish one")
        raise typer.Exit(1)

    changes = compare(baseline.api, api, baseline.hashes, hashes)
    if not changes:
        typer.echo(f"semverer: up to date (version {context.version})")
        raise typer.Exit(0)

    _note_python_mismatch(baseline, changes)
    required = max(change.severity for change in changes)
    _require_semver(baseline.version, "stored baseline version", hint="; re-run 'semverer init'")
    target = next_version(baseline.version, context.version, required)
    if target == context.version:
        typer.echo(
            f"semverer: baseline refresh needed; manual bump to {target} covers the "
            f"{SEVERITY_LABEL[required]} change(s)"
        )
    else:
        typer.echo(
            f"semverer: version bump required: {context.version} -> {target} "
            f"({SEVERITY_LABEL[required]})"
        )
    _print_changes(changes)
    raise typer.Exit(1)


@app.command()
def update(
    package_path: str | None = typer.Argument(None, help="Package directory to scan."),
    pyproject: Path | None = typer.Option(None, help="Path to pyproject.toml."),
) -> None:
    """Apply the required version bump and refresh the baseline (pre-commit hook)."""
    context = _resolve(package_path, pyproject)
    api, hashes = _extract(context)
    baseline = storage.read_baseline(context.doc)

    if baseline is None:
        storage.write_state(
            context.pyproject,
            context.doc,
            context.version,
            Baseline(context.version, api, hashes, python=running_python()),
        )
        typer.echo(
            f"semverer: Initialized baseline for version {context.version} "
            f"({len(api)} public symbols); stage pyproject.toml and retry the commit"
        )
        raise typer.Exit(1)

    changes = compare(baseline.api, api, baseline.hashes, hashes)
    if not changes:
        typer.echo(f"semverer: up to date (version {context.version})")
        raise typer.Exit(0)

    _note_python_mismatch(baseline, changes)
    required = max(change.severity for change in changes)
    _require_semver(baseline.version, "stored baseline version", hint="; re-run 'semverer init'")
    target = next_version(baseline.version, context.version, required)
    storage.write_state(
        context.pyproject,
        context.doc,
        target,
        Baseline(target, api, hashes, python=running_python()),
    )

    if target == context.version:
        typer.echo(
            f"semverer: manual bump to {target} covers the {SEVERITY_LABEL[required]} "
            "change(s); baseline refreshed"
        )
    else:
        typer.echo(
            f"semverer: version bump: {context.version} -> {target} ({SEVERITY_LABEL[required]})"
        )
    _print_changes(changes)
    typer.echo("semverer: pyproject.toml updated; stage it and retry the commit")
    raise typer.Exit(1)


@app.command()
def init(
    package_path: str | None = typer.Argument(None, help="Package directory to scan."),
    pyproject: Path | None = typer.Option(None, help="Path to pyproject.toml."),
) -> None:
    """Establish (or rewrite) the baseline for the current version, without bumping."""
    context = _resolve(package_path, pyproject)
    api, hashes = _extract(context)
    storage.write_state(
        context.pyproject,
        context.doc,
        context.version,
        Baseline(context.version, api, hashes, python=running_python()),
    )
    typer.echo(
        f"semverer: baseline established for version {context.version}: "
        f"{len(api)} public symbols across {len(hashes)} modules"
    )


@app.command()
def audit(
    since: str | None = typer.Option(
        None, "--since", help="Audit transitions starting from this ref (e.g. the adoption tag)."
    ),
    tags_only: bool = typer.Option(
        False, "--tags-only", help="Audit only semver release tags (v*) instead of every commit."
    ),
) -> None:
    """Verify the git history's recorded versions obey the semver rules."""
    try:
        reports = audit_repository(Path.cwd(), since=since, tags_only=tags_only)
    except AuditError as error:
        raise _fail(str(error)) from None

    for report in reports:
        typer.echo(f"  {report.old_ref}..{report.new_ref}: {report.line}")
    violations = sum(1 for report in reports if report.violation)
    skipped = sum(1 for report in reports if report.skipped)
    passed = len(reports) - violations - skipped
    if violations:
        typer.echo(f"semverer: audit failed: {violations} violation(s), {passed} OK")
        raise typer.Exit(1)
    typer.echo(f"semverer: audit passed ({passed} OK, {skipped} skipped)")


@skill_app.command("install")
def skill_install(
    user: bool = typer.Option(
        False, "--user", help="Install for the user (~/.claude/skills) instead of the project."
    ),
) -> None:
    """Install the Claude Code skill so Claude manages versions with semverer."""
    if user:
        base = Path.home()
    else:
        pyproject = storage.find_pyproject(Path.cwd())
        base = pyproject.parent if pyproject is not None else Path.cwd()
    path = skill.install(base)
    typer.echo(f"semverer: Claude skill installed at {path}")
