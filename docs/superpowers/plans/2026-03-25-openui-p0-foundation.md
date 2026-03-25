# OpenUI P0 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unblock all OpenUI interactive functionality: upgrade to zod v4 (enabling proper library API), rewrite gaiaLibrary to use the official API, wire action buttons to the chat input, implement the action dispatcher for direct API calls, and add dual-mode migration infrastructure.

**Architecture:** Upgrade zod v3→v4 so `defineComponent`/`createLibrary` work natively; rewrite `gaiaLibrary.ts` to use the proper API (with component signature verified from package source after install); create `openUIActionDispatcher.ts` as a pure function that routes `ActionEvent`s to either `appendToInput` or direct API handlers; wire `OpenUIRenderer.tsx` to use `useAppendToInput` from the existing `composerStore`; add `MIGRATED_TOOLS` to backend settings for dual-mode rollout.

**Tech Stack:** TypeScript, React 19, zod v4, `@openuidev/react-lang@0.1.3`, zustand (`composerStore`), FastAPI/Pydantic (backend settings)

**Spec:** `docs/superpowers/specs/2026-03-25-openui-full-integration-design.md`

---

## File Map

| Action | File | Purpose |
|---|---|---|
| Modify | `apps/web/package.json` | Bump zod to v4 |
| Modify | `apps/web/src/features/workflows/schemas/workflowFormSchema.ts` | `.passthrough()` → `.catchall(z.unknown())` |
| Verify | `apps/web/src/features/blog/components/CreateBlogPage.tsx` | No breaking changes (simple string schemas) |
| Verify | `apps/web/src/features/workflows/components/WorkflowModal.tsx` | Uses zodResolver — no changes needed (hookform v5 supports zod v4) |
| Modify | `apps/web/src/features/mail/components/EmailComposeCard.tsx` | `error.errors` → `error.issues`; verify `.email()` still works |
| Modify | `apps/web/src/features/support/components/SupportTicketCard.tsx` | `error.errors` → `error.issues` |
| Rewrite | `apps/web/src/config/openui/gaiaLibrary.ts` | Use `defineComponent`/`createLibrary` with verified signature |
| Create | `apps/web/src/features/chat/actions/openUIActionDispatcher.ts` | Route `ActionEvent` to handlers |
| Modify | `apps/web/src/features/chat/components/interface/OpenUIRenderer.tsx` | Wire `useAppendToInput` + dispatcher |
| Modify | `apps/api/app/config/settings.py` | Add `MIGRATED_TOOLS: set[str]` |
| Modify | `apps/api/.env.example` | Document `MIGRATED_TOOLS` env var format |

---

## Task 1: Upgrade zod v3 → v4

**Files:**
- Modify: `apps/web/package.json`
- Modify: `apps/web/src/features/workflows/schemas/workflowFormSchema.ts`
- Modify: `apps/web/src/features/mail/components/EmailComposeCard.tsx`
- Modify: `apps/web/src/features/support/components/SupportTicketCard.tsx`

### Breaking changes this touches

| File | Change | Risk |
|---|---|---|
| `workflowFormSchema.ts` | `.passthrough()` deprecated → `.catchall(z.unknown())` | Low — same runtime behavior |
| `EmailComposeCard.tsx` | `error.errors` → `error.issues`; `.email()` stricter in v4 | Medium — email validation in production path |
| `SupportTicketCard.tsx` | `error.errors` → `error.issues` | Low — support form |

`@hookform/resolvers@5.2.2` natively supports zod v4. `WorkflowModal.tsx`, `CreateBlogPage.tsx`, `data/tools.ts`, and `timezoneUtils.ts` need no changes.

- [ ] **Step 1.1: Bump zod in package.json**

In `apps/web/package.json`, change:
```json
"zod": "^3.25.76",
```
to:
```json
"zod": "^4.0.0",
```

- [ ] **Step 1.2: Install**

```bash
cd /home/aryan/Downloads/project
pnpm install
```

Expected: lock file updates, no peer dependency errors.

