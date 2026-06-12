"""Steps for file tracking and pyproject install-contract scenarios."""

from __future__ import annotations

import tomlkit
from pytest_bdd import given, parsers, scenarios, when

from tests.conftest import Project

scenarios("../../features/file_tracking.feature")


def _write_file(project: Project, name: str, content: str) -> None:
    path = project.root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n")


def _edit_pyproject(project: Project, mutate) -> None:
    doc = project.read_pyproject()
    mutate(doc)
    project.pyproject.write_text(tomlkit.dumps(doc))


@given(parsers.parse('a project file "{name}" containing "{content}"'))
@when(parsers.parse('a project file "{name}" is added containing "{content}"'))
@when(parsers.parse('the project file "{name}" is changed to "{content}"'))
def project_file(project: Project, name: str, content: str):
    _write_file(project, name, content)


@when(parsers.parse('the project file "{name}" is deleted'))
def project_file_deleted(project: Project, name: str):
    (project.root / name).unlink()


@given("file tracking is disabled")
def file_tracking_disabled(project: Project):
    _edit_pyproject(project, lambda doc: doc["tool"]["semverer"].update(track_files=False))


@given(parsers.parse('the semverer exclude patterns are "{pattern}"'))
def exclude_patterns(project: Project, pattern: str):
    _edit_pyproject(project, lambda doc: doc["tool"]["semverer"].update(exclude=[pattern]))


@when(parsers.parse('the dependency "{requirement}" is added to the project'))
def dependency_added(project: Project, requirement: str):
    def mutate(doc):
        doc["project"]["dependencies"] = [*doc["project"].get("dependencies", []), requirement]

    _edit_pyproject(project, mutate)


@when(parsers.parse('requires-python is set to "{specifier}"'))
def requires_python_set(project: Project, specifier: str):
    _edit_pyproject(project, lambda doc: doc["project"].update({"requires-python": specifier}))


@given(parsers.parse('the project declares a console script "{name}" targeting "{target}"'))
def console_script_declared(project: Project, name: str, target: str):
    _edit_pyproject(project, lambda doc: doc["project"].update({"scripts": {name: target}}))


@when(parsers.parse('the console script "{name}" is removed'))
def console_script_removed(project: Project, name: str):
    def mutate(doc):
        del doc["project"]["scripts"][name]

    _edit_pyproject(project, mutate)
