"""Version arithmetic: map change severity to the next project version."""

from __future__ import annotations

import semver

from semverer.models import Severity


def bump(version: str, severity: Severity) -> str:
    parsed = semver.Version.parse(version)
    if severity is Severity.MAJOR:
        return str(parsed.bump_major())
    if severity is Severity.MINOR:
        return str(parsed.bump_minor())
    if severity is Severity.PATCH:
        return str(parsed.bump_patch())
    return version


def manual_bump_severity(baseline_version: str, current_version: str) -> Severity:
    """How far the version was hand-raised since the baseline was written."""
    baseline = semver.Version.parse(baseline_version)
    current = semver.Version.parse(current_version)
    if current.compare(str(baseline)) <= 0:
        return Severity.NONE
    if current.major > baseline.major:
        return Severity.MAJOR
    if current.minor > baseline.minor:
        return Severity.MINOR
    return Severity.PATCH


def next_version(baseline_version: str, current_version: str, required: Severity) -> str:
    """The version the project should carry after the detected changes.

    A hand-made bump at least as large as the required severity is respected
    rather than bumped again on top.
    """
    if required is Severity.NONE:
        return current_version
    if manual_bump_severity(baseline_version, current_version) >= required:
        return current_version
    return bump(current_version, required)
