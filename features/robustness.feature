Feature: Robust handling of broken or unsupported input
  Anything a real repository can throw at semverer should produce a clear,
  actionable message and exit code 2 (configuration/usage error) — never a
  traceback, and never a half-written pyproject.toml.

  Scenario: A module that does not parse is reported, not a traceback
    Given a project at version "1.0.0"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    And a baseline has been established
    When the module "broken.py" is changed to:
      """
      def broken(:
      """
    And I run "semverer update"
    Then the command exits with code 2
    And the output contains "broken.py"
    And the project version remains "1.0.0"

  Scenario: A version that cannot resolve to semver is rejected with guidance
    Given a project at version "not.a.version"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    When I run "semverer init"
    Then the command exits with code 2
    And the output contains "does not follow the semver spec"

  Scenario: An epoch version is outside the semver spec
    Given a project at version "1!1.2.3"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    When I run "semverer init"
    Then the command exits with code 2
    And the output contains "does not follow the semver spec"

  Scenario: A two-component version is moved onto MAJOR.MINOR.PATCH at init
    Given a project at version "1.4"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    When I run "semverer init"
    Then the command exits with code 0
    And the project version becomes "1.4.0"

  Scenario: Dynamic versioning is named explicitly as unsupported
    Given a project with a dynamic version
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    When I run "semverer check"
    Then the command exits with code 2
    And the output contains "dynamic"

  Scenario: A corrupted baseline version suggests re-initializing
    Given a project at version "1.0.0"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    And a baseline has been established
    And the baseline version is corrupted to "garbage"
    When the module "core.py" is changed to:
      """
      def greet(name): ...
      def wave(): ...
      """
    And I run "semverer update"
    Then the command exits with code 2
    And the output contains "semverer init"
    And the project version remains "1.0.0"
