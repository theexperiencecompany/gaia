# HeroUI v2 → v3 migration (GAIA web)

Measured on `apps/web`, 2026-11-01. Re-run the tools after each phase; every number
below is generated, not estimated.

## 1. Scope, measured

| Tier | Sites | What it means |
|---|---|---|
| **A — mechanical** | 897 | prop/variant swaps. Codemod, then eyeball the diff. |
| **B — structural** | 230 | compound components (`Input`→`TextField`, `Modal.Header`, item `id`/`textValue`). Codemod scaffolds, human finishes. |
| **removed** | 4 | `Snippet` (2), `User` (2) — no v3 equivalent, replace with HTML. |

1,131 JSX sites across 363 files. React 19.1 and Tailwind 4.3 are already in place,
so there's no framework upgrade — only components, variants, and tokens.

**Nothing is blocked.** The MCP server exposes guides for 39 components but the docs
table lists 72; `Pagination`, `Progress` (→`ProgressBar`), `Table`, `Badge` all exist
in v3. Read the table at `/docs/react/migration#step-6-component-migration-reference`,
not the MCP tool enum.

Truly removed in v3: `Code`, `Image`, `Navbar`, `Snippet`, `Spacer`, `User`, `Ripple`.

## 2. Variants — the part that actually decides the timeline

`node tools/heroui-migration/variants.mjs` extracts both vocabularies from the
installed type definitions (`@heroui/theme` for v2, `@heroui/styles` for v3) and
joins them against your real usage:

```
1,591 variant sites · 123 distinct (component, prop, value) tuples
same 518 · rename 482 · moved-into-variant 158 · dropped 252 · dynamic 107
→ needs a human decision: 17 tuples / 64 sites
```

So **96% of variant usage is mechanically determined**. The 17 that aren't:

| uses | v2 | v3 options | decision |
|---|---|---|---|
| 12 | `Accordion variant="light"` | `default \| surface` | visual call |
| 10 | `Spinner color="default"` | `accent \| current \| danger \| success \| warning` | `accent` |
| 8 | `Spinner color="primary"` | same | `accent` |
| 7 | `Modal size="2xl"` | `xs \| sm \| md \| lg \| full \| cover` | map 2xl→full |
| 6 | `Tabs variant="solid"` | `primary \| secondary` | `primary` |
| 4 | `Tabs variant="underlined"` | `primary \| secondary` | `secondary` |
| 3 | `Button size="icon"` | `sm \| md \| lg` | `md` + `isIconOnly` |
| 2 | `Badge color="primary"` | `accent \| …` | `accent` |
| ~12 | `Modal size="xl/3xl/4xl/5xl"` | as above | collapse |

**Critical detail:** v3 folds `color` *into* `variant` for Button. Mapping the props
independently is wrong — `color="primary" variant="flat"` → `variant="tertiary"`, but
`color="danger" variant="flat"` → `variant="danger-soft"`. The report has a dedicated
joint `color × variant` table built from your actual pairs:

```
100x  (none)|light          -> tertiary
 91x  (none)|flat           -> tertiary
 74x  primary|(none)        -> primary
 35x  primary|flat          -> tertiary
  9x  danger|light          -> DECIDE
```

Open `tools/heroui-migration/variants-report.html`.

## 3. The automation loop

```
inventory + variants  →  screenshot baseline  →  codemod  →  typecheck  →  visual diff  →  bundle diff
                                                                              ↑                ↑
                                                                     what actually      what it ships
                                                                     changed, on screen
```

### a. Baseline screenshots (before touching code)

```bash
cd ~/Projects/gaia
node tools/heroui-migration/routes.mjs      # 68 routes from the app dir
node tools/heroui-migration/visual/shoot.mjs --label v2
```

Headless Chromium, desktop 1440 + mobile 390, full-page PNGs, 4 workers, no agent
driving the UI. Takes ~2 min for all 136 shots.

### b. Codemod

```bash
./tools/heroui-migration/node_modules/.bin/jscodeshift \
  -t tools/heroui-migration/codemods/v3-props.cjs \
  --parser=tsx --extensions=tsx apps/web/src
```

Verified dry run on this repo: **284 files rewritten, 0 errors, 213 sites flagged**
for manual review (124 `Button` content props, 78 `Chip`, 9 `Tooltip`, 1 `Spinner`,
1 `Avatar`) → `manual-review.log`.

