"""Command line interface: check, update, init, audit, skill."""

from __future__ import annotations

from pathlib import Path

import typer
from packaging.version import InvalidVersion, Version

from semverer import metadata, skill, storage
from semverer.audit import AuditError, audit_repository
from semverer.comparator import compare
from semverer.discovery import DiscoveryError, Target, discover
from semverer.extractor import DuplicateModuleError, extract_packages
from semverer.files import hash_files
from semverer.metadata import ProjectMetadata, compare_metadata
from semverer.models import Change, Severity
from semverer.storage import Baseline, ConfigError
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

# Per-target update outcomes, ordered so the command can pick the worst.
_CLEAN, _INITIALIZED, _BUMPED = 0, 1, 2


def _fail(message: str) -> typer.Exit:
    typer.echo(f"semverer: error: {message}")
    return typer.Exit(2)


def _require_semver(version: str, what: str, hint: str = "") -> None:
    try:
        Version(version)
    except InvalidVersion:
        raise _fail(
            f"{what} {version!r} is not a valid PEP 440 version "
            f"(e.g. 1.2.3, 1.2.3rc1, 1.2.3.post1){hint}"
        ) from None


def _targets(package_path: str | None, pyproject: Path | None, member: str | None) -> list[Target]:
    try:
        targets = discover(Path.cwd(), pyproject_option=pyproject, package_path=package_path)
    except (DiscoveryError, ConfigError) as error:
        raise _fail(str(error)) from None
    if member is None:
        return targets
    matched = [t for t in targets if member in (t.name, t.pyproject.parent.name)]
    if not matched:
        available = ", ".join(t.name for t in targets) or "none"
        raise _fail(f"no member matching {member!r} (available: {available})")
    return matched


def _snapshot(target: Target) -> tuple[dict[str, str], dict[str, str], ProjectMetadata]:
    """The target's current state: public API, tracked file hashes, metadata."""
    try:
        api = extract_packages(target.package_dirs)
    except SyntaxError as error:
        raise _fail(f"cannot parse {error.filename}, line {error.lineno}: {error.msg}") from None
    except DuplicateModuleError as error:
        raise _fail(str(error)) from None
    try:
        exclude = storage.read_exclude(target.doc)
        scopes = None if storage.read_track_files(target.doc) else target.package_dirs
    except ConfigError as error:
        raise _fail(str(error)) from None
    files = hash_files(target.root, scopes=scopes, exclude=exclude)
    return api, files, metadata.read_metadata(target.doc)


def _read_baseline(target: Target) -> Baseline | None:
    try:
        return storage.read_baseline(target.doc)
    except ConfigError as error:
        raise _fail(str(error)) from None


def _changes(
    baseline: Baseline, api: dict[str, str], files: dict[str, str], meta: ProjectMetadata
) -> list[Change]:
    return compare(baseline.api, api, baseline.files, files) + compare_metadata(
        baseline.metadata, meta
    )


def _print_changes(changes: list[Change]) -> None:
    for change in sorted(changes, key=lambda c: (-c.severity, c.key)):
        typer.echo(f"  [{SEVERITY_LABEL[change.severity]}] {change.key}: {change.description}")


def _check_target(target: Target, label: str) -> int:
    _require_semver(target.version, "project version")
    api, files, meta = _snapshot(target)
    baseline = _read_baseline(target)
    if baseline is None:
        typer.echo(f"semverer: {label}no baseline found; run 'semverer init' to establish one")
        return 1

    changes = _changes(baseline, api, files, meta)
    if not changes:
        typer.echo(f"semverer: {label}up to date (version {target.version})")
        return 0

    required = max(change.severity for change in changes)
    _require_semver(baseline.version, "stored baseline version", hint="; re-run 'semverer init'")
    target_version = next_version(baseline.version, target.version, required)
    if target_version == target.version:
        typer.echo(
            f"semverer: {label}baseline refresh needed; manual bump to {target_version} "
            f"covers the {SEVERITY_LABEL[required]} change(s)"
        )
    else:
        typer.echo(
            f"semverer: {label}version bump required: {target.version} -> {target_version} "
            f"({SEVERITY_LABEL[required]})"
        )
    _print_changes(changes)
    return 1


