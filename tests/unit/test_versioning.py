"""PEP 440 bump arithmetic, including 0.x and pre-release relaxation.

The tables here are the executable form of the design's truth tables: every
row pins one (current, severity) -> next outcome or one transition severity.
"""

import pytest

from semverer.models import Severity
from semverer.versioning import (
    bump,
    manual_bump_severity,
    next_version,
    relaxed_required,
)

MAJOR, MINOR, PATCH, NONE = Severity.MAJOR, Severity.MINOR, Severity.PATCH, Severity.NONE


class TestBumpStable:
    @pytest.mark.parametrize(
        ("version", "severity", "expected"),
        [
            ("1.2.3", NONE, "1.2.3"),
            ("1.2.3", PATCH, "1.2.4"),
            ("1.2.3", MINOR, "1.3.0"),
            ("1.2.3", MAJOR, "2.0.0"),
            ("1", MAJOR, "2.0.0"),
            ("1.2", MINOR, "1.3.0"),
            ("1!1.2.3", MAJOR, "1!2.0.0"),
            ("1!1.2.3", PATCH, "1!1.2.4"),
            ("1.2.3.post1", PATCH, "1.2.4"),
            ("1.2.3.post1", MAJOR, "2.0.0"),
            ("1.2.3+abc", PATCH, "1.2.4"),
        ],
    )
    def test_bump(self, version, severity, expected):
        assert bump(version, severity) == expected


class TestBumpZeroX:
    @pytest.mark.parametrize(
        ("version", "severity", "expected"),
        [
            ("0.3.0", MAJOR, "0.4.0"),
            ("0.3.0", MINOR, "0.3.1"),
            ("0.3.0", PATCH, "0.3.1"),
            ("0.0.3", MAJOR, "0.1.0"),
            ("0.0.3", MINOR, "0.0.4"),
            ("0.0.3", PATCH, "0.0.4"),
            ("0.3.0+abc", MAJOR, "0.4.0"),
        ],
    )
    def test_bump(self, version, severity, expected):
        assert bump(version, severity) == expected


class TestBumpPrerelease:
    @pytest.mark.parametrize(
        ("version", "severity", "expected"),
        [
            ("1.2.3rc1", PATCH, "1.2.3rc2"),
            ("1.2.3rc1", MINOR, "1.2.3rc2"),
            ("1.2.3rc1", MAJOR, "1.2.3rc2"),
            ("1.2.3a1", MAJOR, "1.2.3a2"),
            ("1.2.3b4", MINOR, "1.2.3b5"),
            ("1.2.3.dev1", MAJOR, "1.2.3.dev2"),
            ("1.2.3rc1.dev2", MAJOR, "1.2.3rc1.dev3"),
            ("1.2.3rc1.post1", PATCH, "1.2.3rc2"),
            ("0.3.0rc1", MAJOR, "0.3.0rc2"),
        ],
    )
    def test_bump(self, version, severity, expected):
        # Pre-release relaxation wins over the 0.x rule (branch order matters).
        assert bump(version, severity) == expected


class TestTransitionSeverity:
    @pytest.mark.parametrize(
        ("old", "new", "expected"),
        [
            ("1.0.0", "2.0.0", MAJOR),
            ("1.0.0", "1.1.0", MINOR),
            ("1.0.0", "1.0.1", PATCH),
            ("1.0.0rc1", "1.0.0", PATCH),
            ("1.0.0rc1", "1.0.0rc2", PATCH),
            ("1.0.0.dev1", "1.0.0", PATCH),
            ("1.0.0", "1.0.0.post1", PATCH),
            ("0.3.0", "0.4.0", MINOR),
            ("1!1.0.0", "2!1.0.0", MAJOR),
            ("1.0.0", "1.0.0", NONE),
            ("2.0.0", "1.0.0", NONE),
        ],
    )
    def test_manual_bump_severity(self, old, new, expected):
        assert manual_bump_severity(old, new) is expected


class TestRelaxedRequired:
    @pytest.mark.parametrize(
        ("version", "required", "expected"),
        [
            ("1.2.3", MAJOR, MAJOR),
            ("0.3.0", MAJOR, MINOR),
            ("0.3.0", MINOR, PATCH),
            ("0.3.0", PATCH, PATCH),
            ("1.2.3rc1", MAJOR, PATCH),
            ("0.3.0rc1", MAJOR, PATCH),
            ("1.2.3", NONE, NONE),
        ],
    )
    def test_relaxed_required(self, version, required, expected):
        assert relaxed_required(version, required) is expected


class TestNextVersion:
    def test_no_change_keeps_version(self):
        assert next_version("1.2.3", "1.2.3", NONE) == "1.2.3"

    def test_applies_required_bump(self):
        assert next_version("1.2.3", "1.2.3", MINOR) == "1.3.0"

    def test_respects_sufficient_manual_bump(self):
        # Human already bumped minor; a detected patch needs nothing more.
        assert next_version("1.2.3", "1.3.0", PATCH) == "1.3.0"

    def test_insufficient_manual_bump_is_topped_up(self):
        assert next_version("1.2.3", "1.2.4", MAJOR) == "2.0.0"

    def test_respects_relaxed_manual_bump_on_zero_x(self):
        # Breaking change on 0.x only needs a minor; the human's 0.3.0->0.4.0 covers it.
        assert next_version("0.3.0", "0.4.0", MAJOR) == "0.4.0"
