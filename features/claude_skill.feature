Feature: Claude Code skill installation
  semverer ships an Agent Skill so Claude Code automatically knows to manage
  versions with semverer when working in a Python package. "semverer skill
  install" copies the skill into the project's .claude/skills directory (the
  default) or the user's ~/.claude/skills directory.

  Scenario: Install the skill into the project
    Given a project at version "1.2.3"
    When I run "semverer skill install"
    Then the command exits with code 0
    And the skill file exists in the project

  Scenario: Install the skill for the user
    Given a project at version "1.2.3"
    And an isolated user home
    When I run "semverer skill install --user"
    Then the command exits with code 0
    And the skill file exists in the user home

  Scenario: Reinstalling overwrites the existing skill
    Given a project at version "1.2.3"
    When I run "semverer skill install"
    And I run "semverer skill install"
    Then the command exits with code 0
    And the skill file exists in the project
