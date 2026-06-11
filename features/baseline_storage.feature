Feature: Baseline storage in pyproject.toml
  The API baseline lives in the consumer's pyproject.toml under
  [tool.semverer.baseline] as flat, human-readable signature strings. Writes
  preserve the file's existing formatting and comments. The baseline records
  the version it was generated for, so hand-made version bumps can be
  reconciled instead of double-bumped.

  Scenario: The first update initializes the baseline without bumping
    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    When I run "semverer update"
    Then the project version remains "1.2.3"
    And the baseline records version "1.2.3"
    And the output contains "Initialized"
    And the command exits with code 1

  Scenario: The baseline stores canonical signature strings
    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      def greet(name, punctuation="!"): ...
      """
    When I run "semverer init"
    Then the baseline contains the signature "mypkg/core.py::greet" = "def greet(name, punctuation=...)"

  Scenario: Updates preserve pyproject formatting and comments
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
    Then the pyproject comments are preserved

  Scenario: A sufficient manual bump is respected instead of double-bumping
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
    And the project version is manually set to "1.3.0"
    And I run "semverer update"
    Then the project version remains "1.3.0"
    And the baseline records version "1.3.0"

  Scenario: An insufficient manual bump is corrected
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
    And the project version is manually set to "1.2.4"
    And I run "semverer update"
    Then the project version becomes "2.0.0"

  Scenario: A second update with no further changes does nothing
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
    And I run "semverer update"
    Then the project version remains "1.3.0"
    And the command exits with code 0
