---
name: create-pr
description: Create GitHub pull requests following team best practices - proper title format, description template, reviewers, labels, and linked issues
target: github_agent
---

# GitHub Pull Request Best Practices

Use this skill whenever creating or describing a pull request.

## PR Title Format

Follow this pattern: `<type>(<scope>): <short description>`

Types:
- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation only
- `style` - Code style (formatting, missing semicolons)
- `refactor` - Code change that neither fixes a bug nor adds a feature
- `test` - Adding or updating tests
- `chore` - Build process, dependencies

Examples:
- `feat(auth): add OAuth2 login support`
- `fix(api): handle null response from user service`
- `docs(readme): update installation instructions`

## PR Description Template

Always include these sections in your PR description:

```markdown
## Summary
Brief description of what this PR does and why.

## Changes
- List specific changes made
- Be specific: "Added user validation" not "Fixed stuff"

## Testing
- How was this tested?
- Any manual testing steps?

## Screenshots (if applicable)
Add screenshots for UI changes.

## Checklist
- [ ] Code follows project style guidelines
- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] All tests pass
```

## Reviewers

**Required reviewers based on scope:**

| Scope | Required Reviewers |
|-------|-------------------|
| API changes | 1 API + 1 Backend |
| Frontend changes | 1 Frontend |
| Database/Schema | 1 Backend + 1 DBA |
| Security | 1 Security |
| Documentation | 1 maintainer |
| Breaking changes | 2 maintainers |

## Labels

Apply appropriate labels:
- `bug`, `enhancement`, `feature`, `documentation`, `refactor`, `security`
- `needs-review`, `wip`, `blocked`
- Priority: `p0`, `p1`, `p2`, `p3`

## Linked Issues

- Link related issues using GitHub keywords: `Fixes #123`, `Closes #456`, `Relates to #789`
- Use `Draft` PR for work in progress

## Branch Naming

Follow: `<type>/<ticket-id>-<short-description>`

Examples:
- `feat/PROJ-123-user-login`
- `fix/PROJ-456-null-handling`
- `docs/PROJ-789-readme-update`
