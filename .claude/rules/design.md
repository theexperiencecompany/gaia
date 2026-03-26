---
description: Design system rules — tokens, colors, components, card contract, animations, icons
paths:
  - "**/*.tsx"
  - "**/*.ts"
  - "**/*.css"
---

# Design System Rules

Full reference: **`DESIGN.md`** at the repo root.
Chat bubble / OpenUI architecture: `apps/web/src/features/chat/components/bubbles/bot/CLAUDE.md`

---

## Card Contract (most violated rule)

All data cards, tool sections, and info panels follow this exactly:

```tsx
// Outer container
<div className="rounded-2xl bg-zinc-800 p-4 w-fit min-w-[400px]">
  // Inner items
  <div className="rounded-2xl bg-zinc-900 p-3">
```

| Layer | Classes |
|---|---|
| Outer | `rounded-2xl bg-zinc-800 p-4 w-fit min-w-[400px]` |
| Outer (accordion) | `rounded-2xl bg-zinc-800 p-3 py-0` |
| Inner item | `rounded-2xl bg-zinc-900 p-3` |
| Inner item (compact) | `rounded-xl bg-zinc-900 p-3` |
| Section header | `text-sm font-semibold text-zinc-100 mb-3` |
| Item title | `text-sm font-medium text-zinc-200` |
| Body text | `text-xs text-zinc-400` |
| Meta / timestamp | `text-xs text-zinc-500` |
| Item spacing | `space-y-2` |

**Hard rules:**
- Never `border-`, `ring-`, or `outline-` anywhere in a card tree
- `rounded-2xl` on outer containers always — never `rounded-lg` for cards
- Depth comes from `zinc-800 → zinc-900` layering only

---

## Colors

**Layout surfaces** → `bg-background text-foreground` (auto dark/light via CSS vars)
**Dark cards** → zinc directly (`bg-zinc-800`, `bg-zinc-900`) — never CSS variables here

### Status Colors — always `/10` opacity

```tsx
bg-emerald-400/10 text-emerald-400  // success
bg-amber-400/10  text-amber-400     // warning
bg-red-400/10    text-red-400       // error
bg-blue-400/10   text-blue-400      // info
bg-zinc-700/50   text-zinc-400      // pending
```

Never solid color backgrounds for status badges.

### Zinc Text Scale (on dark surfaces)

```
text-zinc-100  primary text / section headers
text-zinc-200  item titles
text-zinc-400  body / secondary
text-zinc-500  meta / timestamps
```

---

## Icons

All icons from `@icons` (`@theexperiencecompany/gaia-icons`). **Never raw SVGs.**

```typescript
import { CheckmarkCircle02Icon, Copy01Icon } from "@icons";

// In a button
<Copy01Icon className="h-4 w-4" />

// In a badge/chip
<Alert01Icon height={17} />
```

Sizing: inline/badge → `height={17}`, actions → `size={16}`, decorative → `size={24}`

---

## Toasts / Notifications

Library: **Sileo** — already mounted globally. Never add `<Toaster>` or import from `sonner` / `react-hot-toast`.

---

## Animations

### Framer Motion

Import from `motion/react` — **not** `framer-motion`.

```typescript
import { AnimatePresence, m } from "motion/react";

<AnimatePresence mode="wait">
  {visible && (
    <m.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      {content}
    </m.div>
  )}
</AnimatePresence>
```

`AnimatePresence` is required for exit animations — never skip it.
Durations: ≤ 300ms micro-interactions, ≤ 500ms entrances.

### Transitions

Default: `transition-all duration-200`. Button press: `active:scale-95 transition-all! duration-300`.

---

## Styling Utilities

```typescript
import { cn } from "@/lib/utils";
// Always use cn() for conditional class merging — never string concatenation
<div className={cn("base", condition && "extra", className)} />
```

Use `cva` from `class-variance-authority` for multi-variant components.

---

## Component Library Choices

| Need | Use |
|---|---|
| Confirmation, focused form | `Dialog` (Shadcn) |
| Side panel, settings | `Sheet` (Shadcn) |
| Inline picker, contextual detail | `Popover` (Shadcn) |
| Hover label only | `Tooltip` (Shadcn) |
| Action list | `DropdownMenu` / `ContextMenu` (Shadcn) |
| Status badges | `Chip variant="flat"` (HeroUI) |
| Progress bars | `Progress` (HeroUI) |
| Tabbed card content | `Tabs/Tab` (HeroUI) |

Chart palette (Recharts): `["#a78bfa", "#34d399", "#60a5fa", "#f472b6", "#fb923c"]`

---

## OpenUI Components

OpenUI components must match the card contract above exactly. They render **outside** the `imessage-bubble` wrapper — never inside it (both use `bg-zinc-800`, so inner rendering makes them invisible).

See `apps/web/src/features/chat/components/bubbles/bot/CLAUDE.md` for the full OpenUI lifecycle, rendering paths, and component addition checklist.

---

## Typography

| Class | Font | Use |
|---|---|---|
| `font-sans` | Inter | All UI |
| `font-serif` | PP Editorial New | Editorial headings |
| `font-mono` | Anonymous Pro | Code, technical |

Never set `font-family` inline — use the Tailwind class.
