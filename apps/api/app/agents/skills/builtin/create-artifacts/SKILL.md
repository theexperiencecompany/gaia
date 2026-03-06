---
name: create-artifacts
description: Create rich file artifacts (documents, code, reports, HTML pages) that appear as interactive cards in chat when placed in .user-visible/.
target: executor
---

# Create Artifacts

## When to Use

Activate when the user asks for standalone files that are better as viewable/downloadable outputs than inline chat text:

- Reports, briefs, plans, strategy docs
- Code files or multi-file deliverables
- HTML pages/templates
- Structured exports (CSV, JSON, YAML)

## When Not to Use

- Short conversational answers
- Small snippets that fit in normal response text
- Cases where the user explicitly asks for inline output

## Core Rule

Files are shown to the user only when they are in `.user-visible/` for the current session.

Use:
vfs_write(".user-visible/file-name.ext", content)

This auto-resolves to the session-scoped location.

## Prerequisites

If `vfs_write` is not already available, bind it before proceeding:

    retrieve_tools(exact_tool_names=["vfs_write", "vfs_cmd"])

## Preferred Workflow (Robust)

For substantial work, use a two-step flow:

1. Write privately in `files/` or `notes/`
2. Move the polished result into `.user-visible/`

Example:

    vfs_write("files/draft-plan.md", draft_content)
    # iterate, refine, validate
    vfs_cmd("mv files/draft-plan.md .user-visible/final-plan.md")

This ensures users only see final artifacts, not intermediate drafts.

## Important Safety Rules

1. Never put temporary/scratch/debug files in `.user-visible/`
2. Never put partial or broken output in `.user-visible/`
3. Use descriptive filenames with clear extensions
4. Always provide a short summary in the assistant response describing what was created

## Format Preference

1. HTML (`.html`) by default for user-facing artifacts that should look polished
2. Markdown (`.md`) only when the user asks for Markdown or plain docs
3. Language-specific code extensions for code
4. Text (`.txt`) only when formatting is unnecessary

## HTML Quality Standard

When generating HTML artifacts, prioritize quality over speed:

1. Use semantic structure (`header`, `main`, `section`, `article`, `footer`)
2. Make layout responsive (desktop + mobile)
3. Ensure clear visual hierarchy (headings, spacing, readable body text)
4. Use cohesive styling with thoughtful typography, color, and contrast
5. Deliver production-like output (no placeholder text, no broken sections)

## Response Pattern

After creating an artifact, briefly tell the user:

- What file was created
- What it contains
- Why it is useful

Keep this concise and practical.
