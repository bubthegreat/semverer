"""Resolve a repository into the version targets semverer should manage.

A :class:`Target` is one independently-versioned unit: the ``pyproject.toml``
that owns its ``[project].version`` and baseline, plus one or more source
directories whose combined public API drives that one version. This unifies
three layouts behind a single ``discover`` call:

- **classic** — one package, auto-detected or ``[tool.semverer] package``;
- **Layout A** — several importable packages in one distribution sharing one
  version (``[tool.semverer] packages = [...]``);
- **Layout B** — a monorepo of independently-versioned members
  (``[tool.semverer] members = [...]``), each itself classic or Layout A.

A CLI path argument or ``--pyproject`` always means "this one pyproject, this
one directory", preserving the original single-package behavior exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tomlkit import TOMLDocument

from semverer import storage
from semverer.files import IGNORED_DIRS


class DiscoveryError(Exception):
    """The repository could not be resolved into version targets."""


@dataclass
class Target:
    name: str
    pyproject: Path
    root: Path
    package_dirs: list[Path]
    doc: TOMLDocument
    version: str


def discover(
    root: Path,
    *,
    pyproject_option: Path | None = None,
    package_path: str | None = None,
) -> list[Target]:
    """Resolve ``root`` (or an explicit ``--pyproject``) into version targets.

    Search depth is bounded by design: the top level, then exactly one
    directory level deeper (PRINCIPLES.md, bounded scope). Anything more
    nested must be named explicitly — via ``[tool.semverer] members``, a
    package path argument, or ``--pyproject``.
    """
    pyproject = pyproject_option or storage.find_pyproject(root)

    # An explicit path or pyproject forces the legacy single-target path,
    # bypassing members so existing single-package behavior is bit-for-bit.
    if package_path is not None or pyproject_option is not None:
        if pyproject is None or not pyproject.is_file():
            raise DiscoveryError("no pyproject.toml found")
        return [_resolve_one(pyproject, storage.load(pyproject), package_path)]

    if pyproject is None:
        return _discover_one_deep(root)
    doc = storage.load(pyproject)

    members = storage.read_members_config(doc)
    if members:
        if storage.read_packages_config(doc) or storage.read_package_config(doc) is not None:
            raise DiscoveryError(
                "[tool.semverer] members cannot be combined with package/packages on the same file"
            )
        return _discover_members(pyproject, members)

    if _is_tooling_only(doc):
        # A version-less pyproject (lint/format config only) is not a
        # package; look one level deeper before giving up.
        return _discover_one_deep(pyproject.parent)

    return [_resolve_one(pyproject, doc, None)]


def _is_tooling_only(doc: TOMLDocument) -> bool:
    """No version, no dynamic version, and no semverer package config."""
    return (
        storage.read_version(doc) is None
        and "version" not in doc.get("project", {}).get("dynamic", [])
        and storage.read_package_config(doc) is None
        and not storage.read_packages_config(doc)
    )


def _discover_one_deep(root: Path) -> list[Target]:
    """Find member projects exactly one directory level down — and no further.

    Only directories with their own ``pyproject.toml`` carrying a version
    count as clear packages; version-less ones (tooling config) are skipped.
    """
    targets: list[Target] = []
    for member_pyproject in sorted(root.glob("*/pyproject.toml")):
        if member_pyproject.parent.name in IGNORED_DIRS:
            continue
        member_doc = storage.load(member_pyproject)
        if storage.read_version(member_doc) is None:
            continue  # not a clear package
        targets.append(_resolve_one(member_pyproject, member_doc, None))
    if not targets:
        raise DiscoveryError(
            "no clear Python package found at the top level or one level deep; "
            "to use semverer here, specify the project: pass a package path or "
            "--pyproject, or list [tool.semverer] members in a root pyproject.toml"
        )
    return targets


def _discover_members(controlling: Path, members: list[str]) -> list[Target]:
    root = controlling.parent
    targets: list[Target] = []
    for member in members:
        member_pyproject = root / member / "pyproject.toml"
        if not member_pyproject.is_file():
            raise DiscoveryError(f"member {member!r} has no pyproject.toml at {member_pyproject}")
        member_doc = storage.load(member_pyproject)
        targets.append(_resolve_one(member_pyproject, member_doc, None))
    return targets


def _resolve_one(pyproject: Path, doc: TOMLDocument, package_path: str | None) -> Target:
    root = pyproject.parent
    version = _require_version(doc, pyproject)
    name = storage.read_name_config(doc) or _project_name(doc) or pyproject.parent.name
    package_dirs = _resolve_package_dirs(root, doc, package_path)
    return Target(
        name=name,
        pyproject=pyproject,
        root=root,
        package_dirs=package_dirs,
        doc=doc,
        version=version,
    )


def _require_version(doc: TOMLDocument, pyproject: Path) -> str:
    version = storage.read_version(doc)
    if version is not None:
        return version
    if "version" in doc.get("project", {}).get("dynamic", []):
        raise DiscoveryError(
            "dynamic [project] version is not supported; semverer needs a "
            "literal version field it can read and update"
        )
    raise DiscoveryError(f"no [project] version in {pyproject}")


def _project_name(doc: TOMLDocument) -> str:
    return storage.read_project_name(doc)


def _resolve_package_dirs(root: Path, doc: TOMLDocument, package_path: str | None) -> list[Path]:
    if package_path is not None:
        directory = (root / package_path).resolve()
        if not directory.is_dir():
            raise DiscoveryError(f"package directory not found: {package_path}")
        return [directory]

    packages = storage.read_packages_config(doc)
    package = storage.read_package_config(doc)
    if packages and package is not None:
        raise DiscoveryError("set either [tool.semverer] package or packages, not both")
    if packages:
        return [_require_dir(root, entry, "[tool.semverer] packages") for entry in packages]
    if package is not None:
        return [_require_dir(root, package, "[tool.semverer] package")]

    ident = _project_name(doc).replace("-", "_")
    for candidate in (root / "src" / ident, root / ident):
        if ident and candidate.is_dir():
            return [candidate]
    raise DiscoveryError(
        "could not locate the package; set [tool.semverer] package/packages or pass a path argument"
    )


def _require_dir(root: Path, entry: str, what: str) -> Path:
    directory = (root / entry).resolve()
    if not directory.is_dir():
        raise DiscoveryError(f"{what} directory not found: {entry}")
    return directory
