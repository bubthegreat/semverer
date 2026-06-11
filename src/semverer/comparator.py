"""Compare two API snapshots and classify every difference by semver impact."""

from __future__ import annotations

from semverer.extractor import parse_signature
from semverer.models import (
    NAMED_KINDS,
    POSITIONAL_KINDS,
    Change,
    ClassSig,
    FunctionSig,
    Severity,
)


def compare(
    old_api: dict[str, str],
    new_api: dict[str, str],
    old_hashes: dict[str, str],
    new_hashes: dict[str, str],
    *,
    compare_hashes: bool = True,
) -> list[Change]:
    """Return all changes between baseline and current snapshots.

    The required version bump is the maximum severity across the result.

    ``compare_hashes=False`` disables hash-based patch detection, for callers
    that cannot trust the provenance of the stored hashes (they are stable
    across Python minors by design — see extractor.hash_module — but that
    cannot be guaranteed for interpreters newer than this code).
    """
    changes: list[Change] = []

    removed = old_api.keys() - new_api.keys()
    added = new_api.keys() - old_api.keys()

    for key in sorted(removed):
        parent = _parent_key(key)
        if parent in removed:
            continue  # the class removal already covers its methods
        changes.append(Change(Severity.MAJOR, key, f"removed ({old_api[key]})"))

    for key in sorted(added):
        parent = _parent_key(key)
        if parent in added:
            continue  # the class addition already covers its methods
        changes.append(Change(Severity.MINOR, key, f"added ({new_api[key]})"))

    for key in sorted(old_api.keys() & new_api.keys()):
        if old_api[key] == new_api[key]:
            continue
        severity, details = classify_signature_change(old_api[key], new_api[key])
        if severity is Severity.NONE:
            continue  # caller-invisible change (e.g. *args renamed); hash check below
        changes.append(Change(severity, key, "; ".join(details)))

    if not compare_hashes:
        return changes

    api_changed_modules = {change.module for change in changes}
    for module in sorted(old_hashes.keys() | new_hashes.keys()):
        if module in api_changed_modules:
            continue
        old_hash = old_hashes.get(module)
        new_hash = new_hashes.get(module)
        if old_hash == new_hash:
            continue
        if old_hash is None:
            description = "module added (no public API)"
        elif new_hash is None:
            description = "module removed (no public API)"
        else:
            description = "implementation changed (public API unchanged)"
        changes.append(Change(Severity.PATCH, module, description))

    return changes


def classify_signature_change(old: str, new: str) -> tuple[Severity, list[str]]:
    """Classify a same-symbol signature change per the severity rules."""
    old_sig = parse_signature(old)
    new_sig = parse_signature(new)

    if type(old_sig) is not type(new_sig):
        return Severity.MAJOR, [f"changed from ({old}) to ({new})"]
    if isinstance(old_sig, ClassSig):
        assert isinstance(new_sig, ClassSig)
        return _classify_class(old_sig, new_sig)
    assert isinstance(new_sig, FunctionSig)
    return _classify_function(old_sig, new_sig)


def _classify_function(old: FunctionSig, new: FunctionSig) -> tuple[Severity, list[str]]:
    severity = Severity.NONE
    details: list[str] = []

    def note(level: Severity, message: str) -> None:
        nonlocal severity
        severity = max(severity, level)
        details.append(message)

    if old.is_async != new.is_async:
        note(Severity.MAJOR, "sync/async changed")

    old_named = {p.name: p for p in old.params if p.kind in NAMED_KINDS}
    new_named = {p.name: p for p in new.params if p.kind in NAMED_KINDS}

    for name in sorted(old_named.keys() - new_named.keys()):
        note(Severity.MAJOR, f"parameter '{name}' removed")
    for name in sorted(new_named.keys() - old_named.keys()):
        if new_named[name].has_default:
            note(Severity.MINOR, f"optional parameter '{name}' added")
        else:
            note(Severity.MAJOR, f"required parameter '{name}' added")
    for name in sorted(old_named.keys() & new_named.keys()):
        old_param, new_param = old_named[name], new_named[name]
        if old_param.kind is not new_param.kind:
            note(
                Severity.MAJOR,
                f"parameter '{name}' changed from {old_param.kind.value} to {new_param.kind.value}",
            )
        if old_param.has_default and not new_param.has_default:
            note(Severity.MAJOR, f"parameter '{name}' lost its default (now required)")
        elif not old_param.has_default and new_param.has_default:
            note(Severity.MINOR, f"parameter '{name}' gained a default")

    common = old_named.keys() & new_named.keys()
    old_order = [p.name for p in old.params if p.kind in POSITIONAL_KINDS and p.name in common]
    new_order = [p.name for p in new.params if p.kind in POSITIONAL_KINDS and p.name in common]
    if old_order != new_order:
        note(Severity.MAJOR, "positional parameters reordered")

    if old.has_vararg and not new.has_vararg:
        note(Severity.MAJOR, "*args removed")
    elif new.has_vararg and not old.has_vararg:
        note(Severity.MINOR, "*args added")
    if old.has_kwarg and not new.has_kwarg:
        note(Severity.MAJOR, "**kwargs removed")
    elif new.has_kwarg and not old.has_kwarg:
        note(Severity.MINOR, "**kwargs added")

    return severity, details


def _classify_class(old: ClassSig, new: ClassSig) -> tuple[Severity, list[str]]:
    severity = Severity.NONE
    details: list[str] = []

    removed = set(old.bases) - set(new.bases)
    added = set(new.bases) - set(old.bases)
    if removed:
        severity = Severity.MAJOR
        details.append(f"base class(es) removed: {', '.join(sorted(removed))}")
    elif old.bases != new.bases and not added:
        severity = Severity.MAJOR  # same bases, new MRO
        details.append("base classes reordered")
    if added:
        severity = max(severity, Severity.MINOR)
        details.append(f"base class(es) added: {', '.join(sorted(added))}")

    return severity, details


def _parent_key(key: str) -> str | None:
    """For 'mod.py::Class.method' return 'mod.py::Class'; else None."""
    module, _, symbol = key.partition("::")
    if "." not in symbol:
        return None
    return f"{module}::{symbol.rsplit('.', 1)[0]}"
