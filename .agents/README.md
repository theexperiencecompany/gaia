# .agents

Agent-related resources for Claude Code and other AI agents working in this repo.

## Structure

- **plans/** — Implementation plans created before executing multi-step tasks. Files are Markdown documents describing changes, rationale, and steps. Gitignored — local only.
- **skills/** — Installed Claude Code skills (agent workflows). Each subdirectory is a skill that extends Claude's capabilities with specialized knowledge or tool integrations.

## Usage

- Store new implementation plans in `plans/` before starting complex work.
- Skills in `skills/` are automatically available to Claude Code via the Skill tool.
- To install new skills, use the `find-skills` or `skill-creator` skill.