### c. Visual diff — the review surface

```bash
node tools/heroui-migration/visual/shoot.mjs --label v3
node tools/heroui-migration/visual/compare.mjs --a v2 --b v3
open tools/heroui-migration/visual-report.html
```

The unit of review is a **changed region**, not a percentage. Every cluster of
changed pixels becomes a before/after crop:

- cards show the largest change per route as stacked before/after crops
- lightbox: full page with red boxes over every changed region, a before/after
  slider, and a filmstrip of all region crops; `←/→` switches viewport
- percentages are only a sort key — the crops are the point

### d. Bundle / tree-shaking

```bash
node tools/heroui-migration/bundle.mjs --snapshot v2      # after `pnpm -C apps/web build`
node tools/heroui-migration/bundle.mjs --snapshot v3
node tools/heroui-migration/bundle.mjs --compare v2 v3
node tools/heroui-migration/bundle.mjs --deps             # no build needed
```

Reads `.next/app-build-manifest.json`, so it measures **shipped bytes per route**:
unique JS, duplication factor, css, and which packages survive into
`.next/static` (framer-motion should disappear; `@heroui/theme` should too).
`--deps` measures the install graph — 33 `@heroui/*` micro-packages + framer-motion
collapse to 2 packages.

### e. Phase gate

```bash
pnpm -C apps/web type-check && pnpm -C apps/web lint && pnpm -C apps/web test
```

Do **not** run `next build` during the component phase — HeroUI's guide is explicit
that it produces thousands of expected errors and hides real progress. Build only
after the dependency switch (phase 4).

## 4. Phases

| # | Phase | Scope | Exit gate |
|---|---|---|---|
| 0 | Branch + baseline | 136 screenshots, `variants-report.html` decisions | screenshots green |
| 1 | Tier A codemod | 897 sites / 284 files | typecheck + visual triage |
| 2 | Variant decisions | the 17 tuples above | `variants-report.html` has no `DECIDE` |
| 3 | Tier B structure | `Input`→`TextField` (67), `Modal` (36), `Select` (26), `Tabs` (23), `Accordion` (18), `Dropdown` (17), `Switch` (11), `Popover` (8), `Card` (7), `Autocomplete` (4), `Table` (3), `Checkbox` (3), `Slider` (3), `Radio` (2), `Pagination` (1), `NumberInput` (1) | forms submit, overlays work, keyboard nav |
| 4 | Removed components | `Snippet` (2), `User` (2) → HTML | visual parity |
| 5 | Dependency switch | `@heroui/react@3` + `@heroui/styles`, drop 33 micro-packages + framer-motion, delete `hero.ts`, remove `heroui()` from Tailwind, delete `HeroUIProvider` (3 layout files) | `pnpm build` clean |
| 6 | Styling | tokens/utilities (321 `flat`, 136 `light`, 82 `radius=full`) | visual pass + bundle diff |
| 7 | Hooks | `useDisclosure` (19) → `useOverlayState` | gate |
| 8 | Docs | `apps/web/AGENTS.md`, `apps/web/CLAUDE.md` reference HeroUI APIs | no stale imports in guides |

Tag `v2-last-good` before phase 5. Phases 0–4 are source-only on v2 deps and revert
cleanly; phase 5+ is a lockfile flip.

Realistic effort with this harness: **4–6 hours** for phases 1–7, plus whatever the
17 variant decisions need in design review.

## 5. Files

| File | Purpose |
|---|---|
| `inventory.mjs` | JSX site inventory, tiers, stale docs |
| `variants.mjs` | v2↔v3 variant vocabularies joined to real usage |
| `codemods/v3-props.cjs` | Tier A codemod + `Divider`→`Separator` |
| `visual/shoot.mjs` | headless screenshot capture |
| `visual/compare.mjs` | pixel diff → region crops → review UI |
| `bundle.mjs` | per-route shipped bytes, tree-shaking deltas |
| `report.mjs` | side-by-side code diff of every changed file |
| `routes.mjs` | derives routes from the app dir |
| `v3-variants.json` | v3 vocabulary snapshot (regenerate with `--v3-dir`) |

Generated and gitignored: `inventory.json`, `variants.json`, `shots/`,
`visual-report.html`, `bundle-*.json`, `manual-review.log`.
