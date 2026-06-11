"""Edge-case coverage for AST extraction and canonical signature rendering."""

import ast
import textwrap

import pytest

from semverer.extractor import (
    extract_module_api,
    extract_package,
    hash_module,
    parse_signature,
)
from semverer.models import ClassSig, FunctionSig, ParamKind


def api_of(source: str) -> dict[str, str]:
    return extract_module_api(ast.parse(textwrap.dedent(source)))


class TestSignatureRendering:
    def test_plain_function(self):
        assert api_of("def greet(name): ...") == {"greet": "def greet(name)"}

    def test_defaults_are_normalized(self):
        api = api_of("def greet(name, punctuation='!'): ...")
        assert api == {"greet": "def greet(name, punctuation=...)"}

    def test_keyword_only(self):
        api = api_of("def run(path, *, dry_run=False, retries=3): ...")
        assert api == {"run": "def run(path, *, dry_run=..., retries=...)"}

    def test_keyword_only_without_default(self):
        api = api_of("def run(*, mode): ...")
        assert api == {"run": "def run(*, mode)"}

    def test_positional_only(self):
        api = api_of("def f(a, b, /, c): ...")
        assert api == {"f": "def f(a, b, /, c)"}

    def test_varargs_and_kwargs(self):
        api = api_of("def f(a, *args, **kwargs): ...")
        assert api == {"f": "def f(a, *args, **kwargs)"}

    def test_async_function(self):
        api = api_of("async def fetch(url, timeout=10): ...")
        assert api == {"fetch": "async def fetch(url, timeout=...)"}

    def test_class_without_bases(self):
        assert api_of("class Engine: ...") == {"Engine": "class Engine"}

    def test_class_with_bases(self):
        api = api_of("class Engine(Base, abc.ABC): ...")
        assert api == {"Engine": "class Engine(Base, abc.ABC)"}


class TestPublicApiSelection:
    def test_private_function_excluded(self):
        assert api_of("def _helper(): ...") == {}

    def test_private_class_excluded(self):
        assert api_of("class _Internal: ...") == {}

    def test_nested_functions_excluded(self):
        api = api_of(
            """
            def outer():
                def inner(): ...
            """
        )
        assert api == {"outer": "def outer()"}

    def test_methods_are_qualified_not_duplicated(self):
        api = api_of(
            """
            class Engine:
                def start(self): ...
                def _warm_up(self): ...
            """
        )
        assert api == {
            "Engine": "class Engine",
            "Engine.start": "def start(self)",
        }

    def test_dunder_methods_included(self):
        api = api_of(
            """
            class Engine:
                def __init__(self, fuel): ...
                def __mangled(self): ...
            """
        )
        assert "Engine.__init__" in api
        assert "Engine.__mangled" not in api

    def test_module_level_dunder_included(self):
        api = api_of("def __getattr__(name): ...")
        assert api == {"__getattr__": "def __getattr__(name)"}


class TestPackageScanning:
    def make_package(self, tmp_path, files: dict[str, str]):
        package = tmp_path / "mypkg"
        package.mkdir()
        for name, content in files.items():
            path = package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(content))
        return package

    def test_keys_are_relative_posix(self, tmp_path):
        package = self.make_package(tmp_path, {"core.py": "def go(): ..."})
        api, hashes = extract_package(package)
        assert api == {"mypkg/core.py::go": "def go()"}
        assert set(hashes) == {"mypkg/core.py"}

    def test_init_module_included(self, tmp_path):
        package = self.make_package(tmp_path, {"__init__.py": "def public(): ..."})
        api, _ = extract_package(package)
        assert api == {"mypkg/__init__.py::public": "def public()"}

    def test_private_module_hashed_but_not_in_api(self, tmp_path):
        package = self.make_package(tmp_path, {"_internal.py": "def helper(): ..."})
        api, hashes = extract_package(package)
        assert api == {}
        assert "mypkg/_internal.py" in hashes

    def test_subpackages_scanned(self, tmp_path):
        package = self.make_package(
            tmp_path, {"sub/__init__.py": "", "sub/feature.py": "def f(): ..."}
        )
        api, _ = extract_package(package)
        assert "mypkg/sub/feature.py::f" in api

    def test_bom_prefixed_file_parses(self, tmp_path):
        package = tmp_path / "mypkg"
        package.mkdir()
        (package / "core.py").write_bytes(b"\xef\xbb\xbfdef go(): ...\n")
        api, _ = extract_package(package)
        assert api == {"mypkg/core.py::go": "def go()"}

    def test_pycache_ignored(self, tmp_path):
        package = self.make_package(
            tmp_path,
            {"core.py": "def go(): ...", "__pycache__/junk.py": "def junk(): ..."},
        )
        api, hashes = extract_package(package)
        assert list(api) == ["mypkg/core.py::go"]
        assert list(hashes) == ["mypkg/core.py"]


