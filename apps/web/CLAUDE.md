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

Do not reach into another feature's internals — consume only what a feature exposes. Logic lives in hooks, not components (see React Components below).

## React Components

Components render. Hooks think.

- **Named exports only.** No default exports for components, except `page.tsx`, which Next.js requires to default-export.
- A component holds layout, conditional rendering, and event wiring — nothing else. All data fetching, transformation, side effects, and business logic live in custom hooks (`src/hooks/` or `src/features/<feature>/hooks/`, prefixed `use`).
- Add `"use client"` **only** when the component uses browser APIs, event handlers, or hooks. Prefer Server Components; data-fetching belongs in Server Components, passed down as props.
- Type props with an `interface` directly above the component; destructure props in the signature.
- Keep components under ~150 lines — split if larger.
- No prop drilling more than 2 levels — lift to Zustand or use composition.

## API Layer

Never call `fetch` or `axios` directly from components or hooks.

- All HTTP calls go through `apiService` from `@/lib/api/service`. It handles auth headers, error extraction, toast notifications, and analytics automatically.
- Use `silent: true` on polling/background requests to suppress toasts.
- For SSE streaming, use `fetchEventSource` via the pattern established in `chatApi.ts` — do not hand-roll an `EventSource`.

```ts
// wrong
const res = await fetch("/api/todos");
// correct
const todos = await apiService.get<Todo[]>("/api/todos");
```

## Error Boundaries

- Every major feature area that renders independently should be wrapped in an `ErrorBoundary`.
- Use the shared one at `src/components/shared/ErrorBoundary.tsx` — do not create new ones. It catches rendering errors and reports to PostHog automatically.

## State Management

Zustand (v5). Stores live in `src/stores/` and are named `use<Name>Store`.

Two patterns in use:

1. **Simple store** — `create<State>()(...)` with plain setters.
2. **Persisted store** — wraps with `persist` + `devtools` middleware (e.g. `userStore`, keyed to `localStorage`).

Export named selectors from the store file (e.g. `useUserProfile`) using `useShallow` for object selectors to avoid unnecessary re-renders.

Patterns that are not tool-enforced but required:

- **devtools action names** — pass a readable action name as the 3rd arg to every `set()` call (e.g. `set({ ... }, false, "updateTodo")`). This is what makes the Redux DevTools timeline legible.
- **partialize** — persisted stores must use a `partialize` function. Never persist derived or volatile state, only the minimal fields that must survive reload.
- **Optimistic mutations** — capture the current value, apply the change immediately, roll back to the captured value on error. Name the rollback `set()` accordingly (e.g. `"updateTodo/rollback"`).
- **Never store derived state.** If a value can be computed from existing state, compute it (`useMemo` for expensive derivations, inline for cheap ones). If two `set()` calls always change together, one of them is derived and should be removed.

Some stores (e.g. `chatStore`) hydrate from IndexedDB (Dexie) at module load time and sync via a `dbEventEmitter` — do not add server-side logic to those stores. React state and Zustand are not appropriate for large persistent datasets (e.g. message history) — that belongs in IndexedDB, synced back into the store via `dbEventEmitter`. Hydrate at module load, not in `useEffect`, to avoid flicker.

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
- **Never use icon components as spinners** (e.g. `Loading02Icon` with `animate-spin`). Always use `<Spinner>` from `@heroui/spinner` for loading states, or `<Skeleton>` from `@heroui/skeleton` for content placeholders. Icon-based spinners look wrong and are not consistent with the design system.
- Use Framer Motion (`motion/react`) for transitions; `AnimatePresence` is required for exit animations.
- Design tokens, the chat tool-card contract, status colors, `cn()` / `cva`, animation classes and easing live in **`DESIGN.md`** at the repo root — read it before writing UI, do not restate it here.

### HeroUI Components

Always use HeroUI over raw HTML or custom implementations. HeroUI handles accessibility, keyboard navigation, focus management, and theming for you. Only reach for raw HTML when there is no HeroUI equivalent. Docs: https://v2.heroui.com/docs/guide/introduction

