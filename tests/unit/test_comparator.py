"""Severity matrix coverage: every rule in the spec table has a test."""

from semverer.comparator import classify_signature_change, compare
from semverer.models import Severity

HASH_A = "sha256:aaa"
HASH_B = "sha256:bbb"


def severity_of(changes) -> Severity:
    return max((c.severity for c in changes), default=Severity.NONE)


class TestMajor:
    def test_symbol_removed(self):
        changes = compare({"m.py::f": "def f()"}, {}, {"m.py": HASH_A}, {"m.py": HASH_B})
        assert severity_of(changes) is Severity.MAJOR

    def test_required_param_added(self):
        severity, details = classify_signature_change("def f(a)", "def f(a, b)")
        assert severity is Severity.MAJOR
        assert "required parameter 'b' added" in details

    def test_param_removed(self):
        severity, _ = classify_signature_change("def f(a, b)", "def f(a)")
        assert severity is Severity.MAJOR

    def test_param_renamed(self):
        severity, _ = classify_signature_change("def f(a)", "def f(b)")
        assert severity is Severity.MAJOR

    def test_params_reordered(self):
        severity, details = classify_signature_change("def f(a, b)", "def f(b, a)")
        assert severity is Severity.MAJOR
        assert "positional parameters reordered" in details

    def test_default_removed(self):
        severity, _ = classify_signature_change("def f(a=...)", "def f(a)")
        assert severity is Severity.MAJOR

    def test_varargs_removed(self):
        severity, _ = classify_signature_change("def f(a, *args)", "def f(a)")
        assert severity is Severity.MAJOR

    def test_kwargs_removed(self):
        severity, _ = classify_signature_change("def f(a, **kw)", "def f(a)")
        assert severity is Severity.MAJOR

    def test_sync_to_async(self):
        severity, _ = classify_signature_change("def f(a)", "async def f(a)")
        assert severity is Severity.MAJOR

    def test_param_becomes_keyword_only(self):
        severity, _ = classify_signature_change("def f(a, b=...)", "def f(a, *, b=...)")
        assert severity is Severity.MAJOR

    def test_function_becomes_class(self):
        severity, _ = classify_signature_change("def f(a)", "class f")
        assert severity is Severity.MAJOR

    def test_base_class_removed(self):
        severity, _ = classify_signature_change("class C(Base)", "class C")
        assert severity is Severity.MAJOR

    def test_method_removed(self):
        changes = compare(
            {"m.py::C": "class C", "m.py::C.go": "def go(self)"},
            {"m.py::C": "class C"},
            {"m.py": HASH_A},
            {"m.py": HASH_B},
        )
        assert severity_of(changes) is Severity.MAJOR

    def test_class_removal_reported_once_not_per_method(self):
        changes = compare(
            {"m.py::C": "class C", "m.py::C.go": "def go(self)"},
            {},
            {"m.py": HASH_A},
            {"m.py": HASH_B},
        )
        assert [c.key for c in changes] == ["m.py::C"]


class TestMinor:
    def test_new_function(self):
        changes = compare({}, {"m.py::f": "def f()"}, {"m.py": HASH_A}, {"m.py": HASH_B})
        assert severity_of(changes) is Severity.MINOR

    def test_new_module_with_public_api(self):
        changes = compare({}, {"new.py::f": "def f()"}, {}, {"new.py": HASH_A})
        assert severity_of(changes) is Severity.MINOR

    def test_optional_param_added(self):
        severity, details = classify_signature_change("def f(a)", "def f(a, b=...)")
        assert severity is Severity.MINOR
        assert "optional parameter 'b' added" in details

    def test_keyword_only_with_default_added(self):
        severity, _ = classify_signature_change("def f(a)", "def f(a, *, b=...)")
        assert severity is Severity.MINOR

    def test_varargs_added(self):
        severity, _ = classify_signature_change("def f(a)", "def f(a, *args)")
        assert severity is Severity.MINOR

    def test_kwargs_added(self):
        severity, _ = classify_signature_change("def f(a)", "def f(a, **kw)")
        assert severity is Severity.MINOR

    def test_param_gains_default(self):
        severity, _ = classify_signature_change("def f(a, b)", "def f(a, b=...)")
        assert severity is Severity.MINOR

    def test_base_class_added(self):
        severity, _ = classify_signature_change("class C", "class C(Base)")
        assert severity is Severity.MINOR

    def test_new_class_reported_once_with_methods(self):
        changes = compare(
            {},
            {"m.py::C": "class C", "m.py::C.go": "def go(self)"},
            {},
            {"m.py": HASH_A},
        )
        assert [c.key for c in changes] == ["m.py::C"]
        assert severity_of(changes) is Severity.MINOR


class TestPatch:
    def test_body_change_with_same_api(self):
        changes = compare(
            {"m.py::f": "def f(a)"},
            {"m.py::f": "def f(a)"},
            {"m.py": HASH_A},
            {"m.py": HASH_B},
        )
        assert [c.severity for c in changes] == [Severity.PATCH]

    def test_private_module_change(self):
        changes = compare({}, {}, {"_internal.py": HASH_A}, {"_internal.py": HASH_B})
        assert [c.severity for c in changes] == [Severity.PATCH]

    def test_new_module_without_public_api(self):
        changes = compare({}, {}, {}, {"_internal.py": HASH_A})
        assert [c.severity for c in changes] == [Severity.PATCH]

    def test_varargs_rename_is_invisible_so_patch_via_hash(self):
        changes = compare(
            {"m.py::f": "def f(*args)"},
            {"m.py::f": "def f(*items)"},
            {"m.py": HASH_A},
            {"m.py": HASH_B},
        )
        assert [c.severity for c in changes] == [Severity.PATCH]


class TestNone:
    def test_identical_snapshots(self):
        api = {"m.py::f": "def f(a)"}
        hashes = {"m.py": HASH_A}
        assert compare(api, api, hashes, hashes) == []

    def test_keyword_only_reorder_is_no_change_beyond_patch(self):
        # kw-only order is invisible to callers; only the hash difference counts
        changes = compare(
            {"m.py::f": "def f(*, a=..., b=...)"},
            {"m.py::f": "def f(*, b=..., a=...)"},
            {"m.py": HASH_A},
            {"m.py": HASH_B},
        )
        assert [c.severity for c in changes] == [Severity.PATCH]


class TestMixedSeverity:
    def test_max_severity_wins(self):
        changes = compare(
            {"m.py::f": "def f()", "m.py::g": "def g()"},
            {"m.py::g": "def g()", "m.py::h": "def h()"},
            {"m.py": HASH_A},
            {"m.py": HASH_B},
        )
        assert severity_of(changes) is Severity.MAJOR
        keys = {c.key: c.severity for c in changes}
        assert keys["m.py::f"] is Severity.MAJOR
        assert keys["m.py::h"] is Severity.MINOR
