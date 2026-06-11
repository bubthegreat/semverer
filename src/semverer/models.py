"""Data model for API signatures and detected changes."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Severity(enum.IntEnum):
    """Semver impact of a change, ordered so max() picks the required bump."""

    NONE = 0
    PATCH = 1
    MINOR = 2
    MAJOR = 3


class ParamKind(enum.Enum):
    POSITIONAL_ONLY = "positional-only"
    POSITIONAL_OR_KEYWORD = "positional-or-keyword"
    VAR_POSITIONAL = "var-positional"
    KEYWORD_ONLY = "keyword-only"
    VAR_KEYWORD = "var-keyword"


#: Kinds whose name is part of the public contract (callers may pass by keyword
#: or rely on position). Vararg/kwarg names are invisible to callers.
NAMED_KINDS = frozenset(
    {ParamKind.POSITIONAL_ONLY, ParamKind.POSITIONAL_OR_KEYWORD, ParamKind.KEYWORD_ONLY}
)

POSITIONAL_KINDS = frozenset({ParamKind.POSITIONAL_ONLY, ParamKind.POSITIONAL_OR_KEYWORD})


@dataclass(frozen=True)
class Param:
    name: str
    kind: ParamKind
    has_default: bool = False


@dataclass(frozen=True)
class FunctionSig:
    name: str
    params: tuple[Param, ...]
    is_async: bool = False

    @property
    def has_vararg(self) -> bool:
        return any(p.kind is ParamKind.VAR_POSITIONAL for p in self.params)

    @property
    def has_kwarg(self) -> bool:
        return any(p.kind is ParamKind.VAR_KEYWORD for p in self.params)


@dataclass(frozen=True)
class ClassSig:
    name: str
    bases: tuple[str, ...]


@dataclass(frozen=True)
class Change:
    """A single detected difference between baseline and current API."""

    severity: Severity
    key: str
    description: str

    @property
    def module(self) -> str:
        return self.key.split("::", 1)[0]
