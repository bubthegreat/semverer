"""Extract the public API of a package as canonical signature strings.

Canonical strings are valid Python signatures with every default value
replaced by ``...``, e.g. ``def update(path, *, dry_run=...)``. This keeps
them readable and diffable in pyproject.toml while letting them round-trip
through :func:`ast.parse` for structural comparison.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from semverer.models import ClassSig, FunctionSig, Param, ParamKind

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


class DuplicateModuleError(Exception):
    """Two scanned package directories map to the same module key.

    Keys are prefixed by the *leaf* directory name, so ``src/foo`` and
    ``vendored/foo`` would both yield ``foo/...`` keys and silently clobber
    each other. We refuse rather than drop symbols.
    """

    def __init__(self, key: str, first: Path, second: Path) -> None:
        self.key = key
        self.first = first
        self.second = second
        super().__init__(
            f"packages {first} and {second} both map to module {key!r}; "
            "rename one of them or use [tool.semverer] members for independent versioning"
        )


def extract_package(package_path: Path) -> dict[str, str]:
    """Scan one package directory and return its public API snapshot.

    Thin wrapper over :func:`extract_packages` for the single-directory case.
    """
    return extract_packages([package_path])


def extract_packages(package_paths: Iterable[Path]) -> dict[str, str]:
    """Scan several package directories into one public API snapshot.

    The result maps ``"module.py::Symbol"`` / ``"module.py::Class.method"``
    keys to canonical signature strings. Module keys are relative to each
    directory's *parent*, in posix form, so baselines are portable and several
    importable packages in one distribution union cleanly. Colliding keys
    across directories raise :class:`DuplicateModuleError`. Implementation
    changes are detected separately, by content-hashing the whole tree (see
    :mod:`semverer.files`).
    """
    sources: dict[str, str] = {}
    origin: dict[str, Path] = {}
    for package_path in package_paths:
        for module_key, text in _collect_sources(package_path).items():
            if module_key in sources:
                raise DuplicateModuleError(module_key, origin[module_key], package_path)
            sources[module_key] = text
            origin[module_key] = package_path
    return extract_sources(sources)


def _collect_sources(package_path: Path) -> dict[str, str]:
    """Read one package directory's ``.py`` files keyed parent-relative."""
    package_path = package_path.resolve()
    root = package_path.parent
    sources: dict[str, str] = {}
    for file in sorted(package_path.rglob("*.py")):
        relative_parts = file.relative_to(package_path).parts
        if any(part == "__pycache__" or part.startswith(".") for part in relative_parts[:-1]):
            continue
        module_key = file.relative_to(root).as_posix()
        # utf-8-sig: tolerate a BOM (some Windows editors add one); plain
        # utf-8 files decode identically under it.
        sources[module_key] = file.read_text(encoding="utf-8-sig")
    return sources


def extract_sources(sources: dict[str, str]) -> dict[str, str]:
    """Extract the public API from in-memory sources keyed by module key.

    This is the filesystem-free core of :func:`extract_package`; the audit
    command uses it to snapshot historical commits directly from git blobs
    without checking them out.
    """
    api: dict[str, str] = {}

    for module_key in sorted(sources):
        tree = ast.parse(sources[module_key], filename=module_key)
        name = module_key.rsplit("/", 1)[-1]
        if name.startswith("_") and name != "__init__.py":
            continue
        for symbol, signature in extract_module_api(tree).items():
            api[f"{module_key}::{symbol}"] = signature

    return api


def extract_module_api(tree: ast.Module) -> dict[str, str]:
    """Public symbols of a module: top-level defs/classes and class methods.

    Only direct children of the module/class body count — nested functions are
    implementation detail. ``_private`` names are excluded; dunders are not.
    """
    entries: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, FunctionNode) and is_public(node.name):
            entries[node.name] = render_function(node)
        elif isinstance(node, ast.ClassDef) and is_public(node.name):
            entries[node.name] = render_class(node)
            for child in node.body:
                if isinstance(child, FunctionNode) and is_public(child.name):
                    entries[f"{node.name}.{child.name}"] = render_function(child)
    return entries


def is_public(name: str) -> bool:
    """Dunders count as public API; single-underscore names do not."""
    if name.startswith("__") and name.endswith("__"):
        return True
    return not name.startswith("_")


def render_function(node: FunctionNode) -> str:
    args = node.args
    parts: list[str] = []

    positional = args.posonlyargs + args.args
    first_default = len(positional) - len(args.defaults)
    for index, arg in enumerate(positional):
        parts.append(arg.arg + ("=..." if index >= first_default else ""))
        if args.posonlyargs and index == len(args.posonlyargs) - 1:
            parts.append("/")

    if args.vararg is not None:
        parts.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        parts.append("*")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        parts.append(arg.arg + ("=..." if default is not None else ""))
    if args.kwarg is not None:
        parts.append("**" + args.kwarg.arg)

    keyword = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{keyword} {node.name}({', '.join(parts)})"


def render_class(node: ast.ClassDef) -> str:
    if not node.bases:
        return f"class {node.name}"
    return f"class {node.name}({', '.join(ast.unparse(base) for base in node.bases)})"


def parse_signature(text: str) -> FunctionSig | ClassSig:
    """Parse a canonical signature string back into its structured form."""
    node = ast.parse(f"{text}: ...").body[0]
    if isinstance(node, ast.ClassDef):
        return ClassSig(name=node.name, bases=tuple(ast.unparse(base) for base in node.bases))
    if isinstance(node, FunctionNode):
        return function_sig(node)
    raise ValueError(f"not a canonical signature: {text!r}")


def function_sig(node: FunctionNode) -> FunctionSig:
    args = node.args
    params: list[Param] = []

    positional = [(arg, ParamKind.POSITIONAL_ONLY) for arg in args.posonlyargs]
    positional += [(arg, ParamKind.POSITIONAL_OR_KEYWORD) for arg in args.args]
    first_default = len(positional) - len(args.defaults)
    for index, (arg, kind) in enumerate(positional):
        params.append(Param(arg.arg, kind, has_default=index >= first_default))

    if args.vararg is not None:
        params.append(Param(args.vararg.arg, ParamKind.VAR_POSITIONAL))
    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        params.append(Param(arg.arg, ParamKind.KEYWORD_ONLY, has_default=default is not None))
    if args.kwarg is not None:
        params.append(Param(args.kwarg.arg, ParamKind.VAR_KEYWORD))

    return FunctionSig(
        name=node.name,
        params=tuple(params),
        is_async=isinstance(node, ast.AsyncFunctionDef),
    )
