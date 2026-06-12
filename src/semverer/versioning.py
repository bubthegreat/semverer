"""Version arithmetic: map change severity to the next project version.

Versions are read with PEP 440 (what pip and PyPI speak) but must resolve to
the semver spec's MAJOR.MINOR.PATCH before semverer will manage them: short
releases are padded (``1.4`` -> ``1.4.0``), while epochs and releases with
more than three components are rejected with guidance — complying with
semver comes first (PRINCIPLES.md, bounded scope). Pre-release, post, and
dev suffixes are tolerated and read as their **base** release, so bumps
always land on a real version (``1.4.3rc1`` + patch -> ``1.4.4``); semverer
never iterates candidate counters.

One stability rule relaxes the bump: under 0.x (SemVer §4, initial
development) severity is demoted one level — major -> minor, minor -> patch —
and the leading zero never auto-increments, because declaring ``1.0.0`` is a
human act (§5). :func:`relaxed_required` is the single source of truth for
that rule; ``bump`` and the history audit both consume it so they can never
disagree.
"""

from __future__ import annotations

from packaging.version import Version

from semverer.models import Severity

_DEMOTE = {
    Severity.MAJOR: Severity.MINOR,
    Severity.MINOR: Severity.PATCH,
    Severity.PATCH: Severity.PATCH,
}


def parse_semver(version: str) -> Version:
    """Parse a version, requiring it to resolve to MAJOR.MINOR.PATCH.

    Raises ``ValueError`` when it cannot: unparseable text, an epoch (semver
    has no such concept), or a release with more than three components.
    """
    parsed = Version(version)  # InvalidVersion is a ValueError
    if parsed.epoch:
        raise ValueError(f"{version!r} has an epoch, which the semver spec does not define")
    if len(parsed.release) > 3:
        raise ValueError(f"{version!r} has more components than MAJOR.MINOR.PATCH")
    return parsed


def canonical(version: str) -> str:
    """Pad a plain short release out to MAJOR.MINOR.PATCH (``1.4`` -> ``1.4.0``).

    Versions carrying pre/post/dev/local suffixes are returned unchanged;
    their first bump lands on a padded base release anyway.
    """
    parsed = parse_semver(version)
    plain = not (parsed.is_prerelease or parsed.is_postrelease or parsed.local)
    if plain and len(parsed.release) < 3:
        return f"{parsed.major}.{parsed.minor}.{parsed.micro}"
    return version


def relaxed_required(version: str, required: Severity) -> Severity:
    """The severity a 0.x version actually needs to satisfy ``required``.

    Stable ``>=1.0`` releases need the full severity; 0.x releases get one
    level of demotion and the leading zero never auto-increments. ``NONE``
    always stays ``NONE``.
    """
    if required is Severity.NONE:
        return Severity.NONE
    if parse_semver(version).major == 0:
        return _DEMOTE[required]
    return required


def bump(version: str, severity: Severity) -> str:
    """The next version after a change of the given severity.

    The bump applies to the **base** release — a pre-release/post/dev suffix
    is read as the version it was heading for and then left behind — so the
    result is always a plain MAJOR.MINOR.PATCH. The 0.x relaxation (see
    module docstring) is applied here, so callers get the spec-correct
    result without special-casing.
    """
    if severity is Severity.NONE:
        return version
    parsed = parse_semver(version)
    effective = relaxed_required(version, severity)
    major, minor, micro = parsed.major, parsed.minor, parsed.micro
    if effective is Severity.MAJOR:
        return f"{major + 1}.0.0"
    if effective is Severity.MINOR:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{micro + 1}"


def manual_bump_severity(baseline_version: str, current_version: str) -> Severity:
    """The actual severity of the move from one version to another.

    Used both to respect a hand-made bump (was it already big enough?) and by
    the audit to measure how far a recorded version moved. A non-forward move
    is ``NONE``. Within the same base release any forward move (finishing a
    pre-release, a post/dev advance) counts as ``PATCH``.
    """
    baseline = parse_semver(baseline_version)
    current = parse_semver(current_version)
    if current <= baseline:
        return Severity.NONE
    if current.major > baseline.major:
        return Severity.MAJOR
    if current.minor > baseline.minor:
        return Severity.MINOR
    return Severity.PATCH


def next_version(baseline_version: str, current_version: str, required: Severity) -> str:
    """The version the project should carry after the detected changes.

    A hand-made bump at least as large as the (relaxed) required severity is
    respected rather than bumped again on top — including a hand-chosen
    pre-release like ``2.0.0rc1``, which semverer keeps rather than fights.
    """
    if required is Severity.NONE:
        return current_version
    effective = relaxed_required(current_version, required)
    if manual_bump_severity(baseline_version, current_version) >= effective:
        return current_version
    return bump(current_version, required)