- [ ] **Step 1.3: Fix workflowFormSchema.ts — `.passthrough()` → `.catchall()`**

In `apps/web/src/features/workflows/schemas/workflowFormSchema.ts`, change:

```typescript
// OLD
const integrationTriggerConfigSchema = z
  .object({
    type: z.string(),
    enabled: z.boolean(),
  })
  .passthrough();
```
to:
```typescript
// NEW — zod v4: explicit catchall instead of deprecated passthrough
const integrationTriggerConfigSchema = z
  .object({
    type: z.string(),
    enabled: z.boolean(),
  })
  .catchall(z.unknown());
```

- [ ] **Step 1.4: Fix EmailComposeCard.tsx — `error.errors` → `error.issues`**

In `apps/web/src/features/mail/components/EmailComposeCard.tsx`, zod v4 renames `ZodError.errors` to `ZodError.issues` (`.errors` is kept as a deprecated alias but TypeScript will flag it). Make all three occurrences explicit:

At line ~288:
```typescript
// OLD
error.errors.forEach((err) => {
// NEW
error.issues.forEach((err) => {
```

At line ~306:
```typescript
// OLD
setCustomEmailError(error.errors[0]?.message || "Invalid email");
// NEW
setCustomEmailError(error.issues[0]?.message || "Invalid email");
```

Also verify the `.email()` validation still handles typical emails correctly. Zod v4's `.email()` uses a stricter RFC validator but standard `user@domain.com` addresses all pass. The existing test addresses in the codebase are all standard format — no action needed, but confirm no edge cases in the component (look for any test email strings like `test+tag@domain.co.uk` etc.).

- [ ] **Step 1.5: Fix SupportTicketCard.tsx — `error.errors` → `error.issues`**

In `apps/web/src/features/support/components/SupportTicketCard.tsx`, at line ~158:
```typescript
// OLD
error.errors.forEach((err) => {
// NEW
error.issues.forEach((err) => {
```

- [ ] **Step 1.6: Run type-check**

```bash
cd /home/aryan/Downloads/project
nx type-check web
```

Expected: zero errors. If there are remaining `.errors` deprecation warnings, find them with:
```bash
grep -rn "\.errors\b" apps/web/src --include="*.ts" --include="*.tsx" | grep "ZodError\|error\."
```

- [ ] **Step 1.7: Commit**

```bash
git add apps/web/package.json pnpm-lock.yaml \
  apps/web/src/features/workflows/schemas/workflowFormSchema.ts \
  apps/web/src/features/mail/components/EmailComposeCard.tsx \
  apps/web/src/features/support/components/SupportTicketCard.tsx
git commit -m "chore: upgrade zod v3 → v4, update deprecated APIs"
```

---

## Task 2: Inspect defineComponent API and Rewrite gaiaLibrary.ts

**Files:**
- Rewrite: `apps/web/src/config/openui/gaiaLibrary.ts`

**Critical:** The current working `gaiaLibrary.ts` registers components with the signature `({ props }: { props: Record<string, unknown> })` — this is the internal calling convention the `Renderer` uses. Before rewriting, we must confirm whether `defineComponent`'s `component` prop receives the flat zod-inferred type OR the internal `{ props, renderNode }` shape. Get this wrong and the three working components silently break.

- [ ] **Step 2.1: Inspect the @openuidev/react-lang package source**

After `pnpm install` (done in Step 1.2), run:

```bash
# Find where the package is stored in pnpm's virtual store
find /home/aryan/Downloads/project -path "*/node_modules/@openuidev/react-lang" -type d 2>/dev/null | head -3
```

Then:
```bash
# Check what defineComponent does — specifically how it calls the component function
grep -A 20 "defineComponent" <path-from-above>/dist/index.js | head -40
```

**What to look for:** Does `defineComponent` call `config.component(props)` with the flat zod-inferred object, or `config.component({ props, renderNode })`?

- If it calls `config.component(props)` → component function receives flat inferred type → use **Variant A** below
- If it calls `config.component({ props, renderNode })` → must keep `({ props })` signature → use **Variant B** below

