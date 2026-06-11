Feature: Version bumping based on detected API changes
  semverer compares the package's current public API against the stored
  baseline and bumps the project version by the highest-severity change:
  breaking changes are major, compatible additions are minor, and
  implementation-only changes are patch.

  Scenario: Removing a public function is a major change
    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      def greet(name): ...
      def wave(): ...
      """
    And a baseline has been established
    When the module "core.py" is changed to:
      """
      def greet(name): ...
      """
    And I run "semverer update"
    Then the project version becomes "2.0.0"
    And the output contains "core.py::wave"

  Scenario: Adding a public function is a minor change
    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    And a baseline has been established
    When the module "core.py" is changed to:
      """
      def greet(name): ...
      def wave(): ...
      """
    And I run "semverer update"
    Then the project version becomes "1.3.0"

  Scenario: Adding an optional parameter is a minor change
    Given a project at version "1.2.0"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    And a baseline has been established
    When the module "core.py" is changed to:
      """
      def greet(name, punctuation="!"): ...
      """
    And I run "semverer update"
    Then the project version becomes "1.3.0"
    And the output contains "optional parameter 'punctuation' added"

  Scenario: Changing only a function body is a patch change
    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      def greet(name):
          return name
      """
    And a baseline has been established
    When the module "core.py" is changed to:
      """
      def greet(name):
          return name.title()
      """
    And I run "semverer update"
    Then the project version becomes "1.2.4"

  Scenario: Changing a type annotation is a patch change
    Annotations do not change runtime compatibility, so they are excluded
    from signature comparison (a future strict mode may treat them as API);
    they are still part of the implementation hash, so the change is not lost.

    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      def greet(name: str) -> str:
          return name
      """
    And a baseline has been established
    When the module "core.py" is changed to:
      """
      def greet(name: bytes) -> bytes:
          return name
      """
    And I run "semverer update"
    Then the project version becomes "1.2.4"

  Scenario: Changing a default value is a patch change
    Default presence is part of the signature; the default's value is
    implementation detail.

    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      def greet(name, punctuation="!"):
          return name + punctuation
      """
    And a baseline has been established
    When the module "core.py" is changed to:
      """
      def greet(name, punctuation="?"):
          return name + punctuation
      """
    And I run "semverer update"
    Then the project version becomes "1.2.4"

  Scenario: Comment and formatting changes require no bump
    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      def greet(name):
          return name
      """
    And a baseline has been established
    When the module "core.py" is changed to:
      """
      # now with a comment
      def greet(name):

          return (name)
      """
    And I run "semverer update"
    Then the project version remains "1.2.3"
    And the command exits with code 0

  Scenario: Adding a new module with public API is a minor change
    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    And a baseline has been established
    When a module "extras.py" is added containing:
      """
      def bonus(): ...
      """
    And I run "semverer update"
    Then the project version becomes "1.3.0"

  Scenario: Deleting a module that had public API is a major change
    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    And a module "extras.py" containing:
      """
      def bonus(): ...
      """
    And a baseline has been established
    When the module "extras.py" is deleted
    And I run "semverer update"
    Then the project version becomes "2.0.0"

  Scenario: The highest severity change wins
    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    And a baseline has been established
    When the module "core.py" is changed to:
      """
      def wave(): ...
      """
    And I run "semverer update"
    Then the project version becomes "2.0.0"

  Scenario: Removing a method from a public class is a major change
    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      class Engine:
          def start(self): ...
          def stop(self): ...
      """
    And a baseline has been established
    When the module "core.py" is changed to:
      """
      class Engine:
          def start(self): ...
      """
    And I run "semverer update"
    Then the project version becomes "2.0.0"

  Scenario: Adding a method to a public class is a minor change
    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      class Engine:
          def start(self): ...
      """
    And a baseline has been established
    When the module "core.py" is changed to:
      """
      class Engine:
          def start(self): ...
          def stop(self): ...
      """
    And I run "semverer update"
    Then the project version becomes "1.3.0"

  Scenario Outline: Signature change severity rules
    Given a project at version "1.0.0"
    And a module "api.py" with source "<before>"
    And a baseline has been established
    When the module "api.py" is changed to source "<after>"
    And I run "semverer update"
    Then the project version becomes "<version>"

    Examples: Breaking changes bump major
      | before                  | after                      | version |
      | def f(a): ...           | def f(a, b): ...           | 2.0.0   |
      | def f(a, b): ...        | def f(a): ...              | 2.0.0   |
      | def f(a): ...           | def f(b): ...              | 2.0.0   |
      | def f(a, b): ...        | def f(b, a): ...           | 2.0.0   |
      | def f(a=1): ...         | def f(a): ...              | 2.0.0   |
      | def f(a, *args): ...    | def f(a): ...              | 2.0.0   |
      | def f(a, **kw): ...     | def f(a): ...              | 2.0.0   |
      | def f(a): ...           | async def f(a): ...        | 2.0.0   |
      | def f(a, b=1): ...      | def f(a, *, b=1): ...      | 2.0.0   |
      | class C(Base): pass     | class C: pass              | 2.0.0   |

    Examples: Compatible additions bump minor
      | before                  | after                      | version |
      | def f(a): ...           | def f(a, b=1): ...         | 1.1.0   |
      | def f(a): ...           | def f(a, *, b=1): ...      | 1.1.0   |
      | def f(a): ...           | def f(a, *args): ...       | 1.1.0   |
      | def f(a): ...           | def f(a, **kw): ...        | 1.1.0   |
      | def f(a, b): ...        | def f(a, b=1): ...         | 1.1.0   |
      | class C: pass           | class C(Base): pass        | 1.1.0   |

    Examples: Implementation changes bump patch
      | before                  | after                      | version |
      | def f(a): return 1      | def f(a): return 2         | 1.0.1   |
      | def f(*args): return 1  | def f(*items): return 1    | 1.0.1   |
