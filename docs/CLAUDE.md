# CLAUDE.md — docs/

This is a [Mintlify](https://mintlify.com) documentation site for GAIA, served at https://docs.heygaia.io.

## Key Commands

```bash
# Preview docs locally (run from the docs/ directory)
nx dev docs
# or directly:
cd docs && mintlify dev

# Mintlify CLI must be installed: npm install -g mintlify
```

## Structure

- `docs.json` — single source of truth for navigation, theme, SEO, and site config. **All new pages must be registered here** under `navigation.tabs[].groups[].pages` or they won't appear in the sidebar.
- `introduction.mdx`, `quick-start.mdx`, etc. — top-level pages
- `developers/`, `self-hosting/`, `bots/`, `cli/`, `configuration/` — section directories
- `knowledge/` — large programmatic SEO section (glossary, comparisons, use-cases, etc.). Hundreds of pages; don't hand-edit en masse.
- `snippets/` — reusable MDX snippets (include via `<Snippet file="..." />`)
- `images/`, `logo/` — static assets

## Skills

**Always use the `copywriting` skill when writing or editing any prose in docs pages.** Invoke it via the `Skill` tool before drafting feature descriptions, explanations, onboarding copy, or any user-facing text. Do not write marketing or explanatory copy ad-hoc.

See the full skill reference table at the bottom of this file.

## Writing Docs

**Frontmatter** (required on every page):
```mdx
---
title: "Page Title"
description: "One-line description shown in meta and sidebar"
icon: "icon-name"   # optional, Font Awesome icon slug
---
```

**Common Mintlify components** used in this repo:
- `<Card>`, `<CardGroup cols={2}>` — feature grids
- `<Steps>`, `<Step title="...">` — numbered how-to steps
- `<Tip>`, `<Note>`, `<Warning>` — callout blocks
- `<Snippet file="snippets/foo.mdx" />` — shared content

Page paths in `docs.json` are **relative and extensionless** (e.g., `"developers/introduction"` maps to `developers/introduction.mdx`).

## Images

**Always use `<Frame>` for images.** Do not use markdown image syntax (`![alt](src)`). Use absolute paths from the project root.

```mdx
<Frame>
  <img src="/images/screenshots/example.webp" alt="Descriptive alt text" />
</Frame>
```

- No relative paths (`../images/` or `./images/`) — always use absolute (`/images/...`)
- Every image must have a meaningful `alt` attribute (not generic like "image")

## Mintlify Reference

When making component changes or adding new Mintlify components, fetch the official docs:
https://www.mintlify.com/docs/llms.txt

## Available Skills

Always invoke these via the `Skill` tool rather than doing the work ad-hoc:

| Skill | When to use |
|---|---|
| `mintlify` | Configuring navigation in `docs.json`, adding Mintlify components, setting up API references, fixing build issues |
| `copywriting` | Writing or improving feature descriptions, explanations, or any prose in docs pages |
| `landing-page-copywriter` | Homepage copy (`introduction.mdx`) or feature landing pages |
| `seo-geo` | Optimizing page titles, descriptions, and meta in `docs.json` or `knowledge/` pages |

## Release Notes Image Convention

The in-app "What's New" sidebar card and modal parse `release-notes.mdx` to display releases. They don't read the `.mdx` directly — they read Mintlify's generated RSS feed (`/release-notes/rss.xml`) via `apps/web/src/app/api/releases/route.ts`, which regex-extracts the first `<img>` from each item's `content:encoded`. To include a hero image, **place an image as the very first element inside the `<Update>` block**, before the H1 title:

```mdx
<Update label="Mar 15, 2026" description="API, Web">

![Release hero](/images/changelog/release-mar-15-2026.webp)

# Feature Title Here

...
</Update>
```

- **Use a bare markdown image — never wrap it in `<Frame>` (or any JSX component).** Mintlify strips custom components and their children out of the RSS `content:encoded`, so a `<Frame>`-wrapped image renders fine on the docs page but is dropped from the feed entirely. The parser then finds no image and the card/modal fall back to the default wallpaper for that release. Only the bare markdown `![alt](src)` survives into the RSS as a plain `<img>`. (The page-level hero at the top of `release-notes.mdx` is `<Frame>`-wrapped on purpose — it lives outside every `<Update>` block, so it's never part of any RSS item.)
- Images must go in `images/changelog/` (not the root `images/` dir)
- Name pattern: `release-{mon}-{dd}-{yyyy}.webp` (e.g. `release-mar-15-2026.webp`)
- Mintlify rewrites the relative `/images/...` path to an absolute `https://docs.heygaia.io/...` URL in the feed, so the app loads it directly — no extra config needed.
- The image is optional — omitting it is fine, the card will render without one
- The parser grabs **only the first image** in the block; any subsequent images are ignored for the card
- **Don't hand-edit the page-level hero `<img src>` at the top of `release-notes.mdx`.** `scripts/generate-changelog-pages.js` auto-syncs it to the newest release's image on every run (pre-commit + CI), so the page banner always matches the latest release. Just give the newest `<Update>` block its hero image and the page banner follows. If the newest release has no image, the existing banner is left untouched.

## Non-obvious Patterns

- **Navigation is not auto-discovered.** Adding an `.mdx` file does nothing until its path is added to `docs.json`. Always update both.
- **The `knowledge/` section is programmatic SEO.** It has 180+ pages across glossary, comparisons, use-cases, etc. Edits to tone or structure should be done consistently across the group, not one-off.
- **No build step for content.** MDX is rendered by Mintlify's cloud (or local CLI). There is no compile step to run after editing — just save and the dev server hot-reloads.
- **Images go in `images/`**, referenced as `/images/filename.webp`. Mintlify serves them as static assets from the project root.
- **`docs.json` uses `$schema`** for editor autocomplete — keep it present when editing.
