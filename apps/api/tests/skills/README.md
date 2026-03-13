# Skills Tests

Tests for GitHub-based skill discovery (`app/agents/skills/github_discovery`). Skills are YAML-defined agent capabilities hosted in GitHub repos; these tests verify that the discovery client can list available skills from a repo and fetch individual skill definitions by name.

Requires a `GITHUB_TOKEN` environment variable. Tests are skipped when the token is absent. Set `EVAL_USER_ID` additionally to run full integration tests that also write skill metadata to MongoDB and VFS.