- [ ] **Step 2.2: Rewrite gaiaLibrary.ts using the correct variant**

Replace entire contents of `apps/web/src/config/openui/gaiaLibrary.ts`.

**VARIANT A** — if defineComponent passes flat props (component receives `z.infer<T>` directly):

```typescript
import { createLibrary, defineComponent } from "@openuidev/react-lang";
import React from "react";
import { z } from "zod";
import CalendarListCard from "@/features/calendar/components/CalendarListCard";
import SearchResultsTabs from "@/features/chat/components/bubbles/bot/SearchResultsTabs";
import { WeatherCard } from "@/features/weather/components/WeatherCard";
import type { CalendarFetchData } from "@/types/features/calendarTypes";
import type { SearchResults } from "@/types/features/searchTypes";
import type { WeatherData } from "@/types/features/weatherTypes";

// --- Zod Schemas ---

const weatherConditionSchema = z.object({
  id: z.number(),
  main: z.string(),
  description: z.string(),
  icon: z.string(),
});

const forecastDaySchema = z.object({
  date: z.string(),
  timestamp: z.number(),
  temp_min: z.number(),
  temp_max: z.number(),
  humidity: z.number(),
  weather: z.object({
    main: z.string(),
    description: z.string(),
    icon: z.string(),
  }),
});

const weatherDataSchema = z.object({
  coord: z.object({ lon: z.number(), lat: z.number() }),
  weather: z.array(weatherConditionSchema),
  base: z.string().optional(),
  main: z.object({
    temp: z.number(),
    feels_like: z.number(),
    temp_min: z.number(),
    temp_max: z.number(),
    pressure: z.number(),
    humidity: z.number(),
    sea_level: z.number().optional(),
    grnd_level: z.number().optional(),
  }),
  visibility: z.number().optional(),
  wind: z.object({
    speed: z.number(),
    deg: z.number(),
    gust: z.number().optional(),
  }),
  clouds: z.object({ all: z.number() }).optional(),
  dt: z.number(),
  sys: z.object({
    country: z.string(),
    sunrise: z.number(),
    sunset: z.number(),
  }),
  timezone: z.number(),
  id: z.number().optional(),
  name: z.string(),
  cod: z.number().optional(),
  location: z.object({
    city: z.string(),
    country: z.string().nullable(),
    region: z.string().nullable(),
  }),
  forecast: z.array(forecastDaySchema).optional(),
});

const calendarEventSchema = z.object({
  summary: z.string(),
  start_time: z.string(),
  end_time: z.string(),
  calendar_name: z.string(),
  background_color: z.string(),
});

const calendarListSchema = z.object({
  events: z.array(calendarEventSchema),
});

const webResultSchema = z.object({
  title: z.string(),
  url: z.string(),
  content: z.string(),
  score: z.number(),
  raw_content: z.string().optional(),
  favicon: z.string().optional(),
});

const newsResultSchema = z.object({
  title: z.string(),
  url: z.string(),
  content: z.string(),
  score: z.number(),
  raw_content: z.string().optional(),
  favicon: z.string().optional(),
});

const searchResultsSchema = z.object({
  web: z.array(webResultSchema).optional(),
  images: z.array(z.string()).optional(),
  news: z.array(newsResultSchema).optional(),
  answer: z.string().optional(),
  query: z.string().optional(),
  response_time: z.number().optional(),
  request_id: z.string().optional(),
});

// --- Component Definitions (Variant A: flat props) ---

const WeatherCardComponent = defineComponent({
  name: "WeatherCard",
  description: "Displays current weather conditions with temperature, forecast, and details for a location.",
  props: weatherDataSchema,
  component: (props) =>
    React.createElement(WeatherCard, { weatherData: props as unknown as WeatherData }),
});

const CalendarListCardComponent = defineComponent({
  name: "CalendarListCard",
  description: "Displays a list of calendar events with times, names, and calendar colors.",
  props: calendarListSchema,
  component: (props) =>
    React.createElement(CalendarListCard, { events: props.events as unknown as CalendarFetchData[] }),
});

const SearchResultsTabsComponent = defineComponent({
  name: "SearchResultsTabs",
  description: "Displays search results in tabs: web results, image gallery, and news articles.",
  props: searchResultsSchema,
  component: (props) =>
    React.createElement(SearchResultsTabs, { search_results: props as unknown as SearchResults }),
});

// --- Library ---

export const gaiaLibrary = createLibrary({
  components: [WeatherCardComponent, CalendarListCardComponent, SearchResultsTabsComponent],
  componentGroups: [
    {
      name: "Data Display",
      components: ["WeatherCard", "CalendarListCard", "SearchResultsTabs"],
      notes: [
        "Use these components to present tool results visually.",
        "Always pass the full data object from the tool result.",
        "The agent should still write natural conversational text before/after the component.",
      ],
    },
  ],
});
```