class TestHashing:
    def test_comments_and_formatting_do_not_change_hash(self):
        a = ast.parse("def f(a):\n    return a + 1\n")
        b = ast.parse("# comment\ndef f(a):\n\n    return (a + 1)\n")
        assert hash_module(a) == hash_module(b)

    def test_body_change_changes_hash(self):
        a = ast.parse("def f(a):\n    return a + 1\n")
        b = ast.parse("def f(a):\n    return a + 2\n")
        assert hash_module(a) != hash_module(b)

    def test_string_quote_style_does_not_change_hash(self):
        a = ast.parse("""x = f"a{', '.join(y)}b"\n""")
        b = ast.parse("""x = f'a{", ".join(y)}b'\n""")
        assert hash_module(a) == hash_module(b)

    def test_fstring_content_change_changes_hash(self):
        a = ast.parse('x = f"a{y}"\n')
        b = ast.parse('x = f"b{y}"\n')
        assert hash_module(a) != hash_module(b)

    def test_redundant_parens_do_not_change_hash(self):
        a = ast.parse("x = (1, 2)\ny = a + b * c\n")
        b = ast.parse("x = 1, 2\ny = a + (b * c)\n")
        assert hash_module(a) == hash_module(b)

    def test_annotation_change_changes_hash(self):
        a = ast.parse("def f(a: int) -> str: ...")
        b = ast.parse("def f(a: str) -> int: ...")
        assert hash_module(a) != hash_module(b)

    def test_default_value_change_changes_hash(self):
        a = ast.parse("def f(a=1): ...")
        b = ast.parse("def f(a=2): ...")
        assert hash_module(a) != hash_module(b)


class TestParseSignature:
    @pytest.mark.parametrize(
        "canonical",
        [
            "def greet(name)",
            "def greet(name, punctuation=...)",
            "def f(a, b, /, c, *args, d, e=..., **kwargs)",
            "async def fetch(url, timeout=...)",
            "class Engine",
            "class Engine(Base, abc.ABC)",
        ],
    )
    def test_round_trip(self, canonical):
        sig = parse_signature(canonical)
        rendered = api_of(f"{canonical}: ...")
        assert rendered[sig.name] == canonical

    def test_structure(self):
        sig = parse_signature("def f(a, /, b, c=..., *args, d, **kwargs)")
        assert isinstance(sig, FunctionSig)
        kinds = {p.name: p.kind for p in sig.params}
        assert kinds["a"] is ParamKind.POSITIONAL_ONLY
        assert kinds["b"] is ParamKind.POSITIONAL_OR_KEYWORD
        assert kinds["args"] is ParamKind.VAR_POSITIONAL
        assert kinds["d"] is ParamKind.KEYWORD_ONLY
        assert kinds["kwargs"] is ParamKind.VAR_KEYWORD
        defaults = {p.name: p.has_default for p in sig.params}
        assert defaults == {
            "a": False,
            "b": False,
            "c": True,
            "args": False,
            "d": False,
            "kwargs": False,
        }

    def test_class_structure(self):
        sig = parse_signature("class Engine(Base)")
        assert sig == ClassSig(name="Engine", bases=("Base",))
