# Bot Bubble Component Styling Guide

Derived from reading: TodoSection, NotificationListSection, SearchResultsTabs, RedditPostSection,
EmailComposeSection, EmailThreadCard, SupportTicketSection, CalendarEventSection.

---

## 1. Styling Contract

| Role | Exact Tailwind Classes |
|---|---|
| Outer card container | `rounded-2xl bg-zinc-800 p-4` |
| Outer card (accordion variant) | `rounded-2xl bg-zinc-800 p-3 py-0` |
| Inner row / item | `rounded-2xl bg-zinc-900 p-3` |
| Inner row (compact) | `rounded-xl bg-zinc-900 p-3` |
| Section header text | `text-sm font-semibold text-zinc-100 mb-3` |
| Item title | `text-sm font-medium text-zinc-200` |
| Item title (prominent) | `text-sm font-medium text-zinc-100` |
| Secondary / body text | `text-xs text-zinc-400` |
| Meta / timestamp | `text-xs text-zinc-500` |
| Item spacing | `space-y-2` |
| Flex / grid gap | `gap-2` |
| Width (default) | `w-fit min-w-[400px]` (or `w-full`) |
| Border radius only | `rounded-2xl` — never `rounded-lg`, `rounded-xl` at card level |
| Borders | NONE — never `border-`, `ring-`, `outline-` |
| Status: success | `bg-emerald-400/10 text-emerald-400` |
| Status: warning | `bg-amber-400/10 text-amber-400` |
| Status: error/danger | `bg-red-400/10 text-red-400` |
| Status: info | `bg-blue-400/10 text-blue-400` |
| Status: pending | `bg-zinc-700/50 text-zinc-400` |
| Priority high (TodoSection) | `bg-red-500/10 text-red-500` |
| Priority medium (TodoSection) | `bg-yellow-500/10 text-yellow-500` |
| Priority low (TodoSection) | `bg-blue-500/10 text-blue-500` |
| Badge / pill (inline) | `rounded-full px-2 py-0.5 text-xs` + status color |
| Chart colors (recharts) | `["#a78bfa", "#34d399", "#60a5fa", "#f472b6", "#fb923c"]` |

**Rules extracted from source:**
- `rounded-2xl` on all outer cards, `rounded-xl` acceptable only on inner items
- `bg-zinc-800` outer, `bg-zinc-900` inner — this two-level depth is consistent everywhere
- No borders or outlines anywhere in the card tree (confirmed across all 8 components)
- `w-fit` + `min-w-[...]` pattern for sizing (TodoSection uses `min-w-[400px]`, `min-w-[450px]`)
- HeroUI `Chip`, `Button`, `Accordion`, `AccordionItem`, `Progress`, `Tabs`, `Tab`, `Avatar` are all used
- `Chip variant="flat"` is the standard chip style throughout
- `Button variant="flat"` or `variant="solid"` for actions
- `ScrollShadow` wraps any list that might overflow

---

## 2. How to Add a Native Tool Card (TOOL_RENDERERS path)

Native tool cards are for **known GAIA tools with structured backend data** (e.g. calendar, email, todos).

### Files to create / modify

1. **Create a section component** in this directory:
   `apps/web/src/features/chat/components/bubbles/bot/MyToolSection.tsx`

   Follow the styling contract above. Use `bg-zinc-800` outer, `bg-zinc-900` inner.

2. **Register it in TOOL_RENDERERS** — find the renderer map:
   `apps/web/src/features/chat/components/bubbles/bot/ToolDataRenderer.tsx` (or similar)

   Add an entry: `my_tool_data: (data) => <MyToolSection {...data} />`

3. **Add the tool name to `tool_fields`** in:
   `apps/api/app/models/chat_models.py`

   This prevents the backend from stripping the field before it reaches the frontend.

4. **Do NOT add an OpenUI component** for this tool. Once it is in `tool_fields`, it is on the suppression list and the LLM will never emit `:::openui` for it.

### Styling rules for native tool cards

