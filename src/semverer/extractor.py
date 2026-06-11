"""Extract the public API of a package as canonical signature strings.

Canonical strings are valid Python signatures with every default value
replaced by ``...``, e.g. ``def update(path, *, dry_run=...)``. This keeps
them readable and diffable in pyproject.toml while letting them round-trip
through :func:`ast.parse` for structural comparison.
"""

from __future__ import annotations

import ast
import hashlib
import sys
from pathlib import Path

from semverer.models import ClassSig, FunctionSig, Param, ParamKind

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def extract_package(package_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Scan a package directory and return its ``(api, hashes)`` snapshot.

    ``api`` maps ``"module.py::Symbol"`` / ``"module.py::Class.method"`` keys to
    canonical signature strings. ``hashes`` maps every module (public or
    private) to a hash of its normalized AST, so implementation-only changes
    can still be detected as patch-level. Module keys are relative to the
    package's parent directory, in posix form, so baselines are portable.
    """
    package_path = package_path.resolve()
    root = package_path.parent
    api: dict[str, str] = {}
    hashes: dict[str, str] = {}

    for file in sorted(package_path.rglob("*.py")):
        relative_parts = file.relative_to(package_path).parts
        if any(part == "__pycache__" or part.startswith(".") for part in relative_parts[:-1]):
            continue
        module_key = file.relative_to(root).as_posix()
        # utf-8-sig: tolerate a BOM (some Windows editors add one); plain
        # utf-8 files decode identically under it.
        tree = ast.parse(file.read_text(encoding="utf-8-sig"), filename=str(file))
        hashes[module_key] = hash_module(tree)
        if file.name.startswith("_") and file.name != "__init__.py":
            continue
        for symbol, signature in extract_module_api(tree).items():
            api[f"{module_key}::{symbol}"] = signature

    return api, hashes


def hash_module(tree: ast.Module) -> str:
    """Hash of the module's code with comments/formatting normalized away.

    The hash covers a canonical structural serialization of the AST rather
    than ast.unparse text: the unparser's rendering rules differ between
    Python minor versions (e.g. 3.12 emits PEP 701 quote-reuse f-strings
    where 3.14 switches the outer quotes), so identical source can unparse
    to different text under different interpreters and produce phantom
    patch-level findings. Structure is what we actually care about, and it
    is far more stable across versions. The baseline still records
    :func:`running_python` so a residual cross-version drift (e.g. a future
    minor changing AST shape for existing syntax) can be flagged to the user
    instead of silently mis-bumping.
    """
    return "sha256:" + hashlib.sha256(_stable_dump(tree).encode("utf-8")).hexdigest()


def _stable_dump(node: object) -> str:
    """Serialize an AST so equal structure gives equal text across Pythons.

    Deviations from ast.dump, each in service of cross-version stability:
    - position attributes (lineno/col_offset/...) are never included;
    - fields that are None or empty lists are omitted, so a new optional
      field added in a future Python (like 3.12's type_params) hashes the
      same as the field not existing at all;
    - field names are emitted sorted, so reordering of _fields between
      versions cannot change the output.
    """
    if isinstance(node, ast.AST):
        parts = []
        for name in sorted(node._fields):
            value = getattr(node, name, None)
            if value is None or (isinstance(value, list) and not value):
                continue
            parts.append(f"{name}={_stable_dump(value)}")
        return f"{type(node).__name__}({', '.join(parts)})"
    if isinstance(node, list):
        return f"[{', '.join(_stable_dump(item) for item in node)}]"
    return repr(node)


def running_python() -> str:
    """The interpreter minor version that produced this process's hashes."""
    return f"{sys.version_info.major}.{sys.version_info.minor}"


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
