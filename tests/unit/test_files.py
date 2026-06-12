"""Whole-tree content hashing: scope, ignores, excludes, normalization."""

from __future__ import annotations

from pathlib import Path

from semverer.files import hash_files


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class TestScope:
    def test_whole_tree_with_root_relative_keys(self, tmp_path):
        write(tmp_path / "README.md", "hi\n")
        write(tmp_path / "docs" / "guide.md", "guide\n")
        write(tmp_path / "src" / "pkg" / "__init__.py", "def f(): ...\n")
        hashes = hash_files(tmp_path)
        assert set(hashes) == {"README.md", "docs/guide.md", "src/pkg/__init__.py"}
        assert all(value.startswith("sha256:") for value in hashes.values())

    def test_scopes_limit_the_walk(self, tmp_path):
        write(tmp_path / "README.md", "hi\n")
        write(tmp_path / "src" / "pkg" / "__init__.py", "def f(): ...\n")
        hashes = hash_files(tmp_path, scopes=[tmp_path / "src" / "pkg"])
        assert set(hashes) == {"src/pkg/__init__.py"}


class TestExclusions:
    def test_builtin_directories_ignored(self, tmp_path):
        write(tmp_path / ".git" / "config", "x\n")
        write(tmp_path / "src" / "__pycache__" / "junk.pyc", "x\n")
        write(tmp_path / ".venv" / "lib" / "site.py", "x\n")
        write(tmp_path / "dist" / "pkg.whl", "x\n")
        write(tmp_path / "pkg.egg-info" / "PKG-INFO", "x\n")
        write(tmp_path / "kept.txt", "x\n")
        assert set(hash_files(tmp_path)) == {"kept.txt"}

    def test_self_written_root_files_excluded(self, tmp_path):
        write(tmp_path / "pyproject.toml", "[project]\n")
        write(tmp_path / "uv.lock", "lock\n")
        write(tmp_path / "kept.txt", "x\n")
        assert set(hash_files(tmp_path)) == {"kept.txt"}

    def test_nested_pyproject_is_tracked(self, tmp_path):
        # Only the target's own root pyproject self-rewrites; a fixture or
        # example pyproject deeper in the tree is ordinary content.
        write(tmp_path / "tests" / "fixtures" / "pyproject.toml", "[project]\n")
        assert set(hash_files(tmp_path)) == {"tests/fixtures/pyproject.toml"}

    def test_exclude_globs(self, tmp_path):
        write(tmp_path / "notes" / "scratch.md", "x\n")
        write(tmp_path / "kept.md", "x\n")
        hashes = hash_files(tmp_path, exclude=("notes/*",))
        assert set(hashes) == {"kept.md"}

    def test_coverage_artifacts_ignored(self, tmp_path):
        write(tmp_path / ".coverage", "db\n")
        write(tmp_path / ".coverage.host.123", "db\n")
        write(tmp_path / "kept.txt", "x\n")
        assert set(hash_files(tmp_path)) == {"kept.txt"}


class TestHashing:
    def test_content_change_changes_hash(self, tmp_path):
        write(tmp_path / "a.txt", "one\n")
        before = hash_files(tmp_path)["a.txt"]
        write(tmp_path / "a.txt", "two\n")
        assert hash_files(tmp_path)["a.txt"] != before

    def test_comment_change_in_python_changes_hash(self, tmp_path):
        write(tmp_path / "m.py", "def f(): ...\n")
        before = hash_files(tmp_path)["m.py"]
        write(tmp_path / "m.py", "# comment\ndef f(): ...\n")
        assert hash_files(tmp_path)["m.py"] != before

    def test_crlf_and_lf_hash_identically(self, tmp_path):
        (tmp_path / "a.txt").write_bytes(b"line\nline\n")
        lf = hash_files(tmp_path)["a.txt"]
        (tmp_path / "a.txt").write_bytes(b"line\r\nline\r\n")
        assert hash_files(tmp_path)["a.txt"] == lf
