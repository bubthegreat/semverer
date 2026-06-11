"""Automatic semver bumps for Python packages via AST-level API change detection."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("semverer")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0"
