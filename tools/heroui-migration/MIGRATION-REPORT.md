# HeroUI v2 → v3 migration — result

Branch: `heroui/v3-migration` (worktree `~/Projects/gaia.heroui-v3`), commit `f9a6de6399`.
Baseline: `~/Projects/gaia.v2-baseline` (clean HEAD checkout, built for comparison).

## Gates

| Gate | Before | After |
|---|---|---|
| `tsc --noEmit` | 951 errors (post-codemod, v3 installed) | **0** |
| `biome check src` | 6 errors | **4 errors** |
| `next build` | ✅ | **✅** |
| Routes rendering | 68 | **68** |
| Page height within 5% of v2 | — | **65 / 67** (2 deliberate: `/faq`, `/pricing`) |

## Bundle (measured from the built app, per route)

| Metric | v2 | v3 | Δ |
|---|---|---|---|
| Unique client JS | 11,383.3 kB | 11,315.3 kB | **−68.0 kB** (−0.6%) |
| Avg JS per route | 4,406.2 kB | 4,232.6 kB | **−173.6 kB** (−3.9%) |
| Unique chunks | 201 | 204 | +3 |
| CSS per route | 687.7 kB | 931.9 kB | **+244.2 kB (+35%)** |

**Read this honestly:**

- The *unique* code barely moved. HeroUI v3 (React Aria Components + tailwind-variants)
  weighs about the same as v2 (React Aria hooks + framer-motion), so swapping one for
  the other is a wash.
- The win is **per-route**: −174 kB average (−3.9%), because the dependency graph is
  flatter. That's what users actually download.
- **CSS regressed +35%.** v3 ships a large stylesheet. This is the one real cost and
  the obvious next optimisation (purging unused component CSS).
- Tree shaking itself is working: `RangeCalendar`, which the app never uses, appears
  in **0** chunks. `ColorPicker` leaks into 3 (pulled in by Select/DatePicker internals).
- `@heroui/react` declares `sideEffects: false` and exposes per-component subpaths
  (`@heroui/react/button`). Barrelled imports already tree-shake here, so rewriting
  300 files to subpaths would not have paid for itself — measured, not assumed.

Dependencies: **34 `@heroui/*` packages + framer-motion → 2 packages** (`@heroui/react`, `@heroui/styles`).

## Visual diff

`tools/heroui-migration/visual-report.html` — 68 routes, **56 changed / 12 identical, 942 changed regions**.
Each card is the largest changed region on that route, before stacked on after; click for
the full page with red boxes over every region, a drag slider, and a filmstrip of crops.

Page heights within 5% on 65/67 routes ⇒ layout is intact; the differences are component
sizing, not structure.

## What changed in the code

| Area | Count |
|---|---|
| Files touched | 367 |
| Mechanical codemod (variant/prop rewrites) | 291 files, 0 errors |
| Structural rewrites (compound components) | 135 files |
| Variant sites resolved | 1,591 across 123 (prop, value) tuples |
| Variant decisions that needed a human | 17 tuples / 64 sites |

Converted: `Modal` → `Backdrop/Container/Dialog/Header/Body/Footer`, `Select` → `Trigger/Value/Popover` + `ListBox.Item`,
`Tabs` → `List/Panel`, `Accordion` → `Item/Heading/Trigger/Panel`, `Input` → `TextField` + `Label/FieldError`,
`Dropdown` → `Trigger/Popover/Menu`, `Card` → `Header/Content/Footer`, `Tooltip` → `Trigger/Content`,
`Avatar` → `Image/Fallback`, `Progress` → `ProgressBar`, `NumberInput` → `NumberField`,
`useDisclosure` → `useOverlayState`, `Divider` → `Separator`, `Snippet`/`User` → HTML.

## Two things to review before merging

1. **CSS +35%** — the only measured regression. Worth a follow-up purge pass.
2. **`isOpen` placement is inconsistent** — 22 modals put it on `<Modal>`, 26 on
   `<Modal.Backdrop>`. Both type-check (Root extends RAC `DialogTrigger`, Backdrop
   accepts `isOpen` directly), but it should be one or the other.

Also worth knowing: the codemod's global `isLoading → isPending` rename over-reached onto
non-HeroUI components (shadcn buttons, Radix accordion). Agents reverted those, but a
spurious `isPending` could still exist where a custom prop was named `isLoading`.

## Reproduce

```bash
cd ~/Projects/gaia.heroui-v3
node tools/heroui-migration/visual/compare.mjs --a v2 --b v3
node tools/heroui-migration/bundle.mjs --compare v2 v3
open tools/heroui-migration/visual-report.html
open tools/heroui-migration/bundle-report.html
```

Servers used: v2 on `:3100` (baseline worktree), v3 on `:3200`.

## Rollback

```bash
cd ~/Projects/gaia
git checkout seo/hub          # your tree was never touched — migration is in a worktree
git worktree remove ../gaia.heroui-v3
```
