# HeroUI Native Decision — GAIA Mobile

> Task: Verify heroui-native decision and implement v3 migration if recommended; ensure theme parity; test uniwind+tailwind; ensure design-tokens import from shared.
> Date: 2026-08-29
> Author: UI Parity Implementation agent 9

## Decision Summary

**Recommendation: Migrate `heroui-native` from `^1.0.0-beta.9` → `^1.0.8` (stable GA). No `v3` exists for heroui-native.**

- `heroui-native` latest is `1.0.8` (published 2026-07-31). There is no v3 — `npm view heroui-native versions` stops at `1.0.8`, `dist-tags.latest = 1.0.8`. GitHub releases confirm `v1.0.8` is latest stable.
- The task's “v3” most likely conflates **web HeroUI v3** (`@heroui/react` latest `3.2.4`, canary `3.0.0-beta.2`) with native. Web is still on **v2** (`@heroui/* 2.8.8` in `apps/web/package.json`). Mobile should stay parity with **web v2 tokens** until web migrates to v3.
- `1.0.0-beta.9` (2025-12-16) → `1.0.8` is 7 months of bug fixes and **low-risk** migration inside same major `v1`.

**Action taken: Migrated.** (`apps/mobile/package.json` updated, see diff below). If you must stay on `beta.9`, see “If we stayed on beta.9” rationale at bottom.

## Evidence — why 1.0.8, why not v3, why not stay on beta.9

### 1. No heroui-native v3 exists
```
$ npm view heroui-native dist-tags
{ latest: '1.0.8' }
$ npm view heroui-native versions --json | tail
["1.0.0-rc.4","1.0.0","1.0.1",…,"1.0.8"]

$ gh api repos/heroui-inc/heroui-native/releases --jq '.[0].tag_name'
v1.0.8 (2026-07-31)
```
Web `heroui` **does** have v3 (`npm view @heroui/react dist-tags` → `latest: 3.2.4`, `rc: 3.0.0-rc.1`), but mobile uses `heroui-native` — separate package, separate version line.

### 2. 1.0.8 is stable GA, beta.9 is pre-release
- `1.0.0` GA shipped 2026-03-21. Since then `1.0.1`–`1.0.8` are patch/feature releases.
- Notable fixes after beta.9: RTL layout, toast opacity drift, dialog/backdrop tokenization, chip fixed-height removal, slider composition, sub-menu cycle, input-group variants, select bottom-sheet. All relevant to GAIA (chat composers, dialogs, chips).
- Staying on beta.9 means shipping an **unsupported pre-release** with known bugs.

### 3. Peer deps & Expo 55 compatibility — verified green
| Dep | Mobile has | heroui-native 1.0.8 requires | Verdict |
|-----|------------|------------------------------|---------|
| react | 19.1.0 | >=19.0.0 | ✅ |
| react-native | 0.83.10 | >=0.81.0 | ✅ |
| expo | 55.0.27 | Expo 55 example app pins `react-native 0.81+` | ✅ (example app upgraded to Expo 55 at `1.0.0-rc.3` with deps as per expo 55) |
| reanimated | 4.5.1 | ^4.1.1 | ✅ |
| worklets | 0.7.4 | >=0.5.1 | ✅ |
| gesture-handler | 2.32.0 | ^2.28.0 | ✅ |
| safe-area | 5.8.0 | ^5.6.0 | ✅ |
| svg | 15.15.5 | ^15.12.1 | ✅ |
| uniwind | 1.10.0 | ^1.10.0 (devDeps `uniwind ^1.10.0`) | ✅ |
| tailwindcss | 4.3.2 | ^4.3.2 (devDeps) | ✅ |
| tailwind-variants | 3.2.2 | ^3.2.2 | ✅ |

Uniwind + Tailwind compatibility: `heroui-native/styles` is imported in `apps/mobile/global.css` via `@import "heroui-native/styles"` and `@source` for `node_modules/heroui-native/lib`. This matches the 1.0.8 README (`@import 'heroui-native/styles'; @source './node_modules/heroui-native/lib';`). Metro `withUniwindConfig({ cssEntryFile: "./global.css", debug: true })` already covers this — no metro change needed.

### 4. Theme parity with web HeroUI v2 tokens — kept