| Need | HeroUI component | Never use |
|---|---|---|
| Button / icon button | `<Button>`, `<Button isIconOnly>` from `@heroui/button` | `<button>` |
| Link | `<Link>` from `@heroui/link` (or Next.js `Link`) | `<a>` |
| Dropdown menu | `<Dropdown>` + `<DropdownTrigger>` + `<DropdownMenu>` + `<DropdownItem>` from `@heroui/dropdown` | Manual state + click-outside handler |
| Tooltip | `<Tooltip>` from `@heroui/tooltip` | Custom hover state |
| Modal / dialog | `<Modal>` + `<ModalContent>` from `@heroui/modal` | Custom overlay + z-index |
| Divider | `<Divider>` from `@heroui/divider` | `<hr>` |
| Loading spinner | `<Spinner>` from `@heroui/spinner` | Icon with `animate-spin` |
| Skeleton placeholder | `<Skeleton>` from `@heroui/skeleton` | Custom shimmer div |
| Select / combobox | `<Select>` + `<SelectItem>` from `@heroui/select` | `<select>` |
| Input / textarea | `<Input>` / `<Textarea>` from `@heroui/input` | `<input>` / `<textarea>` |
| Checkbox | `<Checkbox>` from `@heroui/checkbox` | `<input type="checkbox">` |
| Tabs | `<Tabs>` + `<Tab>` from `@heroui/tabs` | Manual active-tab state |
| Accordion | `<Accordion>` + `<AccordionItem>` from `@heroui/accordion` | Manual expand state |

**`DropdownTrigger` rule** — always pass a HeroUI `<Button>` (or a component using `useButton`) as the child, never a raw `<button>` or `<div>`. HeroUI propagates `onPress`, `ref`, and ARIA attributes to its own Button; raw elements miss the keyboard/accessibility wiring.

**Do not override HeroUI default styling.** Use variant/color props (`variant="flat"`, `color="primary"`, etc.) first. Custom `classNames` / `className` / inline `style` are acceptable only for one-off layout adjustments (`w-full`, `max-w-*`) or when the user explicitly asks for a visual customisation — never to override HeroUI's internal color or shape tokens. Overrides make components fragile across theme changes and upgrades.

**OpenUI components** must render **outside** the `imessage-bubble` wrapper, never inside it. Both use `bg-zinc-800`, so rendering inside makes them invisible against the bubble. See `apps/web/src/config/openui/CLAUDE.md` for the full OpenUI lifecycle and component checklist.

## i18n

`next-intl` v4 with the `[locale]` segment. Config lives in `src/i18n/`:

- `config.ts` — locale list (`en`, `es`, `fr`, `de`, `ja`, `ko`, `pt-BR`) and `defaultLocale = "en"`
- `routing.ts` — `localePrefix: "as-needed"` (default locale has no prefix in URL)
- `request.ts` — server-side locale resolution passed to `createNextIntlPlugin`
- `navigation.ts` — locale-aware `Link`, `useRouter`, `usePathname`, `redirect` wrappers

**When to use `@/i18n/navigation` vs `next/navigation`:**

- **`@/i18n/navigation`** — only for SEO/landing/marketing pages under `(landing)/` that are crawled in multiple locales. These wrappers auto-prepend the locale prefix for non-default locales (e.g. `/fr/pricing`).
- **`next/navigation`** — for the authenticated app under `(main)/` (chat, onboarding, settings, todos, etc.). These routes are not indexed and always run in the default locale. Use `next/navigation` directly here — it's simpler and consistent with the rest of the app.

Use `loadFeatureTranslations` to lazy-load per-feature message files rather than bundling all translations upfront.

## Non-obvious Patterns

**Icons** — import from `@icons` (aliased to `@theexperiencecompany/gaia-icons/solid-rounded`). The alias is set in both `next.config.mjs` (webpack + turbopack) and `tsconfig.json`. To swap the icon variant globally, change the alias value in `next.config.mjs` — one place changes everything. Exception: use `ChevronRight` from `@/components/shared/icons` for chevron indicators — `@icons` does not have a chevron-right equivalent.

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
