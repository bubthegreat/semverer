"""Replay git history and verify recorded versions obey the semver rules.

Audit verifies; it never redefines (see PRINCIPLES.md). For each pair of
consecutive refs it extracts both snapshots straight from git blobs (no
checkouts) and applies exactly the rules ``update`` uses: public API
signatures decide major/minor, tracked file contents and packaging metadata
decide patch. A version that moved less than the (relaxed) required severity
is a violation; moving more is allowed, consistent with how manual bumps are
respected; moving backwards is always a violation.

History is read through the *current* layout: the member list comes from the
working tree, and refs where a member's package cannot be found are skipped
loudly. Histories that predate the current layout should be audited from the
adoption point with ``--since``; the CLI fails a run that could not evaluate
a single transition rather than passing vacuously.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

import tomlkit
from packaging.version import InvalidVersion, Version
from tomlkit.exceptions import ParseError

from semverer import storage
from semverer.comparator import compare
from semverer.discovery import DiscoveryError, discover
from semverer.extractor import extract_sources
from semverer.files import SELF_WRITTEN, is_ignored
from semverer.metadata import ProjectMetadata, compare_metadata, read_metadata
from semverer.models import Severity
from semverer.storage import ConfigError
from semverer.versioning import manual_bump_severity, parse_semver, relaxed_required


class AuditError(Exception):
    """A problem with the repository itself, not with its history."""


@dataclass
class Member:
    """One independently-versioned unit, as the working tree defines it."""

    name: str
    pyproject: PurePosixPath  # repo-root-relative path to the owning pyproject.toml
    tag_pattern: str


@dataclass
class Snapshot:
    ref: str
    version: str | None = None
    api: dict[str, str] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    metadata: ProjectMetadata = field(default_factory=ProjectMetadata)
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
    members = _members(root)
    multi = len(members) > 1
    reports: list[TransitionReport] = []
    for member in members:
        label = f"[{member.name}] " if member.name and multi else ""
        if tags_only:
            refs = _tag_refs(root, member.tag_pattern.format(name=member.name), since)
        else:
            refs = _commit_refs(root, since)
        previous: Snapshot | None = None
        for ref in refs:
            snapshot = _snapshot_at(root, ref, member)
            if previous is not None:
                report = _evaluate(previous, snapshot, label)
                if report is not None:
                    reports.append(report)
            previous = snapshot
    return reports


def _members(root: Path) -> list[Member]:
    """The units to audit, from the working tree's current layout.

    Falls back to a single default member (root ``pyproject.toml``, ``v*``
    tags) when discovery can't resolve the tree — the audit should still run
    over history even if the current checkout is mid-edit.
    """
    try:
        targets = discover(root)
    except (DiscoveryError, ConfigError):
        return [Member(name="", pyproject=PurePosixPath("pyproject.toml"), tag_pattern="v*")]
    members: list[Member] = []
    for target in targets:
        subpath = PurePosixPath(target.pyproject.relative_to(root).as_posix())
        pattern = storage.read_tag_pattern(target.doc) or "v*"
        members.append(Member(name=target.name, pyproject=subpath, tag_pattern=pattern))
    return members


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


def _tag_refs(root: Path, rendered_pattern: str, since: str | None) -> list[str]:
    tags: list[tuple[Version, str]] = []
    for tag in _git(root, "tag", "--list", rendered_pattern).split():
        version = _tag_version(tag, rendered_pattern)
        if version is not None:
            tags.append((version, tag))
    ordered = [tag for _, tag in sorted(tags)]
    if since and since in ordered:
        ordered = ordered[ordered.index(since) :]
    return ordered


def _tag_version(tag: str, rendered_pattern: str) -> Version | None:
    """Parse the PEP 440 version out of a tag matching ``rendered_pattern``."""
    prefix, _, suffix = rendered_pattern.partition("*")
    if not (tag.startswith(prefix) and tag.endswith(suffix)):
        return None
    core = tag[len(prefix) : len(tag) - len(suffix) if suffix else None]
    try:
        return Version(core)
    except InvalidVersion:
        return None  # not a release tag


def _snapshot_at(root: Path, ref: str, member: Member) -> Snapshot:
    try:
        text = _git(root, "show", f"{ref}:{member.pyproject}")
    except AuditError:
        return Snapshot(ref=ref, error="no pyproject.toml")
    try:
        doc = tomlkit.parse(text)
    except ParseError as error:
        return Snapshot(ref=ref, error=f"bad pyproject.toml: {error}")
    version = storage.read_version(doc)
    member_dir = member.pyproject.parent
    try:
        package_dirs = _package_dirs_at(root, ref, doc, member_dir)
        exclude = storage.read_exclude(doc)
        track_files = storage.read_track_files(doc)
    except ConfigError as error:
        return Snapshot(ref=ref, version=version, error=str(error))
    if not package_dirs:
        return Snapshot(ref=ref, version=version, error="package directory not found")

    files = _files_at(root, ref, member_dir, package_dirs if not track_files else None, exclude)
    sources: dict[str, str] = {}
    for package in package_dirs:
        parent = str(PurePosixPath(package).parent)
        prefix = "" if parent == "." else f"{parent}/"
        for path in _git(root, "ls-tree", "-r", "--name-only", ref, "--", package).splitlines():
            parts = PurePosixPath(path).parts
            if not path.endswith(".py"):
                continue
            if any(part == "__pycache__" or part.startswith(".") for part in parts[:-1]):
                continue
            key = path.removeprefix(prefix)
            if key in sources:
                return Snapshot(ref=ref, version=version, error=f"duplicate module {key}")
            sources[key] = _git(root, "show", f"{ref}:{path}")
    try:
        api = extract_sources(sources)
    except SyntaxError as error:
        return Snapshot(ref=ref, version=version, error=f"unparseable source: {error.filename}")
    return Snapshot(ref=ref, version=version, api=api, files=files, metadata=read_metadata(doc))


def _files_at(
    root: Path,
    ref: str,
    member_dir: PurePosixPath,
    scopes: list[str] | None,
    exclude: list[str],
) -> dict[str, str]:
    """Tracked file hashes at ``ref``, keyed relative to the member directory.

    Git's own blob IDs serve as the hashes: the audit only ever compares
    ref against ref, so any scheme that is stable within the repository
    works, and blob IDs avoid reading every file's contents.
    """
    pathspec = [] if member_dir == PurePosixPath(".") else [str(member_dir)]
    prefix = "" if not pathspec else f"{member_dir}/"
    files: dict[str, str] = {}
    for line in _git(root, "ls-tree", "-r", ref, "--", *pathspec).splitlines():
        info, _, path = line.partition("\t")
        fields = info.split()
        if len(fields) != 3 or fields[1] != "blob":
            continue
        key = path.removeprefix(prefix)
        parts = PurePosixPath(key).parts
        if not parts or is_ignored(parts):
            continue
        if key in SELF_WRITTEN:
            continue
        if any(fnmatch(key, pattern) for pattern in exclude):
            continue
        if scopes is not None and not any(
            path == scope or path.startswith(f"{scope}/") for scope in scopes
        ):
            continue
        files[key] = f"blob:{fields[2]}"
    return files


def _package_dirs_at(
    root: Path, ref: str, doc: tomlkit.TOMLDocument, member_dir: PurePosixPath
) -> list[str]:
    """Resolve a member's source dirs at ``ref``, as repo-root-relative paths.

    ``packages`` (Layout A) contributes every configured dir that exists;
    a scalar ``package`` or auto-detection contributes the first match — the
    same precedence :mod:`semverer.discovery` applies to the working tree.
    """
    packages = storage.read_packages_config(doc)
    if packages:
        joined = (_join(member_dir, entry) for entry in packages)
        return [path for path in joined if _is_dir_at(root, ref, path)]

    package = storage.read_package_config(doc)
    if package is not None:
        path = _join(member_dir, package)
        return [path] if _is_dir_at(root, ref, path) else []

    name = storage.read_project_name(doc).replace("-", "_")
    for candidate in (f"src/{name}", name):
        path = _join(member_dir, candidate)
        if name and _is_dir_at(root, ref, path):
            return [path]
    return []


def _join(member_dir: PurePosixPath, entry: str) -> str:
    return entry if member_dir == PurePosixPath(".") else f"{member_dir}/{entry}"


def _is_dir_at(root: Path, ref: str, path: str) -> bool:
    return bool(_git(root, "ls-tree", "-d", "--name-only", ref, "--", path).strip())


def _evaluate(old: Snapshot, new: Snapshot, label: str = "") -> TransitionReport | None:
    if old.error is not None or new.error is not None:
        reason = old.error if old.error is not None else new.error
        return TransitionReport(old.ref, new.ref, f"{label}skipped: {reason}", skipped=True)

    changes = compare(old.api, new.api, old.files, new.files)
    changes += compare_metadata(old.metadata, new.metadata)
    required = max((change.severity for change in changes), default=Severity.NONE)
    if required is Severity.NONE and old.version == new.version:
        return None  # nothing happened; keep the report readable

    if old.version is None or new.version is None:
        return TransitionReport(old.ref, new.ref, f"{label}skipped: missing version", skipped=True)
    try:
        old_version = parse_semver(str(old.version))
        new_version = parse_semver(str(new.version))
    except ValueError:
        return TransitionReport(
            old.ref, new.ref, f"{label}skipped: non-semver version", skipped=True
        )

    versions = f"version {old.version} -> {new.version}"
    if new_version < old_version:
        return TransitionReport(
            old.ref, new.ref, f"{label}{versions}  WENT BACKWARDS", violation=True
        )

    # Relax the requirement the same way `update` would have, so a correct
    # 0.x or pre-release bump is not flagged as under-bumped.
    effective = relaxed_required(str(old.version), required)
    actual = manual_bump_severity(str(old.version), str(new.version))
    note = "" if effective == required else f" (relaxed to {effective.name.lower()})"
    if actual >= effective:
        verdict = "OK" if actual == effective else "OK (over-bumped)"
        return TransitionReport(
            old.ref,
            new.ref,
            f"{label}required {required.name.lower()}{note}, {versions}  {verdict}",
        )
    return TransitionReport(
        old.ref,
        new.ref,
        f"{label}required {required.name.lower()}{note}, {versions}  UNDER-BUMPED",
        violation=True,
    )