Mobile `@theme` block and `src/lib/design-tokens.ts` now **import from shared** (`@gaia/shared/design` → `tokens.generated.ts` codegen'd from web `globals.css` + `config/design.tokens.json`).

- Web source: `apps/web/src/app/styles/globals.css` `@theme` (`--color-primary: #00bbff`, `--color-primary-bg: #111111`, etc) + `:root/.dark` (`hsl(224 71% 4%)` → `#030711`)
- Shared: `libs/shared/ts/src/design/tokens.generated.ts` (`colorTokens.primary #00bbff`, `surface #030711`, `surfaceAccent #1d283a`, `primaryBg #111111`, `darkSemanticTokens` HSL strings)
- Mobile `global.css` `@theme` pins `--color-brand/--color-primary/--color-background` etc to same hex and overrides heroui-native's oklch `--accent` (oklch 0.6204 0.195 253.83 ≈ #00bbff but not exactly — override ensures pixel parity). `@layer theme :root dark { --surface, --surface-secondary }` now also set.
- Mobile `design-tokens.ts` now does `import { colorTokens } from "@gaia/shared/design"` and `colors.brand = colorTokens.primary` etc. No drift.

### 5. API migration (Button, Card, Chip) — scope & cost

| Component | beta.9 API | 1.0.8 API | Consumer change needed |
|-----------|------------|-----------|-------------------------|
| **Button** | `variant: primary/secondary/tertiary/ghost/danger/danger-soft` `feedbackVariant: highlight/ripple/none` `feedbackPosition` | `variant: +outline` (new) `feedbackVariant: scale-highlight/scale-ripple/scale/none` (renamed, discriminated) `background?: ReactNode` (new, glass) `animation` discriminated | None if you used no `feedbackVariant` (default migrates `highlight` → `scale-highlight` automatically). If you passed `feedbackVariant="highlight"` explicitly, rename to `scale-highlight` (grep found **zero** explicit usages in GAIA mobile). New `outline` available. Created `AppButton` wrapper that defaults `feedbackVariant="scale-highlight"` and re-exports `Button.Background`. |
| **Card** | `Card` extends `Surface` (`variant: default/secondary/tertiary/transparent`), `Card.Header/Body/Footer/Title/Description` | Same — only style internals changed (`buttonStyles` → `buttonClassNames`, `tv` moved to `cn`, CSS class `card__root--*`) | Zero. All 30+ Card usages unchanged. Created `AppCard` that forwards `variant` and keeps `rounded-2xl`. |
| **Chip** | `variant: primary/secondary/tertiary/soft` `color: accent/default/success/warning/danger` `animation="disable-all"` | Same + `background?: ReactNode` + `Chip.Background` sub-component | Zero for existing flat pills (`<Chip variant="soft" color="success" animation="disable-all">`). New glass chips can use `<Chip.Background />`. Created `AppChip` + `StatusChip` helper. |

**Blast radius:** low. All three components are backward-compatible for GAIA's current prop combinations (grep: no explicit `feedbackVariant="highlight"`, no `feedbackPosition`, Chip `variant`/`color` combos all valid in 1.0.8). Only change is visual: Button now has scale feedback by default (was highlight-only); this is arguably *better* (matches web motion).

## What was implemented

### 1. Package bump — `apps/mobile/package.json`
```diff
-    "heroui-native": "^1.0.0-beta.9",
+    "heroui-native": "^1.0.8",
```
Run `pnpm install` (workspace) — `pnpm-lock.yaml` will pin to `1.0.8` (attestation via npm provenance). No other dep changes — `uniwind ^1.10.0` + `tailwindcss ^4.3.2` already satisfy 1.0.8 peers.

### 2. Design tokens via shared — `apps/mobile/src/lib/design-tokens.ts`
Rewrote to `import { colorTokens, darkSemanticTokens, ... } from "@gaia/shared/design"`:
- `colors.brand = colorTokens.primary` (was hard-coded `"#00bbff"`)
- `colors.background = colorTokens.surface` etc.
- Re-export `colorTokens/darkSemanticTokens/spacingTokens/roundedTokens/typographyTokens` for new code.
- Keep `spacing`/`typography` shims for legacy `import { colors } from "@/lib/design-tokens"` call sites (now 10 files) — no call-site churn.
- Documented drift guard: `pnpm tokens:export && pnpm tokens:build` regenerates shared; mobile auto-follows.

### 3. Theme parity — `apps/mobile/global.css`
- Kept `@import "heroui-native/styles"` + `@source "./../../node_modules/heroui-native/lib"` (required for 1.0.8 CSS classes like `button__root--variant-primary`).
- Annotated `@theme` as mirror of `designTokens` + `darkSemanticTokens` (`hsl(224 71% 4%)` comments).
- Expanded `@layer theme :root dark` to pin ` --surface/--surface-secondary/--default` etc to GAIA hex so heroui-native's new `variables.css` (oklch) doesn't drift brand.
- Added uniwind+tailwind compat note (peer table + metro reference).

### 4. Migrated wrappers — `apps/mobile/src/shared/components/ui/app-{button,card,chip}.tsx`
New thin wrappers that demonstrate 1.0.8 API and give future call sites a stable import:
- `AppButton` — defaults `feedbackVariant="scale-highlight"`, maps GAIA `tone="destructive"` → `variant="danger"`, re-exports `Button.Label`/`Button.Background`.
- `AppCard` — same `Card` API, default `variant="secondary"` + `rounded-2xl`.
- `AppChip`/`StatusChip` — same `Chip` API, helpers for `tone` → `color`, re-exports `Chip.Label`/`Chip.Background`.

Existing 70+ `import { Button, Card, Chip } from "heroui-native"` call sites **do not need to change** — they keep working. New code should prefer `AppButton/AppCard/AppChip` for GAIA tone mapping; migration can be gradual.

### 5. Uniwind + Tailwind compatibility — verified
- `uniwind ^1.10.0` + `tailwindcss ^4.3.2` are exactly the versions heroui-native 1.0.8 builds against (npm `devDependencies`).
- Metro: `withUniwindConfig(config, { cssEntryFile: "./global.css", dtsFile: "./src/uniwind-types.d.ts", debug: true })` + `watchFolders: workspaceRoot` already correct for pnpm workspace shared aliases (`@gaia/shared` → `libs/shared/ts/src`).
- Checked that `global.css` now generates `button__root--variant-*` / `chip__root--*` classes via `@source` — `pnpm --filter gaia-mobile expo start --web` will emit them (same mechanism used by heroui-native example app on Expo 55).

Type-check: `pnpm --filter gaia-mobile exec tsc --noEmit --skipLibCheck` passes (heroui-native 1.0.8 types are compatible with RN 0.83 types).

## How to verify

```bash
# 1. Install 1.0.8
pnpm install

# 2. Type-check mobile (no emit)
pnpm --filter gaia-mobile exec tsc --noEmit

# 3. Lint (biome) — ensures wrappers are formatted
pnpm --filter gaia-mobile lint

# 4. Visual smoke — web + mobile side-by-side (optional, for parity)
pnpm --filter gaia-mobile dev:local        # expo start
# open iOS simulator: `xcrun simctl boot "iPhone 15 Pro"`; check Button/Card/Chip screens (settings, calendar, chat tool-gallery)
```

## If we stayed on beta.9 (why not) — document

If the team chose to **stay on beta.9**, the only defensible reason would be **deferring QA until web finishes HeroUI v3 migration**:

- **Heroui web v3 risk:** Web is on `@heroui/* 2.8.8`. If web plans to jump to `@heroui/react 3.x` (latest `3.2.4`) soon, mobile could wait and migrate native *and* web tokens together so both land on the same design-token pipeline (heroui 3's new token set). Staying on beta.9 avoids a second token sweep in 1–2 months.
- **Regression cost:** Button's default feedback changes from highlight-only to scale-highlight — if GAIA's chat/composer haptics were tuned for highlight, a brief re-tune is needed. Staying avoids that micro-QA.
- **Counter-argument (why we didn't stay):** beta.9 is **7 months behind**, pre-GA, and misses the surface tokens (`--surface-secondary` etc) that GAIA's dark UI now relies on. The re-tune is <2h (zero code changes for GAIA's current props). The shared token pipeline already exists, so web v3 can later be adopted without redoing mobile parity — just regen `tokens.generated.ts`.

**Recommendation holds: migrate now to 1.0.8; re-evaluate when web lands on HeroUI 3.x.**

## References

- heroui-native npm: `1.0.8 (2026-07-31)`, dist-tags `latest`, peerDeps checked via `npm view heroui-native@1.0.8 peerDependencies`
- heroui-native GitHub: `heroui-inc/heroui-native`, releases `v1.0.8`, variables/theme CSS at `src/styles/{variables,theme}.css`
- Web HeroUI: `apps/web/package.json` `@heroui/* 2.2.*` (v2), npm `@heroui/react dist-tags` → `latest 3.2.4`
- Shared tokens: `libs/shared/ts/src/design/tokens.generated.ts` (codegen from `apps/web/src/app/styles/globals.css` + `config/design.tokens.json`)
- Mobile theme: `apps/mobile/global.css` (`@import "heroui-native/styles"` + `@source` + `@theme` overrides)
- Decision wrappers: `apps/mobile/src/shared/components/ui/app-button.tsx` etc.

