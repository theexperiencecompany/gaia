---
name: github-create-issue
description: Create GitHub issues with proper formatting, labels, and details.
target: github_agent
---

# GitHub Create Issue

## When to Use
- User asks to "create an issue"
- User asks to "file a bug report"
- User asks to "open a ticket"
- User describes a problem they want tracked
- User wants to suggest a feature or improvement

## Tools

### GITHUB_CREATE_ISSUE
Create a new issue in a GitHub repository.

**Required parameters:**
- `owner`: Repository owner (username or organization)
- `repo`: Repository name
- `title`: Issue title (clear, concise)

**Optional parameters:**
- `body`: Detailed description (supports Markdown)
- `labels`: Array of label names (e.g., ["bug", "high-priority"])
- `assignees`: Array of usernames to assign

### GITHUB_LIST_REPOS
List user's repositories (for finding the right repo).

**Useful for:**
- Finding which repo to create issue in
- Checking repo names

### GITHUB_LIST_ISSUES
List existing issues (check for duplicates).

**Useful for:**
- Avoiding duplicate issues
- Finding related issues
- Checking issue status

### GITHUB_GET_ISSUE
Get details of a specific issue.

### GITHUB_UPDATE_ISSUE
Modify existing issue (add labels, change status, etc.)

## Workflow

### Step 1: Gather Information
Before creating, collect:

1. **Repository**: Which repo? (ask if unclear)
2. **Title**: Brief, clear summary
3. **Description**: Detailed explanation including:
   - What happened / expected behavior
   - Steps to reproduce (for bugs)
   - Environment details
   - Screenshots/logs if applicable
4. **Labels**: Appropriate labels
   - Bugs: "bug", "bug-report"
   - Features: "enhancement", "feature-request"
   - Priority: "high-priority", "low-priority"
   - Status: "help-wanted", "good-first-issue"
5. **Assignee**: Who should handle it? (optional)

### Step 2: Check for Duplicates
- Use GITHUB_LIST_ISSUES to search
- Link to related issues in description
- Avoid duplicates

### Step 3: Create Issue
Call GITHUB_CREATE_ISSUE with all gathered info.

### Step 4: Present Confirmation
Show user:
- Issue number (#123)
- Full URL to issue
- Labels applied
- Assignees (if any)

## Issue Templates (Use These Formats)

### Bug Report
```markdown
## Description
Brief description of the bug

## Steps to Reproduce
1. Go to '...'
2. Click on '...'
3. See error

## Expected Behavior
What should happen

## Actual Behavior
What actually happened

## Screenshots
If applicable

## Environment
- OS: [e.g., macOS 14.0]
- Browser: [e.g., Chrome 120]
```

### Feature Request
```markdown
## Feature Description
Clear description of the feature

## Problem Solved
What problem does this solve?

## Proposed Solution
How should it work?

## Alternatives Considered
Other approaches considered
```

## Important Rules
1. **Confirm before creating** - Show user the issue first
2. **Use templates** - Follow bug report / feature request formats
3. **Add relevant labels** - Helps with triage
4. **Be descriptive** - Include all relevant details
5. **Check permissions** - Ensure user has repo access
6. **Verify repo** - Confirm correct repository

## Tips
- Use Markdown for formatting
- Include code snippets if relevant
- Add steps for reproducibility
- Be specific in titles
- Link related issues
