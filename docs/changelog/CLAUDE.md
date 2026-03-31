# Changelog Instructions

This file documents the structure and conventions for `release-notes.mdx`.

## File

`docs/release-notes.mdx` — registered in `docs.json` under the Release Notes tab.

## Entry Format

Every release uses the Mintlify `<Update>` component. No custom component wrappers are used — filtering is handled automatically by `docs/scripts/changelog-filter.js`, which detects app headings at runtime.

**Per-app era (post-v0.11.0):**

```mdx
<Update label="Feb 27, 2026" description="API, Web, Desktop, Mobile, Bots, CLI">

# System Workflows, Agent Skills & Desktop Auto-Updates

## [API v0.16.0](https://github.com/theexperiencecompany/gaia/releases/tag/api-v0.16.0)

### Features
- **Feature name**: Description for end users

### Bug Fixes
- **Fix name**: What was fixed

---

## [Web v0.17.0](https://github.com/theexperiencecompany/gaia/releases/tag/web-v0.17.0)

### Features
- ...

</Update>
```

**Unified era (pre-v0.11.0):**

```mdx
<Update label="Dec 19, 2025">

# [v0.11.0](https://github.com/theexperiencecompany/gaia/releases/tag/v0.11.0)

Optional one-sentence summary of the release.

## Features
- **Feature name**: Description

## Bug Fixes
- **Fix name**: What was fixed

</Update>
```

## Label Convention

Format: `ShortMonth Day, Year`

- Short month names: Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep, Oct, Nov, Dec
- No version number in the label
- Examples: `Feb 27, 2026`, `Aug 2, 2025`

## Description Convention

- Per-app era (post-v0.11.0): comma-separated list of apps that shipped — `"API, Web, Mobile, Desktop"`
- Unified era (pre-v0.11.0): omit the `description` attribute entirely

## Heading Hierarchy

**Per-app era:**
- `#` (h1): Short descriptive release headline (e.g. "System Workflows, Agent Skills & Desktop Auto-Updates")
- `##` (h2): App name + version as an anchor link to the GitHub release tag (e.g. `## [API v0.16.0](...)`)
- `###` (h3): Section type (Features, Bug Fixes, Improvements, Infrastructure, Performance, Documentation)
- Bullet points with bold names: `- **Name**: Description`

**Unified era:**
- `#` (h1): Version number as an anchor link (e.g. `# [v0.11.0](...)`)
- `##` (h2): Section type
- Bullet points with bold names: `- **Name**: Description`

## Per-App Era (post-v0.11.0)

One `<Update>` per release date. Each app gets its own `##` heading with `###` sections inside. Apps are separated by `---` horizontal rules. Only include apps that have changes.

Tag URL pattern: `https://github.com/theexperiencecompany/gaia/releases/tag/{app}-{version}`

App prefixes: `api-`, `web-`, `mobile-`, `desktop-`, `bots-`, `cli-`

## Unified Era (pre-v0.11.0)

One `<Update>` per version. Single `#` heading linking to the unified tag.

Tag URL pattern: `https://github.com/theexperiencecompany/gaia/releases/tag/{version}`

## Section Types

Only include sections that have content:

- **Features**: New user-facing functionality
- **Bug Fixes**: Things that were broken and are now fixed
- **Improvements**: Enhancements to existing functionality, refactors, DX
- **Infrastructure**: CI/CD, Docker, deployment, tooling
- **Performance**: Speed and latency improvements
- **Documentation**: Docs, guides, blog posts

## Ordering

Entries are in **reverse chronological order** (newest first).

## Writing Style

- Write for end users, not developers
- No commit hashes, PR numbers, file paths, or function names
- Bold the feature/fix name: `- **Name**: Description`
- Keep descriptions to one sentence
- Be comprehensive but concise: cover every meaningful change
- Group related micro-changes into single bullet points

## Adding a New Entry

1. Determine the release date and which apps shipped
2. For each app, read `gh release view {app}-{version}` and `git log --oneline {prev-tag}..{new-tag}`
3. Write the entry at the TOP of `release-notes.mdx` (newest first)
4. Use the per-app format above — no component wrappers needed
5. Update `docs.json` only if the page path changes (it shouldn't)