**VARIANT B** — if defineComponent passes `{ props, renderNode }` (same as current manual approach):

Same as Variant A above, but replace the three `component:` functions with:
```typescript
// WeatherCard
component: ({ props }: { props: Record<string, unknown> }) =>
  React.createElement(WeatherCard, { weatherData: props as unknown as WeatherData }),

// CalendarListCard
component: ({ props }: { props: Record<string, unknown> }) =>
  React.createElement(CalendarListCard, { events: (props as { events: CalendarFetchData[] }).events }),

// SearchResultsTabs
component: ({ props }: { props: Record<string, unknown> }) =>
  React.createElement(SearchResultsTabs, { search_results: props as unknown as SearchResults }),
```

- [ ] **Step 2.3: Type-check**

```bash
nx type-check web
```

Expected: zero errors. If TypeScript reports a type mismatch on the `component:` function argument, you chose the wrong variant — switch to the other one.

- [ ] **Step 2.4: Smoke test — confirm the three components still render**

With the dev server running (`nx dev web`, `nx dev api` with `ENABLE_OPENUI=true`), ask the agent for weather. The WeatherCard must render. If it renders a blank/broken component but no console error, you have the wrong variant. If the error boundary shows raw code, there is a parse error unrelated to the signature.

- [ ] **Step 2.5: Commit**

```bash
git add apps/web/src/config/openui/gaiaLibrary.ts
git commit -m "refactor: rewrite gaiaLibrary using defineComponent/createLibrary (zod v4)"
```

---

## Task 3: Create openUIActionDispatcher

**Files:**
- Create: `apps/web/src/features/chat/actions/openUIActionDispatcher.ts`

Pure routing function. Strips `action:`/`submit:` prefixes, routes to direct handlers (stubbed — implemented per-component in Phase 2) or built-ins.

- [ ] **Step 3.1: Create dispatcher**

Create `apps/web/src/features/chat/actions/openUIActionDispatcher.ts`:

