Feature: What counts as public API
  Only the public surface of a package participates in major/minor decisions:
  top-level functions and classes, and the methods of public classes. Private
  names (single leading underscore) and nested functions are implementation
  detail — changing them is at most a patch. Dunder names are public API.

  Scenario: Private functions are not part of the public API
    Given a project at version "1.0.0"
    And a module "core.py" containing:
      """
      def greet(name): ...
      def _helper(): ...
      """
    And a baseline has been established
    When the module "core.py" is changed to:
      """
      def greet(name): ...
      def _helper(extra): ...
      """
    And I run "semverer update"
    Then the project version becomes "1.0.1"

  Scenario: Private methods are not part of the public API
    Given a project at version "1.0.0"
    And a module "core.py" containing:
      """
      class Engine:
          def start(self): ...
          def _warm_up(self): ...
      """
    And a baseline has been established
    When the module "core.py" is changed to:
      """
      class Engine:
          def start(self): ...
      """
    And I run "semverer update"
    Then the project version becomes "1.0.1"

  Scenario: Dunder methods are public API
    Given a project at version "1.0.0"
    And a module "core.py" containing:
      """
      class Engine:
          def __init__(self, fuel): ...
      """
    And a baseline has been established
    When the module "core.py" is changed to:
      """
      class Engine:
          def __init__(self, fuel, spark): ...
      """
    And I run "semverer update"
    Then the project version becomes "2.0.0"

  Scenario: Nested functions are invisible
    Given a project at version "1.0.0"
    And a module "core.py" containing:
      """
      def outer():
          def inner(): ...
          return inner
      """
    And a baseline has been established
    When the module "core.py" is changed to:
      """
      def outer():
          def inner(changed): ...
          return inner
      """
    And I run "semverer update"
    Then the project version becomes "1.0.1"

  Scenario: Changes in private modules are patch-level
    Given a project at version "1.0.0"
    And a module "_internal.py" containing:
      """
      def helper(): ...
      """
    And a baseline has been established
    When the module "_internal.py" is changed to:
      """
      def helper(extra): ...
      """
    And I run "semverer update"
    Then the project version becomes "1.0.1"

  Scenario: The package __init__ module is public API
    Given a project at version "1.0.0"
    And a module "__init__.py" containing:
      """
      def exported(): ...
      """
    And a baseline has been established
    When the module "__init__.py" is changed to:
      """
      def _hidden(): ...
      """
    And I run "semverer update"
    Then the project version becomes "2.0.0"

  Scenario: Modules in subpackages are scanned
    Given a project at version "1.0.0"
    And a module "sub/feature.py" containing:
      """
      def f(): ...
      """
    And a baseline has been established
    When the module "sub/feature.py" is changed to:
      """
      def f(arg): ...
      """
    And I run "semverer update"
    Then the project version becomes "2.0.0"
