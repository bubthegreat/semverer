"""Content hashes for every tracked file in the project tree.

Any byte-level change to a tracked file is at least a patch: READMEs, docs,
data files, CI config — and comments or formatting in code — all move the
version. Two files are excluded because tracking them would make semverer
trigger itself: the project's own ``pyproject.toml`` (rewritten on every
bump; its packaging metadata is compared semantically by
:mod:`semverer.metadata` instead) and ``uv.lock`` (embeds the project's own
version). Common tool and artifact directories are skipped; anything else
can be tuned with ``[tool.semverer] exclude`` globs, or the scan can be
narrowed to the package directories with ``track_files = false``.

CRLF newlines are normalized away before hashing so checkouts that differ
only in git ``autocrlf`` settings produce identical baselines.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from fnmatch import fnmatch
from pathlib import Path

IGNORED_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".hypothesis",
        ".eggs",
    }
)

# Root-level files semverer (or its bump) rewrites; tracking them would
# self-trigger a patch on every run.
SELF_WRITTEN = ("pyproject.toml", "uv.lock")


def is_ignored(parts: Sequence[str]) -> bool:
    """Whether a root-relative path falls in a built-in ignored location."""
    if any(part in IGNORED_DIRS or part.endswith(".egg-info") for part in parts[:-1]):
        return True
    name = parts[-1]
    return name == ".coverage" or name.startswith(".coverage.")


def hash_files(
    root: Path,
    scopes: Iterable[Path] | None = None,
    exclude: Sequence[str] = (),
) -> dict[str, str]:
    """Hash every tracked file under ``root`` (or just ``scopes`` within it).

    Keys are root-relative posix paths; values are ``sha256:`` content hashes
    with CRLF normalized to LF. ``scopes`` narrows the walk to specific
    directories (the ``track_files = false`` mode); ``exclude`` is a sequence
    of fnmatch globs applied to the root-relative path.
    """
    root = root.resolve()
    bases = [root] if scopes is None else [Path(scope).resolve() for scope in scopes]
    hashes: dict[str, str] = {}
    for base in bases:
        for file in sorted(base.rglob("*")):
            try:
                if not file.is_file():
                    continue
                relative = file.relative_to(root)
                if is_ignored(relative.parts):
                    continue
                key = relative.as_posix()
                if key in SELF_WRITTEN:
                    continue
                if any(fnmatch(key, pattern) for pattern in exclude):
                    continue
                data = file.read_bytes()
            except OSError:
                continue  # unreadable special file; not project content
            normalized = data.replace(b"\r\n", b"\n")
            hashes[key] = "sha256:" + hashlib.sha256(normalized).hexdigest()
    return hashes