```typescript
import type { ActionEvent } from "@openuidev/react-lang";

/**
 * Direct action handlers for OpenUI write-action components.
 * Each is implemented when its Phase 2 component is built.
 * Until then they warn and fall back to continue_conversation.
 */
type DirectActionHandler = (event: ActionEvent) => Promise<void>;

const DIRECT_HANDLERS: Record<string, DirectActionHandler> = {
  send_email: async (event) => {
    console.warn("[OpenUI] send_email handler not yet implemented", event);
  },
  delete_calendar_event: async (event) => {
    console.warn("[OpenUI] delete_calendar_event handler not yet implemented", event);
  },
  edit_calendar_event: async (event) => {
    console.warn("[OpenUI] edit_calendar_event handler not yet implemented", event);
  },
  create_calendar_event: async (event) => {
    console.warn("[OpenUI] create_calendar_event handler not yet implemented", event);
  },
  connect_integration: async (event) => {
    console.warn("[OpenUI] connect_integration handler not yet implemented", event);
  },
  create_todo: async (event) => {
    console.warn("[OpenUI] create_todo handler not yet implemented", event);
  },
  delete_todo: async (event) => {
    console.warn("[OpenUI] delete_todo handler not yet implemented", event);
  },
  complete_todo: async (event) => {
    console.warn("[OpenUI] complete_todo handler not yet implemented", event);
  },
};

/**
 * Dispatch an OpenUI ActionEvent to the appropriate handler.
 *
 * Strips both "action:" and "submit:" prefixes before routing.
 * Falls back to continue_conversation for unknown types.
 */
export async function dispatchOpenUIAction(
  event: ActionEvent,
  appendToInput: (text: string) => void,
): Promise<void> {
  const raw = event.type;

  // Normalize: strip "action:" or "submit:" prefix
  const type = raw.startsWith("action:")
    ? raw.slice("action:".length)
    : raw.startsWith("submit:")
      ? raw.slice("submit:".length)
      : raw;

  // continue_conversation — append message to chat input
  if (type === "continue_conversation") {
    if (event.humanFriendlyMessage) {
      appendToInput(event.humanFriendlyMessage);
    }
    return;
  }

  // open_url — open in new tab
  if (type === "open_url") {
    const url = event.params?.url as string | undefined;
    if (url) {
      window.open(url, "_blank", "noopener,noreferrer");
    }
    return;
  }

  // cancel — noop dismiss button
  if (type === "cancel") {
    return;
  }

  const handler = DIRECT_HANDLERS[type];
  if (handler) {
    await handler(event);
    return;
  }

  // Fallback: unknown action — treat as continue_conversation
  console.warn(`[OpenUI] Unknown action type: "${type}". Falling back to continue_conversation.`);
  if (event.humanFriendlyMessage) {
    appendToInput(event.humanFriendlyMessage);
  }
}
```

- [ ] **Step 3.2: Type-check**

```bash
nx type-check web
```

Expected: zero errors.

- [ ] **Step 3.3: Commit**

```bash
git add apps/web/src/features/chat/actions/openUIActionDispatcher.ts
git commit -m "feat: add openUIActionDispatcher for routing OpenUI ActionEvents"
```

---

## Task 4: Wire OpenUIRenderer

**Files:**
- Modify: `apps/web/src/features/chat/components/interface/OpenUIRenderer.tsx`

`useAppendToInput` is exported from `apps/web/src/stores/composerStore.ts:237`. This is the same hook `FollowUpActions.tsx` uses — follow that exact pattern.

- [ ] **Step 4.1: Rewrite OpenUIRenderer.tsx**

Replace entire file contents:

```typescript
import { type ActionEvent, Renderer } from "@openuidev/react-lang";
import React from "react";
import { dispatchOpenUIAction } from "@/features/chat/actions/openUIActionDispatcher";
import { gaiaLibrary } from "@/config/openui/gaiaLibrary";
import { useAppendToInput } from "@/stores/composerStore";

interface OpenUIRendererProps {
  code: string;
  isStreaming: boolean;
}

function OpenUIRendererInner({ code, isStreaming }: OpenUIRendererProps) {
  const appendToInput = useAppendToInput();

  const handleAction = React.useCallback(
    (event: ActionEvent) => {
      dispatchOpenUIAction(event, appendToInput);
    },
    [appendToInput],
  );

  return (
    <Renderer
      response={code}
      library={gaiaLibrary}
      isStreaming={isStreaming}
      onAction={handleAction}
    />
  );
}

class OpenUIErrorBoundary extends React.Component<
  { children: React.ReactNode; fallbackText: string },
  { hasError: boolean }
> {
  constructor(props: { children: React.ReactNode; fallbackText: string }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidUpdate(prevProps: { fallbackText: string }) {
    if (
      this.state.hasError &&
      prevProps.fallbackText !== this.props.fallbackText
    ) {
      this.setState({ hasError: false });
    }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[OpenUIRenderer] Render error:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <pre className="whitespace-pre-wrap text-sm text-zinc-400">
          {this.props.fallbackText}
        </pre>
      );
    }
    return this.props.children;
  }
}

export default function OpenUIRenderer({
  code,
  isStreaming,
}: OpenUIRendererProps) {
  return (
    <OpenUIErrorBoundary fallbackText={code}>
      <OpenUIRendererInner code={code} isStreaming={isStreaming} />
    </OpenUIErrorBoundary>
  );
}
```

