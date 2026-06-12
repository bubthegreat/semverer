"""Version arithmetic: map change severity to the next project version.

Versions are PEP 440 (``packaging.version.Version``) — the scheme pip and PyPI
actually use — so pre-releases (``1.0.0rc1``), dev releases (``1.0.0.dev1``),
post releases, epochs (``1!1.0.0``) and local versions (``1.0.0+local``) all
parse. Two stability rules relax the bump so unstable projects behave the way
the wider ecosystem expects:

- **0.x** (``major == 0``): the leading zero never auto-increments. Severity is
  demoted one level (major→minor, minor→patch, patch→patch), the Cargo
  "left-most non-zero" convention.
- **pre-release / dev** (``Version.is_prerelease``): the base release is still
  being stabilized, so any change just advances the pre/dev counter
  (``rc1``→``rc2``); magnitude is ignored and only forward movement matters.

:func:`relaxed_required` is the single source of truth for both rules; ``bump``
and the history audit both consume it so they can never disagree.
"""

from __future__ import annotations

from packaging.version import Version

from semverer.models import Severity

_DEMOTE = {
    Severity.MAJOR: Severity.MINOR,
    Severity.MINOR: Severity.PATCH,
    Severity.PATCH: Severity.PATCH,
}


def relaxed_required(version: str, required: Severity) -> Severity:
    """The severity an unstable version actually needs to satisfy ``required``.

    Stable ``>=1.0`` releases need the full severity; 0.x releases get one
    level of demotion; pre-release/dev versions only ever need a counter
    advance (PATCH). ``NONE`` always stays ``NONE``.
    """
    if required is Severity.NONE:
        return Severity.NONE
    parsed = Version(version)
    if parsed.is_prerelease:
        return Severity.PATCH
    if parsed.major == 0:
        return _DEMOTE[required]
    return required


def bump(version: str, severity: Severity) -> str:
    """The next version after a change of the given severity.

    Relaxation (see module docstring) is applied here, so callers get the
    ecosystem-correct result without special-casing 0.x or pre-releases.
    """
    if severity is Severity.NONE:
        return version
    parsed = Version(version)
    if parsed.is_prerelease:
        return _bump_prerelease(parsed)
    return _bump_release(parsed, relaxed_required(version, severity))


def _bump_prerelease(parsed: Version) -> str:
    """Advance the least significant unstable counter of a pre/dev version.

    A ``dev`` segment is the lowest, so when present it is what moves (keeping
    any ``pre``/``post`` ahead of it). Otherwise the ``pre`` counter advances
    and a now-stale ``post`` is dropped. ``local`` is build-local and never
    carried across a bump.
    """
    if parsed.dev is not None:
        return _format_pep440(
            parsed.epoch, parsed.release, parsed.pre, parsed.post, parsed.dev + 1, None
        )
    assert parsed.pre is not None  # is_prerelease and dev is None ⇒ pre set
    label, number = parsed.pre
    return _format_pep440(parsed.epoch, parsed.release, (label, number + 1), None, None, None)


def _bump_release(parsed: Version, severity: Severity) -> str:
    """A clean release bump: drop every pre/post/dev/local segment."""
    major, minor, micro = parsed.major, parsed.minor, parsed.micro
    if severity is Severity.MAJOR:
        release = (major + 1, 0, 0)
    elif severity is Severity.MINOR:
        release = (major, minor + 1, 0)
    else:
        release = (major, minor, micro + 1)
    return _format_pep440(parsed.epoch, release, None, None, None, None)


def _format_pep440(
    epoch: int,
    release: tuple[int, ...],
    pre: tuple[str, int] | None,
    post: int | None,
    dev: int | None,
    local: str | None,
) -> str:
    """Assemble a canonical PEP 440 string from components.

    Re-parsing through :class:`Version` normalizes the result and fails loudly
    if a malformed combination was ever constructed.
    """
    text = f"{epoch}!" if epoch else ""
    text += ".".join(str(part) for part in release)
    if pre is not None:
        text += f"{pre[0]}{pre[1]}"
    if post is not None:
        text += f".post{post}"
    if dev is not None:
        text += f".dev{dev}"
    if local is not None:
        text += f"+{local}"
    return str(Version(text))


def manual_bump_severity(baseline_version: str, current_version: str) -> Severity:
    """The actual severity of the move from one version to another.

    Used both to respect a hand-made bump (was it already big enough?) and by
    the audit to measure how far a recorded version moved. A non-forward move
    is ``NONE``. Within the same base release any forward move (finishing a
    pre-release, a post/dev advance) counts as ``PATCH``.
    """
    baseline = Version(baseline_version)
    current = Version(current_version)
    if current <= baseline:
        return Severity.NONE
    if current.epoch != baseline.epoch or current.major > baseline.major:
        return Severity.MAJOR
    if current.minor > baseline.minor:
        return Severity.MINOR
    return Severity.PATCH


def next_version(baseline_version: str, current_version: str, required: Severity) -> str:
    """The version the project should carry after the detected changes.

    A hand-made bump at least as large as the (relaxed) required severity is
    respected rather than bumped again on top. Relaxation is keyed on the
    current version's stability, mirroring how the audit judges a transition.
    """
    if required is Severity.NONE:
        return current_version
    effective = relaxed_required(current_version, required)
    if manual_bump_severity(baseline_version, current_version) >= effective:
        return current_version
    return bump(current_version, required)
