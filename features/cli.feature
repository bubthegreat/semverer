Feature: Command line interface
  Three commands: "check" reports the required bump without writing anything
  (CI gate), "update" applies the bump and rewrites the baseline (pre-commit
  hook), and "init" establishes a baseline without bumping. Exit codes follow
  the pre-commit convention: 0 means nothing to do, 1 means action is needed
  or files were modified.

  Scenario: check reports a required bump without modifying anything
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
    And I run "semverer check"
    Then the project version remains "1.2.3"
    And the command exits with code 1
    And the output contains "1.2.3 -> 1.3.0"
    And the output contains "core.py::wave"

  Scenario: check passes when the API matches the baseline
    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    And a baseline has been established
    When I run "semverer check"
    Then the command exits with code 0
    And the output contains "up to date"

  Scenario: check without a baseline asks for init
    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    When I run "semverer check"
    Then the command exits with code 1
    And the output contains "semverer init"

  Scenario: update exits 1 when it modifies files so pre-commit can stop the commit
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
    Then the command exits with code 1
    And the output contains "1.2.3 -> 1.3.0"

  Scenario: update exits 0 when there is nothing to do
    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    And a baseline has been established
    When I run "semverer update"
    Then the command exits with code 0

  Scenario: init establishes the baseline and reports the API size
    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    When I run "semverer init"
    Then the command exits with code 0
    And the baseline records version "1.2.3"

  Scenario: the package path is read from tool configuration
    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    When I run "semverer init"
    Then the command exits with code 0

  Scenario: the package path is auto-detected from the project name when not configured
    Given a project at version "1.2.3" without semverer configuration
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    When I run "semverer init"
    Then the command exits with code 0
    And the baseline contains the signature "mypkg/core.py::greet" = "def greet(name)"

  Scenario: an explicit package path argument overrides configuration
    Given a project at version "1.2.3"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    When I run "semverer init src/mypkg"
    Then the command exits with code 0

  Scenario: a missing package directory is an error
    Given a project at version "1.2.3"
    When I run "semverer check src/nonexistent"
    Then the command exits with code 2