- [ ] **Step 4.2: Type-check**

```bash
nx type-check web
```

Expected: zero errors.

- [ ] **Step 4.3: Commit**

```bash
git add apps/web/src/features/chat/components/interface/OpenUIRenderer.tsx
git commit -m "feat: wire OpenUIRenderer action handler to composerStore and dispatcher"
```

---

## Task 5: Add MIGRATED_TOOLS to Backend Settings

**Files:**
- Modify: `apps/api/app/config/settings.py`
- Modify: `apps/api/.env.example`

- [ ] **Step 5.1: Add MIGRATED_TOOLS to CommonSettings**

In `apps/api/app/config/settings.py`, find `ENABLE_OPENUI: bool = False` (~line 96) and add directly after it:

```python
# Tools that have been migrated to emit :::openui blocks instead of tool_data entries.
# Only active when ENABLE_OPENUI=True. Add tool names as they are migrated.
# Env var format (JSON array): MIGRATED_TOOLS='["todo_data","email_fetch_data"]'
MIGRATED_TOOLS: set[str] = set()
```

- [ ] **Step 5.2: Document in .env.example**

Find the ENABLE_OPENUI entry in `apps/api/.env.example` and add below it:

```bash
# Comma/JSON list of tool names migrated to OpenUI rendering (requires ENABLE_OPENUI=true)
# Example: MIGRATED_TOOLS='["todo_data","email_fetch_data"]'
MIGRATED_TOOLS=[]
```

- [ ] **Step 5.3: Verify settings load**

```bash
cd /home/aryan/Downloads/project/apps/api
uv run python -c "from app.config.settings import get_settings; s = get_settings(); print('OK — MIGRATED_TOOLS:', s.MIGRATED_TOOLS)"
```

Expected: `OK — MIGRATED_TOOLS: set()`

- [ ] **Step 5.4: Commit**

```bash
git add apps/api/app/config/settings.py apps/api/.env.example
git commit -m "feat: add MIGRATED_TOOLS setting for dual-mode OpenUI rollout"
```

---

## Task 6: Verify End-to-End (Manual)

No automated frontend tests exist. Verify the three existing components still work and action wiring is live.

- [ ] **Step 6.1: Enable OpenUI in dev env**

In `apps/api/.env`, set:
```
ENABLE_OPENUI=true
```

- [ ] **Step 6.2: Start dev servers**

```bash
nx dev web   # terminal 1
nx dev api   # terminal 2
```

- [ ] **Step 6.3: Test WeatherCard still renders**

Ask the agent: "What's the weather in San Francisco?"
Expected: WeatherCard renders inline with conversational text. No error boundary fallback.

- [ ] **Step 6.4: Verify the old console.warn is gone**

Open DevTools → Console. There should be NO message:
> `[OpenUIRenderer] continue_conversation action not yet wired`

If any OpenUI button is clicked, action flows through dispatcher now (either to appendToInput or to a stub handler's console.warn).

- [ ] **Step 6.5: Build check**

```bash
nx build web
```

Expected: clean build, no errors.

- [ ] **Step 6.6: Commit any fixes found during verification**

If issues were found and fixed, stage the specific files changed:
```bash
git add <specific files that were changed>
git commit -m "fix: address issues found during OpenUI P0 manual verification"
```

---

## Summary

After this plan:

| Feature | Status |
|---|---|
| zod v4 | ✅ Installed, all files migrated |
| `gaiaLibrary` | ✅ Uses `defineComponent`/`createLibrary` properly |
| `continue_conversation` | ✅ Wired to chat input via `useAppendToInput` |
| `action:` / `submit:` dispatch | ✅ Routes to direct handlers (stubs for Phase 2) |
| `open_url` | ✅ Opens URL in new tab |
| `cancel` | ✅ Noop |
| `MIGRATED_TOOLS` | ✅ Backend infrastructure ready |
| Phase 1 read-only components | ⏳ Next plan |
| Phase 2 write-action components | ⏳ After Phase 1 |
