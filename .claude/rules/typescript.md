---
description: TypeScript, React, and frontend architecture standards for this codebase
paths:
  - "**/*.ts"
  - "**/*.tsx"
---

# TypeScript / React Standards

## Tooling

- **Biome** for linting and formatting — never ESLint or Prettier
- **TypeScript strict mode** — `strict: true` in tsconfig
- Line width: 80 characters, 2 spaces, LF, double quotes
- Run `nx lint web` and `nx type-check web` after every change

## Imports

- All imports at the **top of the file** — no inline or dynamic `require()`
- Import order:
  1. React / framework (`react`, `next/*`)
  2. Third-party libraries
  3. Internal absolute imports (`@/components`, `@/features`, `@shared/*`)
  4. Relative imports (`./`, `../`)
  5. Type-only imports last (`import type { ... }`)
- Use `import type` for type-only imports — Biome enforces `useImportType`
- Use `@/` for everything under `src/` — never climb more than one level with relative paths
- **Icons come exclusively from `@icons`** — never write raw SVGs or import SVG files directly

```typescript
import { useState } from "react";
import { create } from "zustand";
import { Button } from "@/components/ui/button";
import { useChatStore } from "@/stores/chatStore";
import type { IConversation } from "@/types";
```

## Types

- **Never use `any`** — use `unknown` and narrow, or define a proper type
- **Never use non-null assertion (`!`)** without proof it cannot be null
- **Before creating a new type, search `src/types/` first** — reuse existing types, do not duplicate
- Define types in the appropriate location:
  - Shared/global types → `src/types/`
  - Feature-specific types → `src/features/{feature}/types.ts` or co-locate with the file
  - API response shapes → `src/types/api/`
- Prefer `interface` for object shapes, `type` for unions/intersections/aliases
- Always type function return values explicitly when not trivially inferred
- Use type guards (`val is MyType`) over casting (`as MyType`) — casting masks bugs

## React Components

Components render. Hooks think.

- **Named exports only** — no default exports for components
- Add `"use client"` **only** when the component uses browser APIs, event handlers, or hooks — prefer Server Components
- Type props with an `interface` defined directly above the component
- Destructure props in the function signature
- Keep components under ~150 lines — split if larger
- A component should contain layout, conditional rendering, and event wiring — nothing else
- All data fetching, transformation, side effects, and business logic live in custom hooks
- If a component has more than one or two `useState` calls or a `useEffect`, extract a hook

```typescript
// wrong — logic living in the component
export function TodoList() {
  const [todos, setTodos] = useState([]);
  useEffect(() => { fetch("/api/todos").then(...) }, []);
  const filtered = todos.filter(t => !t.done);
}

// correct — component is pure layout
export function TodoList() {
  const { todos, isLoading } = useTodos();
}
```

## Hooks

- Always called at the top level — never inside loops, conditions, or nested functions
- Custom hooks live in `src/hooks/` or `src/features/{feature}/hooks/`
- Always prefix with `use`
- Always provide dependency arrays for `useEffect` and `useCallback`
- Include cleanup in `useEffect` when subscribing to events or timers

## API Layer

Never call `fetch` or `axios` directly from components or hooks.

- All HTTP calls go through `apiService` from `@/lib/api/service`
- It handles auth headers, error extraction, toast notifications, and analytics automatically
- Use `silent: true` on polling/background requests to suppress toasts
- For SSE streaming, use `fetchEventSource` via the pattern established in `chatApi.ts`

```typescript
// wrong
const res = await fetch("/api/todos");

// correct
const todos = await apiService.get<Todo[]>("/api/todos");
```

## State Management (Zustand)

- One store file per domain, exports a single `use{Name}Store` hook
- Single `interface` covers both state fields and action methods
- Use `set()` only — never mutate state directly
- Wrap stores with `devtools` — pass a readable action name as the 3rd arg to every `set()` call
- Wrap persisted stores with `persist` + a `partialize` function — never persist derived or volatile state
- Use `useShallow` for selectors that return objects or arrays — prevents unnecessary re-renders
- Optimistic mutations: capture current value, apply immediately, roll back on error

```typescript
// optimistic update + rollback
updateTodo: async (id, patch) => {
  const prev = get().todos.find(t => t.id === id);
  set({ todos: get().todos.map(t => t.id === id ? { ...t, ...patch } : t) }, false, "updateTodo");
  try {
    await todoApi.update(id, patch);
  } catch {
    set({ todos: get().todos.map(t => t.id === id ? prev! : t) }, false, "updateTodo/rollback");
  }
}
```

### Derived State

Never store derived state. If a value can be computed from existing state, compute it.

- Use `useMemo` for expensive derivations, inline expressions for cheap ones
- If two `set()` calls always change in sync, one of them is probably derived

### Heavy Data (IndexedDB)

React state and Zustand are not appropriate for large, persistent datasets.

- Message history lives in IndexedDB — not in a Zustand array
- Use the `dbEventEmitter` pattern to sync IndexedDB changes into Zustand reactively
- Hydrate stores from IndexedDB on module load (not in `useEffect`) to avoid flicker

## Feature Module Structure

Every feature follows the same layout. Do not invent new structures.