- Outer container: `rounded-2xl bg-zinc-800 p-4`
- Inner items: `rounded-2xl bg-zinc-900 p-3` (use `space-y-2` between items)
- Header: `text-sm font-semibold text-zinc-100 mb-3`
- Never add `border-`, `ring-`, or `outline-` classes
- Use `w-fit min-w-[400px]` unless the card should be full-width (`w-full`)

---

## 3. How to Add a genericLibrary OpenUI Primitive

OpenUI primitives are for **MCP tools, third-party integrations, and any unknown tool output**.

### File location

`apps/web/src/config/openui/genericLibrary.ts`

### Pattern

```typescript
// 1. Define a Zod schema
const myComponentSchema = z.object({
  title: z.string(),
  items: z.array(z.object({ label: z.string(), value: z.string() })),
});

// 2. Define the React component (exported with View suffix for preview page)
export function MyComponentView(props: z.infer<typeof myComponentSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      <div className="space-y-2">
        {props.items.map((item, i) => (
          <div key={i} className="rounded-2xl bg-zinc-900 p-3">
            <span className="text-sm font-medium text-zinc-200">{item.label}</span>
            <span className="text-xs text-zinc-400 ml-2">{item.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// 3. Call defineComponent
const myComponentDef = defineComponent({
  name: "MyComponent",
  description: "Short description for the LLM",
  schema: myComponentSchema,
  component: ({ props }) => React.createElement(MyComponentView, props),
});

// 4. Add to the appropriate componentGroup in createLibrary(...)
```

### Adding to the component group

In `createLibrary({ components: [...], componentGroups: [...] })`, add the name to the
correct group array and export the definition in `components: [...]`.

### Updating the LLM prompt

Add a documentation entry in `apps/api/app/agents/prompts/openui_prompts.py` under
`OPENUI_COMPONENT_LIBRARY_PROMPT` following the format of existing entries.

---

## 4. Decision Rule: Native Tool Card vs OpenUI Primitive

```
Does the backend already emit a structured field for this tool?
  YES → tool is (or should be) in tool_fields in chat_models.py
       → Build a native tool card in this directory
       → Register in TOOL_RENDERERS
       → NEVER add an OpenUI component for it
       → LLM suppression list (OPENUI_SUPPRESSED_TOOLS) is auto-generated from tool_fields

  NO  → MCP tool, third-party integration, or unknown output
       → Add a generic component to genericLibrary.ts
       → Document it in openui_prompts.py
       → LLM will emit :::openui for it automatically
```

**Key constraint:** A tool cannot be in both paths. If it is in `tool_fields`, it must never
have a corresponding OpenUI component — the suppression list enforces this at the LLM level.

---

## 5. Copy-Paste Example of a Correctly-Styled Component

```tsx
"use client";

import React from "react";

interface ExampleCardProps {
  title: string;
  items: Array<{ label: string; value: string; meta?: string }>;
  badge?: string;
}

export default function ExampleCard({ title, items, badge }: ExampleCardProps) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-fit min-w-[400px]">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-semibold text-zinc-100">{title}</p>
        {badge && (
          <span className="rounded-full bg-zinc-700/50 px-2 py-0.5 text-xs text-zinc-400">
            {badge}
          </span>
        )}
      </div>
      <div className="space-y-2">
        {items.map((item, i) => (
          <div key={i} className="rounded-2xl bg-zinc-900 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-zinc-200">
                {item.label}
              </span>
              <span className="text-sm text-zinc-400">{item.value}</span>
            </div>
            {item.meta && (
              <p className="text-xs text-zinc-500 mt-1">{item.meta}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
```

**Checklist before committing any card component:**
- [ ] Outer container: `rounded-2xl bg-zinc-800 p-4`
- [ ] Inner items: `rounded-2xl bg-zinc-900 p-3`
- [ ] Header: `text-sm font-semibold text-zinc-100 mb-3`
- [ ] No `border-`, `ring-`, or `outline-` classes anywhere
- [ ] `space-y-2` between items
- [ ] Status colors use `/10` opacity backgrounds with matching text color
- [ ] Width: `w-fit min-w-[...]` or `w-full` depending on context
