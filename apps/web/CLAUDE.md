# Web App (GAIA Frontend)

Next.js 16 frontend for GAIA — the proactive personal AI assistant. Handles the marketing site, authenticated app (chat, todos, calendar, workflows, integrations, etc.), and is also bundled into the Electron desktop app via standalone output.

## Key Commands

```bash
# Dev (Turbopack)
nx dev web          # or: pnpm dev (inside apps/web)

# Build
nx build web

# Lint (Biome)
nx lint web         # or: pnpm check
nx run web:lint:fix # or: pnpm fix

# Format
pnpm format         # inside apps/web

# Type-check
nx run web:type-check   # or: pnpm type

# Clean
nx clean web
```

Package manager is **pnpm**. Never use npm or yarn.

## Architecture

### Routing

All routes live under `src/app/[locale]/` — the locale segment is the top-level dynamic segment powering i18n.

Inside `[locale]/` there are two route groups:

- `(landing)` — public/marketing pages (homepage, pricing, blog, docs, download, login, signup, etc.)
- `(main)` — authenticated app (chat, dashboard, todos, calendar, goals, workflows, integrations, settings, etc.)

Each group has its own `layout.tsx`. The `[locale]/layout.tsx` is the root layout.

### Feature Modules

`src/features/` contains one folder per product feature (chat, todo, calendar, workflows, settings, integrations, etc.). Each feature typically contains:

```
src/features/<feature>/
  components/   — React components
  hooks/        — custom hooks
  api/          — API call functions
  types/        — feature-local types (only if not reusable elsewhere)
  utils/        — helpers
```

Do NOT generate barrel re-exports inside `src/features/` or `src/app/` — the `generate-barrels` script explicitly excludes them.

## State Management

Zustand (v5). Stores live in `src/stores/` and are named `use<Name>Store`.

Two patterns in use:

1. **Simple store** — `create<State>()(...)` with plain setters.
2. **Persisted store** — wraps with `persist` + `devtools` middleware (e.g. `userStore`, keyed to `localStorage`).

Export named selectors from the store file (e.g. `useUserProfile`) using `useShallow` for object selectors to avoid unnecessary re-renders.

Some stores (e.g. `chatStore`) hydrate from IndexedDB (Dexie) at module load time and sync via a `dbEventEmitter` — do not add server-side logic to those stores.

## Types

Types are split into three directories:

- `src/types/api/` — shapes returned directly from the backend API
- `src/types/features/` — domain/UI types (messages, todos, calendar, workflows, etc.)
- `src/types/shared/` — cross-cutting types used in multiple features (files, modals, content, search)

**Before creating a new type, search `src/types/` first.** Many common types already exist. Do not duplicate types.

## Styling

- TailwindCSS v4 (PostCSS plugin, not the Vite plugin).
- Use `tailwind-merge` (`twMerge`) to merge conditional class names; use `clsx` for conditionals.
- `class-variance-authority` (CVA) for variant-based component APIs.
- HeroUI and Radix UI are both present — prefer HeroUI for standard UI primitives before reaching for Radix directly.
- **Always use HeroUI components over raw HTML elements.** Use `<Button>` instead of `<button>`, `<Link>` (HeroUI or Next.js) instead of `<a>`, `<Divider>` instead of `<hr>`, `<Tooltip>` instead of custom hover states, `<Spinner>` / `<Skeleton>` instead of custom loaders, `<Dropdown>` / `<DropdownMenu>` / `<DropdownItem>` instead of hand-rolled dropdown state + click-outside handlers. Only reach for raw HTML when there is no HeroUI equivalent. HeroUI docs: https://v2.heroui.com/docs/guide/introduction
- **Never use icon components as spinners** (e.g. `Loading02Icon` with `animate-spin`). Always use `<Spinner>` from `@heroui/spinner` for loading states, or `<Skeleton>` from `@heroui/skeleton` for content placeholders. Icon-based spinners look wrong and are not consistent with the design system.

## i18n

`next-intl` v4 with the `[locale]` segment. Config lives in `src/i18n/`:

- `config.ts` — locale list (`en`, `es`, `fr`, `de`, `ja`, `ko`, `pt-BR`) and `defaultLocale = "en"`
- `routing.ts` — `localePrefix: "as-needed"` (default locale has no prefix in URL)
- `request.ts` — server-side locale resolution passed to `createNextIntlPlugin`
- `navigation.ts` — typed `Link`, `useRouter`, `usePathname` wrappers; always import navigation helpers from here, not from `next/navigation`

Use `loadFeatureTranslations` to lazy-load per-feature message files rather than bundling all translations upfront.

## Non-obvious Patterns

**Icons** — import from `@icons` (aliased to `@theexperiencecompany/gaia-icons/solid-rounded`). The alias is set in both `next.config.mjs` (webpack + turbopack) and `tsconfig.json`. To swap the icon variant globally, change the alias value in `next.config.mjs` — one place changes everything.

**Standalone output** — `output: "standalone"` is required so the Electron desktop app can bundle the Next.js build. Do not remove it.

**Sentry** — auto-instrumentation is intentionally disabled (`autoInstrumentServerFunctions: false`, etc.) to prevent OpenTelemetry leaking into the bundle. Do not re-enable without checking bundle impact.

**OpenNext / Cloudflare** — `@opennextjs/cloudflare` is a dependency and `deploy`/`preview` scripts target Cloudflare Workers. The `cloudflare-env.d.ts` file is generated by `wrangler types`.

**PostHog proxy** — `/ingest/*` rewrites proxy analytics to PostHog. `skipTrailingSlashRedirect: true` is required for this.

**Console logs** — stripped in production builds (except `console.error`) via Next.js compiler config. Do not rely on `console.log` for production debugging.

**Icon paths** — `src/config/iconPaths.generated.ts` and `.json` are auto-generated by `scripts/extract-icon-paths.ts` (run as `prebuild`). Do not edit them manually.

**Bundle analysis** — run `ANALYZE=true pnpm build` to open the bundle analyzer.

## Code Rules

- No inline imports — all imports at the top of the file.
- Never use the `any` type.
- Do not create test cases unless explicitly asked.
- **Do not run `nx build web` or `pnpm build`** unless explicitly asked — builds are slow and not needed during development.
- Biome handles both linting and formatting — do not add ESLint or Prettier config.
- Strict TypeScript (`strict: true`). Path alias `@/` maps to `src/`.
- `@shared/*` maps to `libs/shared/ts/src/` for shared TypeScript utilities.