def _update_target(target: Target, label: str) -> int:
    _require_semver(target.version, "project version")
    api, files, meta = _snapshot(target)
    baseline = _read_baseline(target)

    if baseline is None:
        storage.write_state(
            target.pyproject,
            target.doc,
            target.version,
            Baseline(target.version, api, files, meta),
        )
        typer.echo(
            f"semverer: {label}Initialized baseline for version {target.version} "
            f"({len(api)} public symbols); stage pyproject.toml and retry the commit"
        )
        return _INITIALIZED

    changes = _changes(baseline, api, files, meta)
    if not changes:
        typer.echo(f"semverer: {label}up to date (version {target.version})")
        return _CLEAN

    required = max(change.severity for change in changes)
    _require_semver(baseline.version, "stored baseline version", hint="; re-run 'semverer init'")
    target_version = next_version(baseline.version, target.version, required)
    storage.write_state(
        target.pyproject,
        target.doc,
        target_version,
        Baseline(target_version, api, files, meta),
    )

    if target_version == target.version:
        typer.echo(
            f"semverer: {label}manual bump to {target_version} covers the "
            f"{SEVERITY_LABEL[required]} change(s); baseline refreshed"
        )
    else:
        typer.echo(
            f"semverer: {label}version bump: {target.version} -> {target_version} "
            f"({SEVERITY_LABEL[required]})"
        )
    _print_changes(changes)
    return _BUMPED


def _init_target(target: Target, label: str) -> None:
    _require_semver(target.version, "project version")
    api, files, meta = _snapshot(target)
    storage.write_state(
        target.pyproject,
        target.doc,
        target.version,
        Baseline(target.version, api, files, meta),
    )
    typer.echo(
        f"semverer: {label}baseline established for version {target.version}: "
        f"{len(api)} public symbols, {len(files)} files tracked"
    )


def _label(target: Target, multi: bool) -> str:
    return f"[{target.name}] " if multi else ""


@app.command()
def check(
    package_path: str | None = typer.Argument(None, help="Package directory to scan."),
    pyproject: Path | None = typer.Option(None, help="Path to pyproject.toml."),
    member: str | None = typer.Option(None, "--member", help="Limit to one monorepo member."),
) -> None:
    """Report the required version bump without writing anything (CI gate)."""
    targets = _targets(package_path, pyproject, member)
    multi = len(targets) > 1
    worst = 0
    for target in targets:
        worst = max(worst, _check_target(target, _label(target, multi)))
    raise typer.Exit(worst)


@app.command()
def update(
    package_path: str | None = typer.Argument(None, help="Package directory to scan."),
    pyproject: Path | None = typer.Option(None, help="Path to pyproject.toml."),
    member: str | None = typer.Option(None, "--member", help="Limit to one monorepo member."),
) -> None:
    """Apply the required version bump and refresh the baseline (pre-commit hook)."""
    targets = _targets(package_path, pyproject, member)
    multi = len(targets) > 1
    outcomes = [_update_target(target, _label(target, multi)) for target in targets]
    if any(outcome == _BUMPED for outcome in outcomes):
        typer.echo("semverer: pyproject.toml updated; stage it and retry the commit")
    if any(outcome != _CLEAN for outcome in outcomes):
        raise typer.Exit(1)


@app.command()
def init(
    package_path: str | None = typer.Argument(None, help="Package directory to scan."),
    pyproject: Path | None = typer.Option(None, help="Path to pyproject.toml."),
    member: str | None = typer.Option(None, "--member", help="Limit to one monorepo member."),
) -> None:
    """Establish (or rewrite) the baseline for the current version, without bumping."""
    targets = _targets(package_path, pyproject, member)
    multi = len(targets) > 1
    for target in targets:
        _init_target(target, _label(target, multi))


@app.command()
def audit(
    since: str | None = typer.Option(
        None, "--since", help="Audit transitions starting from this ref (e.g. the adoption tag)."
    ),
    tags_only: bool = typer.Option(
        False, "--tags-only", help="Audit only release tags instead of every commit."
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
    if not reports:
        typer.echo("semverer: nothing to audit (no transitions found)")
        return
    if passed == 0:
        typer.echo(
            f"semverer: audit could not evaluate any transition "
            f"({skipped} skipped); check the package layout at the skipped refs"
        )
        raise typer.Exit(1)
    typer.echo(f"semverer: audit passed ({passed} OK, {skipped} skipped)")


@skill_app.command("install")
def skill_install(
    project: bool = typer.Option(
        False,
        "--project",
        help="Install into this project's .claude/skills instead of your home directory.",
    ),
    user: bool = typer.Option(
        False, "--user", help="Install into ~/.claude/skills (the default; kept for compatibility)."
    ),
) -> None:
    """Install the Claude Code skill (defaults to ~/.claude/skills, for all projects)."""
    if project and user:
        raise _fail("pass either --project or --user, not both")
    if project:
        pyproject = storage.find_pyproject(Path.cwd())
        base = pyproject.parent if pyproject is not None else Path.cwd()
    else:
        base = Path.home()
    path = skill.install(base)
    typer.echo(f"semverer: Claude skill installed at {path}")
