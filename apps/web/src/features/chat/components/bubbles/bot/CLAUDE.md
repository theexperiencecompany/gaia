# OpenUI System — Maintenance Guide

This file explains the full lifecycle of OpenUI components: how they're built, how the LLM
generates them, and how to keep everything in sync.

---

## 1. What OpenUI Is

OpenUI is a lightweight DSL (domain-specific language) that lets the backend LLM emit rich
React components directly inside its text response.

**Flow:**

```
Backend LLM                Frontend (TextBubble)
──────────────────────     ──────────────────────────────────────────────
response text with         parseOpenUISegments() splits text at :::openui
:::openui fences     →     OpenUIRenderer passes code to @openuidev/react-lang
                           Renderer() parses the code, maps positional args
                           to named props, renders the React component from
                           genericLibrary.tsx
```

**Example backend output:**

```
Here are the results:

:::openui
root = ResultList([{"title": "Item A", "badge": "new"}, {"title": "Item B"}])
:::

Let me know if you need more detail.
```

**What the user sees:** "Here are the results:" in a chat bubble → ResultList card rendered
outside the bubble → "Let me know if you need more detail." in another chat bubble.

---

## 2. Why OpenUI Segments Render OUTSIDE the Bubble

`imessage-bubble imessage-from-them` has `background: #27272a` (zinc-800). All OpenUI
components use `bg-zinc-800` for their outer container — same color = invisible.

The fix (in `TextBubble.tsx`): mixed parts (markdown + openui) are split so that:
- Markdown segments → wrapped in `imessage-bubble`
- OpenUI segments → rendered at the same DOM level as TOOL_RENDERERS (outside any bubble)

**Never** render OpenUI components inside an `imessage-bubble` wrapper.

---

## 3. Two Rendering Paths — Know Which One You Need

```
Is this tool output already handled by a dedicated GAIA tool?
  YES → TOOL_RENDERERS path (native tool card)
        Files: TextBubble.tsx, apps/api/app/models/chat_models.py (tool_fields)
        The LLM will NEVER emit :::openui for suppressed tools.

  NO  → OpenUI path (generic component in genericLibrary.tsx)
        Files: genericLibrary.tsx, openui_prompts.py
        The LLM will emit :::openui and pick a component from the library.
```

A tool can only be in ONE path. Adding it to `tool_fields` (Python) automatically adds it to
`OPENUI_SUPPRESSED_TOOLS` and the LLM is told not to emit openui for it.

---

## 4. Styling Contract

All OpenUI components follow a lightweight card-less design - render clean, unboxed components that blend with the chat bubble. No heavy outer wrappers.

| Role                  | Exact Tailwind Classes                          |
|---|---|
| Outer container (when needed) | `rounded-2xl bg-zinc-800` — never `rounded-xl`, `rounded-3xl`, or any other radius. Padding is per-component (typical: `p-3` or `p-4`; charts can use `p-2`). |
| Inner content block   | `rounded-2xl bg-zinc-900 p-3` (only when needed) |
| Section header        | `text-sm font-semibold text-zinc-100` (no mb margin) |
| Item title            | `text-sm font-medium text-zinc-200`             |
| Secondary text        | `text-xs text-zinc-400`                         |
| Item spacing          | `space-y-2`                                     |
| Width                 | `w-full min-w-fit max-w-lg` (or `max-w-xl`)     |
| Borders and outer    | REMOVE - no outer `bg-zinc-800 p-4` wrappers   |
| Status colors        | Use HeroUI `Chip` components with status colors |

---

## 5. Adding a New OpenUI Component (End-to-End Checklist)

### Step 1 — Define the Zod schema in `genericLibrary.tsx`

```typescript
const myComponentSchema = z.object({
  title: z.string(),
  items: z.array(z.object({ label: z.string(), value: z.string() })),
  // Optional fields must use .optional()
});
```

Prop ORDER in the schema is the positional argument order the LLM will use.
Example: `root = MyComponent("Title", [{"label": "k", "value": "v"}])`

### Step 2 — Write the React component (export with `View` suffix)

```typescript
export function MyComponentView(props: z.infer<typeof myComponentSchema>) {
  return (
    <div className="w-full min-w-fit max-w-lg space-y-2">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100">{props.title}</p>
      )}
      <div className="space-y-2">
        {props.items.map((item, i) => (
          <div key={i} className="rounded-2xl bg-zinc-900 p-3">
            <span className="text-xs text-zinc-500">{item.label}</span>
            <span className="text-sm font-medium text-zinc-200 ml-2">
              {item.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

### Step 3 — Register with `defineComponent`

```typescript
const myComponentDef = defineComponent({
  name: "MyComponent",           // MUST match the name the LLM will use
  description: "Short description",
  props: myComponentSchema,
  component: ({ props }) => React.createElement(MyComponentView, props),
});
```

### Step 4 — Add to `createLibrary`

In `genericLibrary.tsx` at the bottom, add to:
1. `components: [...]` array
2. Appropriate `componentGroups[*].components` array

### Step 5 — Document in the backend prompt

In `apps/api/app/agents/prompts/openui_prompts.py`, add to `OPENUI_COMPONENT_LIBRARY_PROMPT`:

```
MyComponent(title, items)
  title: string; items: {label: string, value: string}[]
  Use for: <when the LLM should pick this component>