```
src/features/{feature}/
├── api/           # API calls using apiService
├── components/    # UI components (dumb, layout only)
├── hooks/         # Custom hooks (logic lives here)
├── stores/        # Zustand stores if feature-scoped
├── types/         # Feature-specific types
├── utils/         # Pure utility functions
├── constants.ts   # Feature constants
└── index.ts       # Barrel export — everything public goes through here
```

- Do not reach into another feature's internals — consume only its `index.ts` exports
- Global/shared types live in `src/types/` — feature types live co-located with the feature

## Performance

- Wrap callbacks passed to child components in `useCallback` with correct deps
- Wrap expensive computations in `useMemo`
- Wrap components that receive stable props but re-render often in `React.memo`
- Use Zustand `useShallow` selectors — subscribing to an object without it re-renders on every store update

## Error Boundaries

- Every major feature area that renders independently should be wrapped in an `ErrorBoundary`
- Error boundaries live in `src/components/shared/ErrorBoundary.tsx` — do not create new ones
- They catch rendering errors and report to PostHog automatically

## HeroUI Components

Always use HeroUI components instead of raw HTML or custom implementations. HeroUI handles accessibility, keyboard navigation, focus management, and theming automatically.

**Docs**: https://v2.heroui.com/docs/guide/introduction

| Need | HeroUI component | Never use |
|---|---|---|
| Button / icon button | `<Button>`, `<Button isIconOnly>` from `@heroui/button` | `<button>` |
| Link | `<Link>` from `@heroui/link` | `<a>` |
| Dropdown menu | `<Dropdown>` + `<DropdownTrigger>` + `<DropdownMenu>` + `<DropdownItem>` from `@heroui/dropdown` | Manual state + click-outside handler |
| Tooltip | `<Tooltip>` from `@heroui/tooltip` | Custom hover state |
| Modal / dialog | `<Modal>` + `<ModalContent>` from `@heroui/modal` | Custom overlay + z-index |
| Divider | `<Divider>` from `@heroui/divider` | `<hr>` |
| Loading spinner | `<Spinner>` from `@heroui/spinner` | Icon with `animate-spin` |
| Skeleton placeholder | `<Skeleton>` from `@heroui/skeleton` | Custom shimmer div |
| Select / combobox | `<Select>` + `<SelectItem>` from `@heroui/select` | `<select>` |
| Input | `<Input>` from `@heroui/input` | `<input>` |
| Checkbox | `<Checkbox>` from `@heroui/checkbox` | `<input type="checkbox">` |
| Tabs | `<Tabs>` + `<Tab>` from `@heroui/tabs` | Manual active-tab state |
| Accordion | `<Accordion>` + `<AccordionItem>` from `@heroui/accordion` | Manual expand state |

**`DropdownTrigger` rule**: always pass a HeroUI `<Button>` (or component using `useButton`) as the child — never a raw `<button>` or `<div>`. HeroUI propagates `onPress`, `ref`, and ARIA attributes to its own Button; raw elements miss keyboard/accessibility wiring.

```tsx
// correct
<DropdownTrigger>
  <Button isIconOnly variant="light" size="sm" aria-label="Options">
    <MoreVerticalIcon size={16} />
  </Button>
</DropdownTrigger>

// wrong — raw button misses HeroUI's press/focus handling
<DropdownTrigger>
  <button type="button">...</button>
</DropdownTrigger>
```

Use HeroUI variant/color props before reaching for `className` overrides. Custom `classNames` are acceptable only for one-off layout adjustments (`w-full`, `max-w-*`) — never to override HeroUI's internal color or shape tokens.

## Styling

- **TailwindCSS exclusively** — no inline `style={{}}`, no CSS modules
- Use Framer Motion (`motion/react`) for transitions, `AnimatePresence` required for exit animations
- Tokens, card contract, `cn()` / `cva`, status colors, animation classes, easing: see **`DESIGN.md`**

## File & Naming Conventions

| Thing | Convention | Example |
|---|---|---|
| Component files | PascalCase | `UserCard.tsx` |
| Hook files | camelCase | `useMediaQuery.ts` |
| Utility files | camelCase | `formatDate.ts` |
| Store files | camelCase + `Store` | `chatStore.ts` |
| Type files | camelCase | `notifications.ts` |
| Component names | PascalCase | `export function UserCard` |
| Functions / variables | camelCase | `const fetchUser` |
| Constants | UPPER_SNAKE_CASE | `const MAX_RETRIES = 3` |
| Enum members | UPPER_SNAKE_CASE | `NotificationSource.AI_EMAIL_DRAFT` |

## Next.js Specifics

- Prefer Server Components — `"use client"` only when required
- Route handlers in `src/app/api/` use `NextRequest` / `NextResponse`
- `page.tsx` files use default export (Next.js requirement) — everything else named exports
- Data-fetching belongs in Server Components; pass data as props

## Anti-Patterns

- No array index as React key — use stable unique IDs (`noArrayIndexKey` is a Biome error)
- No `console.log` in committed code
- No prop drilling more than 2 levels — lift to Zustand or use composition
- No `useEffect` for data derivable from existing state
- No raw SVGs — use `@icons` exclusively
