Feature: Cross-Python hash stability
  Implementation hashes are computed from a canonical structural serialization
  of the AST — not from ast.unparse text, whose rendering rules differ between
  Python minor versions (e.g. f-string quoting changed with PEP 701 in 3.12).
  Structural hashes are designed to be stable across interpreters, so patch
  detection works even when the baseline was written by a different Python
  minor. The baseline still records the hashing interpreter; a mismatch is
  surfaced as an informational note since structural stability across not-yet-
  released Pythons cannot be guaranteed.

  Scenario: The baseline records the Python version used for hashing
    Given a project at version "1.0.0"
    And a module "core.py" containing:
      """
      def f(a): ...
      """
    When I run "semverer init"
    Then the baseline records the running Python version

  Scenario: Implementation changes are detected even under a different Python
    Given a project at version "1.0.0"
    And a module "core.py" containing:
      """
      def f(a):
          return 1
      """
    And a baseline has been established
    And the baseline was hashed under a different Python version
    When the module "core.py" is changed to:
      """
      def f(a):
          return 2
      """
    And I run "semverer update"
    Then the project version becomes "1.0.1"
    And the output contains "differs from the running Python"
    And the baseline records the running Python version

  Scenario: Unchanged code is clean under a different Python
    Given a project at version "1.0.0"
    And a module "core.py" containing:
      """
      def f(a):
          return 1
      """
    And a baseline has been established
    And the baseline was hashed under a different Python version
    When I run "semverer update"
    Then the project version remains "1.0.0"
    And the command exits with code 0

  Scenario: API changes are still detected under a different Python
    Given a project at version "1.0.0"
    And a module "core.py" containing:
      """
      def f(a): ...
      """
    And a baseline has been established
    And the baseline was hashed under a different Python version
    When the module "core.py" is changed to:
      """
      def f(a): ...
      def g(): ...
      """
    And I run "semverer update"
    Then the project version becomes "1.1.0"
    And the baseline records the running Python version
