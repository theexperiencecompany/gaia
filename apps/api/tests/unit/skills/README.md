# Unit Tests — Skills

Tests for the skills registry (`app/agents/skills/`). Skills are reusable agent capabilities that can be discovered from GitHub repos and loaded into the agent at runtime.

Tests verify registry operations (register, lookup, list) and that skill metadata (name, description, source) is stored and returned correctly. GitHub API calls are mocked so these tests run offline.
