Feature: Any change to the project tree requires at least a patch bump
  The importable surface is the only public API: it alone decides between
  major and minor. Everything else in the tree decides whether a patch is
  due. READMEs, docs, data files, CI config — and comments or formatting
  inside code — are all content-hashed into the baseline, so no commit that
  changes the project can ship without moving the version. The project's own
  pyproject.toml is excluded from hashing (semverer rewrites it on every
  bump); the packaging fields it declares are compared field-by-field
  instead, and any difference there is likewise a patch — dependencies,
  entry points, and supported Pythons are the artifact's guts, not its API.

  Scenario: Editing the README is a patch change
    Given a project at version "1.0.0"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    And a project file "README.md" containing "hello"
    And a baseline has been established
    When the project file "README.md" is changed to "hello, world"
    And I run "semverer update"
    Then the project version becomes "1.0.1"
    And the output contains "README.md"

  Scenario: Adding a documentation file is a patch change
    Given a project at version "1.0.0"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    And a baseline has been established
    When a project file "docs/guide.md" is added containing "guide"
    And I run "semverer update"
    Then the project version becomes "1.0.1"
    And the output contains "file added"

  Scenario: Deleting a tracked file is a patch change
    Given a project at version "1.0.0"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    And a project file "data/seed.csv" containing "a,b"
    And a baseline has been established
    When the project file "data/seed.csv" is deleted
    And I run "semverer update"
    Then the project version becomes "1.0.1"
    And the output contains "file removed"

  Scenario: Disabling file tracking narrows the scan to the package
    Given a project at version "1.0.0"
    And file tracking is disabled
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    And a project file "README.md" containing "hello"
    And a baseline has been established
    When the project file "README.md" is changed to "hello, world"
    And I run "semverer update"
    Then the project version remains "1.0.0"
    And the command exits with code 0

  Scenario: Excluded paths do not require a bump
    Given a project at version "1.0.0"
    And the semverer exclude patterns are "notes/*"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    And a project file "notes/scratch.md" containing "wip"
    And a baseline has been established
    When the project file "notes/scratch.md" is changed to "more wip"
    And I run "semverer update"
    Then the project version remains "1.0.0"
    And the command exits with code 0

  Scenario: Adding a runtime dependency is a patch change
    Given a project at version "1.0.0"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    And a baseline has been established
    When the dependency "requests>=2" is added to the project
    And I run "semverer update"
    Then the project version becomes "1.0.1"
    And the output contains "dependencies changed"

  Scenario: Changing requires-python is a patch change
    Given a project at version "1.0.0"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    And a baseline has been established
    When requires-python is set to ">=3.13"
    And I run "semverer update"
    Then the project version becomes "1.0.1"
    And the output contains "requires-python changed"

  Scenario: Removing a console script is a patch change, not a major one
    Given a project at version "1.0.0"
    And a module "core.py" containing:
      """
      def greet(name): ...
      """
    And the project declares a console script "mypkg" targeting "mypkg.core:main"
    And a baseline has been established
    When the console script "mypkg" is removed
    And I run "semverer update"
    Then the project version becomes "1.0.1"
    And the output contains "entry points changed"
