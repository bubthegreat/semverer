"""Step definitions shared by every feature file."""

from __future__ import annotations

import sys

import tomlkit
from pytest_bdd import given, parsers, then, when

from tests.conftest import Project, make_project

# --- Given ------------------------------------------------------------------


@given(parsers.parse('a project at version "{version}"'), target_fixture="project")
def project_at_version(tmp_path, monkeypatch, version: str) -> Project:
    return make_project(tmp_path, monkeypatch, version, with_config=True)


@given(
    parsers.parse('a project at version "{version}" without semverer configuration'),
    target_fixture="project",
)
def project_without_config(tmp_path, monkeypatch, version: str) -> Project:
    return make_project(tmp_path, monkeypatch, version, with_config=False)


@given(parsers.parse('a module "{name}" containing:'))
def module_containing(project: Project, name: str, docstring: str):
    project.write_module(name, docstring)


@given(parsers.parse('a module "{name}" with source "{source}"'))
def module_with_source(project: Project, name: str, source: str):
    project.write_module(name, source + "\n")


@given("a baseline has been established")
def baseline_established(project: Project):
    result = project.run("init")
    assert result.exit_code == 0, result.output


@given("a project with a dynamic version", target_fixture="project")
def project_with_dynamic_version(tmp_path, monkeypatch) -> Project:
    return make_project(tmp_path, monkeypatch, dynamic=True)


@given("the baseline was hashed under a different Python version")
def baseline_under_different_python(project: Project):
    doc = project.read_pyproject()
    doc["tool"]["semverer"]["baseline"]["python"] = "0.0"
    project.pyproject.write_text(tomlkit.dumps(doc))


@given(parsers.parse('the baseline version is corrupted to "{value}"'))
def baseline_version_corrupted(project: Project, value: str):
    doc = project.read_pyproject()
    doc["tool"]["semverer"]["baseline"]["version"] = value
    project.pyproject.write_text(tomlkit.dumps(doc))


@given("an isolated user home", target_fixture="fake_home")
def isolated_user_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    return home


# --- When -------------------------------------------------------------------


@when(parsers.parse('the module "{name}" is changed to:'))
@when(parsers.parse('a module "{name}" is added containing:'))
def module_changed(project: Project, name: str, docstring: str):
    project.write_module(name, docstring)


@when(parsers.parse('the module "{name}" is changed to source "{source}"'))
def module_changed_to_source(project: Project, name: str, source: str):
    project.write_module(name, source + "\n")


@when(parsers.parse('the module "{name}" is deleted'))
def module_deleted(project: Project, name: str):
    (project.package_dir / name).unlink()


@when(parsers.parse('the project version is manually set to "{version}"'))
def version_manually_set(project: Project, version: str):
    project.set_version(version)


@when(parsers.parse('I run "semverer {args}"'))
def run_semverer(project: Project, args: str):
    project.run(args)


# --- Then -------------------------------------------------------------------


@then(parsers.parse('the project version becomes "{version}"'))
@then(parsers.parse('the project version remains "{version}"'))
def assert_version(project: Project, version: str):
    assert project.read_version() == version, project.result.output


@then(parsers.parse("the command exits with code {code:d}"))
def assert_exit_code(project: Project, code: int):
    assert project.result.exit_code == code, project.result.output


@then(parsers.parse('the output contains "{text}"'))
def assert_output_contains(project: Project, text: str):
    assert text in project.result.output, project.result.output


@then(parsers.parse('the baseline records version "{version}"'))
def assert_baseline_version(project: Project, version: str):
    baseline = project.read_baseline()
    assert baseline is not None, "no baseline stored"
    assert str(baseline["version"]) == version


@then(parsers.parse('the baseline contains the signature "{key}" = "{signature}"'))
def assert_baseline_signature(project: Project, key: str, signature: str):
    baseline = project.read_baseline()
    assert baseline is not None, "no baseline stored"
    assert str(baseline["api"][key]) == signature


@then("the pyproject comments are preserved")
def assert_comments_preserved(project: Project):
    text = project.pyproject.read_text()
    assert "# managed by mypkg maintainers" in text
    assert "# semverer configuration" in text


@then("the baseline records the running Python version")
def assert_baseline_python(project: Project):
    baseline = project.read_baseline()
    assert baseline is not None, "no baseline stored"
    expected = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert str(baseline["python"]) == expected


@then("the skill file exists in the project")
def assert_project_skill(project: Project):
    assert (project.root / ".claude" / "skills" / "semverer" / "SKILL.md").is_file()


@then("the skill file exists in the user home")
def assert_user_skill(fake_home):
    assert (fake_home / ".claude" / "skills" / "semverer" / "SKILL.md").is_file()
