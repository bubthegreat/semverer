Feature: Auditing version history against the semver rules
  "semverer audit" replays a repository's git history: for each pair of
  consecutive commits (or tags with --tags-only) it extracts both API
  snapshots from the git blobs, computes the required severity with the same
  rules the update command uses, and verifies the recorded version actually
  moved at least that far. Under-bumps are violations (exit 1); over-bumps
  are allowed and only noted, matching how manual bumps are respected
  elsewhere. This is also how semverer validates itself: a CI job audits the
  tool's own published tags.

  Scenario: A correctly bumped history passes
    Given a git-tracked project
    And a commit at version "1.0.0" with module "core.py":
      """
      def f(a): ...
      """
    And a commit at version "1.1.0" with module "core.py":
      """
      def f(a): ...
      def g(): ...
      """
    And a commit at version "2.0.0" with module "core.py":
      """
      def g(): ...
      """
    When I run "semverer audit"
    Then the command exits with code 0
    And the output contains "audit passed"

  Scenario: An under-bumped change is a violation
    Given a git-tracked project
    And a commit at version "1.0.0" with module "core.py":
      """
      def f(a): ...
      def g(): ...
      """
    And a commit at version "1.0.1" with module "core.py":
      """
      def f(a): ...
      """
    When I run "semverer audit"
    Then the command exits with code 1
    And the output contains "UNDER-BUMPED"
    And the output contains "required major"

  Scenario: An over-bump is allowed but noted
    Given a git-tracked project
    And a commit at version "1.0.0" with module "core.py":
      """
      def f(a):
          return 1
      """
    And a commit at version "2.0.0" with module "core.py":
      """
      def f(a):
          return 2
      """
    When I run "semverer audit"
    Then the command exits with code 0
    And the output contains "over-bumped"

  Scenario: A comment-only commit needs a patch bump like any other change
    Given a git-tracked project
    And a commit at version "1.0.0" with module "core.py":
      """
      def f(a): ...
      """
    And a commit at version "1.0.1" with module "core.py":
      """
      # only a comment was added
      def f(a): ...
      """
    When I run "semverer audit"
    Then the command exits with code 0
    And the output contains "audit passed"

  Scenario: Tags-only mode ignores untagged intermediate commits
    Given a git-tracked project
    And a commit at version "1.0.0" with module "core.py":
      """
      def f(a): ...
      """
    And the commit is tagged "v1.0.0"
    And a commit at version "1.0.0" with module "core.py":
      """
      def temporarily_broken(): ...
      """
    And a commit at version "1.1.0" with module "core.py":
      """
      def f(a): ...
      def g(): ...
      """
    And the commit is tagged "v1.1.0"
    When I run "semverer audit --tags-only"
    Then the command exits with code 0
    And the output contains "audit passed"

  Scenario: Auditing starts from the --since ref
    Given a git-tracked project
    And a commit at version "3.0.0" with module "core.py":
      """
      def old_mess(a, b, c): ...
      """
    And a commit at version "1.0.0" with module "core.py":
      """
      def f(a): ...
      """
    And the commit is tagged "adoption"
    And a commit at version "1.1.0" with module "core.py":
      """
      def f(a): ...
      def g(): ...
      """
    When I run "semverer audit --since adoption"
    Then the command exits with code 0
    And the output contains "audit passed"

  Scenario: A breaking change on a 0.x line only needs a minor bump
    Given a git-tracked project
    And a commit at version "0.3.0" with module "core.py":
      """
      def f(a): ...
      """
    And a commit at version "0.4.0" with module "core.py":
      """
      def f(a, b): ...
      """
    When I run "semverer audit"
    Then the command exits with code 0
    And the output contains "audit passed"
    And the output contains "relaxed to minor"

  Scenario: A 0.x line that under-bumps a breaking change is still a violation
    Given a git-tracked project
    And a commit at version "0.3.0" with module "core.py":
      """
      def f(a): ...
      def g(): ...
      """
    And a commit at version "0.3.1" with module "core.py":
      """
      def f(a): ...
      """
    When I run "semverer audit"
    Then the command exits with code 1
    And the output contains "UNDER-BUMPED"

  Scenario: A breaking change during a pre-release only advances the counter
    Given a git-tracked project
    And a commit at version "1.0.0rc1" with module "core.py":
      """
      def f(a): ...
      """
    And a commit at version "1.0.0rc2" with module "core.py":
      """
      def f(a, b): ...
      """
    When I run "semverer audit"
    Then the command exits with code 0
    And the output contains "audit passed"

  Scenario: A version that moves backwards is a violation
    Given a git-tracked project
    And a commit at version "2.0.0" with module "core.py":
      """
      def f(a): ...
      """
    And a commit at version "1.0.0" with module "core.py":
      """
      def f(a): ...
      """
    When I run "semverer audit"
    Then the command exits with code 1
    And the output contains "WENT BACKWARDS"

  Scenario: Outside a git repository the error is clear
    Given a project at version "1.0.0"
    And a module "core.py" containing:
      """
      def f(a): ...
      """
    When I run "semverer audit"
    Then the command exits with code 2
    And the output contains "git"
