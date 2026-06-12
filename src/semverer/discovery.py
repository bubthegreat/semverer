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
    """Resolve ``root`` (or an explicit ``--pyproject``) into version targets."""
    pyproject = pyproject_option or storage.find_pyproject(root)
    if pyproject is None or not pyproject.is_file():
        raise DiscoveryError("no pyproject.toml found")
    doc = storage.load(pyproject)

    # An explicit path or pyproject forces the legacy single-target path,
    # bypassing members so existing single-package behavior is bit-for-bit.
    if package_path is not None or pyproject_option is not None:
        return [_resolve_one(pyproject, doc, package_path)]

    members = storage.read_members_config(doc)
    if members:
        if storage.read_packages_config(doc) or storage.read_package_config(doc) is not None:
            raise DiscoveryError(
                "[tool.semverer] members cannot be combined with package/packages on the same file"
            )
        return _discover_members(pyproject, members)

    return [_resolve_one(pyproject, doc, None)]


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
