"""Replay git history and verify recorded versions obey the semver rules.

For each pair of consecutive refs, both API snapshots are extracted straight
from git blobs (no checkouts) and compared with the same rules ``update``
uses. A version that moved less than the required severity is a violation;
moving more is allowed, consistent with how manual bumps are respected.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import semver
import tomlkit

from semverer.comparator import compare
from semverer.extractor import extract_sources
from semverer.models import Severity
from semverer.versioning import manual_bump_severity


class AuditError(Exception):
    """A problem with the repository itself, not with its history."""


@dataclass
class Snapshot:
    ref: str
    version: str | None = None
    api: dict[str, str] = field(default_factory=dict)
    hashes: dict[str, str] = field(default_factory=dict)
    error: str | None = None


@dataclass
class TransitionReport:
    old_ref: str
    new_ref: str
    line: str
    violation: bool = False
    skipped: bool = False


def audit_repository(
    start: Path, since: str | None = None, tags_only: bool = False
) -> list[TransitionReport]:
    root = _repo_root(start)
    refs = _tag_refs(root, since) if tags_only else _commit_refs(root, since)
    reports: list[TransitionReport] = []
    previous: Snapshot | None = None
    for ref in refs:
        snapshot = _snapshot_at(root, ref)
        if previous is not None:
            report = _evaluate(previous, snapshot)
            if report is not None:
                reports.append(report)
        previous = snapshot
    return reports


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AuditError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def _repo_root(start: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AuditError("not inside a git repository")
    return Path(result.stdout.strip())


def _commit_refs(root: Path, since: str | None) -> list[str]:
    ref_range = f"{since}..HEAD" if since else "HEAD"
    commits = _git(root, "rev-list", "--reverse", "--first-parent", ref_range).split()
    short = [_git(root, "rev-parse", "--short", commit).strip() for commit in commits]
    if since:
        return [since, *short]
    return short


def _tag_refs(root: Path, since: str | None) -> list[str]:
    tags: list[tuple[semver.Version, str]] = []
    for tag in _git(root, "tag", "--list", "v*").split():
        try:
            tags.append((semver.Version.parse(tag[1:]), tag))
        except ValueError:
            continue  # not a release tag
    ordered = [tag for _, tag in sorted(tags)]
    if since and since in ordered:
        ordered = ordered[ordered.index(since) :]
    return ordered


def _snapshot_at(root: Path, ref: str) -> Snapshot:
    try:
        pyproject = _git(root, "show", f"{ref}:pyproject.toml")
    except AuditError:
        return Snapshot(ref=ref, error="no pyproject.toml")
    doc = tomlkit.parse(pyproject)
    project = doc.get("project", {})
    version = project.get("version")
    package = _package_dir_at(root, ref, doc)
    if package is None:
        return Snapshot(ref=ref, version=version, error="package directory not found")

    parent = str(PurePosixPath(package).parent)
    prefix = "" if parent == "." else f"{parent}/"
    sources: dict[str, str] = {}
    for path in _git(root, "ls-tree", "-r", "--name-only", ref, "--", package).split():
        parts = PurePosixPath(path).parts
        if not path.endswith(".py"):
            continue
        if any(part == "__pycache__" or part.startswith(".") for part in parts[:-1]):
            continue
        sources[path.removeprefix(prefix)] = _git(root, "show", f"{ref}:{path}")
    try:
        api, hashes = extract_sources(sources)
    except SyntaxError as error:
        return Snapshot(ref=ref, version=version, error=f"unparseable source: {error.filename}")
    return Snapshot(ref=ref, version=version, api=api, hashes=hashes)


def _package_dir_at(root: Path, ref: str, doc: tomlkit.TOMLDocument) -> str | None:
    configured = doc.get("tool", {}).get("semverer", {}).get("package")
    candidates: list[str] = []
    if configured is not None:
        candidates.append(str(configured))
    name = str(doc.get("project", {}).get("name", "")).replace("-", "_")
    if name:
        candidates += [f"src/{name}", name]
    for candidate in candidates:
        if _git(root, "ls-tree", "-d", "--name-only", ref, "--", candidate).strip():
            return candidate
    return None


def _evaluate(old: Snapshot, new: Snapshot) -> TransitionReport | None:
    if old.error is not None or new.error is not None:
        reason = old.error if old.error is not None else new.error
        return TransitionReport(old.ref, new.ref, f"skipped: {reason}", skipped=True)

    changes = compare(old.api, new.api, old.hashes, new.hashes)
    required = max((change.severity for change in changes), default=Severity.NONE)
    if required is Severity.NONE and old.version == new.version:
        return None  # nothing happened; keep the report readable

    if old.version is None or new.version is None:
        return TransitionReport(old.ref, new.ref, "skipped: missing version", skipped=True)
    try:
        actual = manual_bump_severity(str(old.version), str(new.version))
    except ValueError:
        return TransitionReport(old.ref, new.ref, "skipped: invalid version", skipped=True)

    versions = f"version {old.version} -> {new.version}"
    if actual >= required:
        verdict = "OK" if actual == required else "OK (over-bumped)"
        return TransitionReport(
            old.ref, new.ref, f"required {required.name.lower()}, {versions}  {verdict}"
        )
    return TransitionReport(
        old.ref,
        new.ref,
        f"required {required.name.lower()}, {versions}  UNDER-BUMPED",
        violation=True,
    )