```

Format: `ComponentName(arg1, arg2, optionalArg?)` — positional order must match schema order.
Use `?` for optional args.

### Step 6 — Update the test file

In `apps/api/tests/test_openui_prompts.py`, add `"MyComponent"` to the components list in
`test_instructions_contains_all_component_names`.

### Step 7 — Verify

Run: `cd apps/api && uv run pytest tests/test_openui_prompts.py`

---

## 6. The Stack Layout Wrapper

`Stack([c1, c2, ...])` is a special container that renders multiple components vertically:

```
:::openui
root = Stack([gauge, card])
gauge = GaugeChart(73, "CPU Usage", 0, 100)
card = DataCard("Server", [{"label": "Status", "value": "healthy"}])
:::
```

Rules:
- `root` must always be defined first (or use forward reference)
- Variables are resolved before rendering
- Stack items can be any other component

---

## 7. LLM Prompt Rules (from `OPENUI_INSTRUCTIONS`)

The LLM follows these rules when emitting openui:

- First line MUST be `root = ComponentName(...)`
- Arguments are positional — never `name=value` syntax
- Use `null` to skip an optional middle argument
- Only emit openui for tool outputs NOT in the suppressed list
- Do NOT emit openui for greetings, opinions, or conversational text

**Suppressed tools** (auto-generated from `tool_fields` in `chat_models.py`) are listed at the
top of the `OPENUI_INSTRUCTIONS` string. The LLM is told to use the TOOL_RENDERERS for these.

---

## 8. Keeping Frontend and Backend in Sync

The most common drift: adding a component to `genericLibrary.tsx` but forgetting the backend
prompt (or vice versa).

**The test `test_instructions_contains_all_component_names` catches this.** If you add a
component to the frontend but forget to document it in `openui_prompts.py`, the test will fail.

Run tests after every component addition:
```bash
cd apps/api && uv run pytest tests/test_openui_prompts.py -v
```

**Checklist for keeping in sync:**

| Change | Frontend | Backend |
|---|---|---|
| New component | Add schema + view + def to `genericLibrary.tsx` | Document in `OPENUI_COMPONENT_LIBRARY_PROMPT` |
| Rename component | Update `defineComponent.name` + `componentGroups` | Update component name in prompt |
| Change arg order | Update schema field order | Update prompt signature |
| Remove component | Remove from `components[]` + `componentGroups` | Remove from prompt |
| Any of the above | — | Update test component list |

---

## 9. Async / External Data in Components

Some components need async initialization (e.g., `CodeDiff` loading Shiki via `@pierre/diffs`).
Use `useState` + `useEffect` pattern:

```typescript
export function CodeDiffView(props: z.infer<typeof codeDiffSchema>) {
  const [data, setData] = React.useState<SomeType | null>(null);

  React.useEffect(() => {
    // async work here
    setData(result);
  }, [props.relevantProp]);

  return data ? <ActualComponent data={data} /> : <LoadingPlaceholder />;
}
```

The component must render something during loading — never return `null` from the view.

---

## 10. Error Handling

The `OpenUIRenderer` wraps everything in an `OpenUIErrorBoundary`. If the React tree throws,
the boundary shows the raw openui code as a `<pre>` fallback.

However, if the **parser** fails silently (returns `result.root = null`), nothing is shown.
This happens when:
- A required argument is missing or null
- A component name in the openui code doesn't match any name in `genericLibrary.tsx`
- The code has syntax errors

To debug: open the browser console and look for `[openui] Parse error:` or
`[OpenUIRenderer] Render error:` logs.

---

## 11. Component Groups Reference

| Group              | Components                                                                                     |
|---|---|
| Layout & Data      | DataCard, ResultList, DataTable, ComparisonTable, StatusCard, ActionCard, TagGroup, FileTree, Accordion, TabsBlock, ProgressList, SelectableList, AvatarList, KbdBlock |
| Analytics          | StatRow, BarChart, LineChart, AreaChart, PieChart, ScatterChart, RadarChart, GaugeChart       |
| Content            | ImageBlock, ImageGallery, VideoBlock, AudioPlayer, MapBlock, CalendarMini, NumberTicker, Carousel, TreeView |
| Timeline           | Timeline, AlertBanner, Steps                                                                   |
| Code               | CodeDiff                                                                                       |
| Layout (internal)  | Stack (used in :::openui code only, not LLM-visible as a standalone)                         |
