# Changelog Instructions

This file documents the structure and conventions for `release-notes.mdx`.

## File

`docs/changelog/release-notes.mdx` — registered in `docs.json` under the Changelog tab.

## Entry Format

Every release uses the Mintlify `<Update>` component. For the per-app era (post-v0.11.0), each app section is wrapped in `<AppSection app="...">` for client-side filtering:

```mdx
<Update label="Feb 27, 2026" description="Changes to API, Web, Desktop, Mobile, Bots, CLI">

<AppSection app="api">
# [API v0.16.0](https://github.com/theexperiencecompany/gaia/releases/tag/api-v0.16.0)

## Features
- **Feature name**: Description for end users

## Bug Fixes
- **Fix name**: What was fixed
</AppSection>

<AppSection app="web">
---

# [Web v0.17.0](https://github.com/theexperiencecompany/gaia/releases/tag/web-v0.17.0)

## Features
- ...
</AppSection>

</Update>
```

The `FilterableChangelog` and `AppSection` components are defined in `docs/snippets/filterable-changelog.mdx` and imported at the top of `release-notes.mdx`.

## Label Convention

Format: `ShortMonth Day, Year`

- Short month names: Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep, Oct, Nov, Dec
- No version number in the label
- Examples: `Feb 27, 2026`, `Aug 2, 2025`

## Description Convention

- Per-app era (post-v0.11.0): `Changes to API, Web, Mobile, Desktop` (list only apps that shipped)
- Unified era (pre-v0.11.0): `Changes to Platform`

## Heading Hierarchy

- `#` (h1): App name + version as an anchor link to the GitHub release tag
- `##` (h2): Section type (Features, Bug Fixes, Improvements, Infrastructure, Performance, Documentation)
- Bullet points with bold names: `- **Name**: Description`

## Per-App Era (post-v0.11.0)

One entry per release date. Each app gets its own `#` heading with sections inside. Apps are separated by `---` horizontal rules. Only include apps that have changes.

Tag URL pattern: `https://github.com/theexperiencecompany/gaia/releases/tag/{app}-{version}`

App prefixes: `api-`, `web-`, `mobile-`, `desktop-`, `bots-`, `cli-`

## Unified Era (pre-v0.11.0)

One entry per version. Single `#` heading linking to the unified tag.

Tag URL pattern: `https://github.com/theexperiencecompany/gaia/releases/tag/{version}`

## Section Types

Only include sections that have content:

- **Features**: New user-facing functionality
- **Bug Fixes**: Things that were broken and are now fixed
- **Improvements**: Enhancements to existing functionality, refactors, DX
- **Infrastructure**: CI/CD, Docker, deployment, tooling
- **Performance**: Speed and latency improvements
- **Documentation**: Docs, guides, blog posts

## Tags

No `tags` attribute on `<Update>` components. The sections and app headings provide sufficient categorization.

## Ordering

Entries are in **reverse chronological order** (newest first).

## Writing Style

- Write for end users, not developers
- No commit hashes, PR numbers, file paths, or function names
- Bold the feature/fix name: `- **Name**: Description`
- Keep descriptions to one sentence
- Be comprehensive but concise: cover every meaningful change
- Group related micro-changes into single bullet points

## AppSection Rules

- **First** app section in an Update: no `---` inside the wrapper
- **Subsequent** app sections: include `---` at the top, before the `#` heading
- `app` prop is always lowercase: `api`, `web`, `desktop`, `mobile`, `bots`, `cli`
- Legacy "Platform" entries (pre-v0.11.0) are NOT wrapped — they have no per-app separation

## Adding a New Entry

1. Determine the release date and which apps shipped
2. For each app, read `gh release view {app}-{version}` and `git log --oneline {prev-tag}..{new-tag}`
3. Write the entry at the TOP of the file (after the `<FilterableChangelog>` opening tag)
4. Wrap each app section in `<AppSection app="...">` per the format above
5. Update `docs.json` only if the page path changes (it shouldn't)
