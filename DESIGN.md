# GAIA Design System

The visual language for building any UI in this codebase. Covers tokens, patterns, and rules — not component internals or workflows.

**Related files:**
- Token source: `apps/web/src/app/styles/globals.css`
- Claude design rules: `.claude/rules/design.md` → points here
- Chat card contract + workflow: `apps/web/src/features/chat/components/bubbles/bot/CLAUDE.md`

---

## 1. Design Philosophy

- **Dark-first.** Primary experience is dark mode (`#111111` bg). Light mode supported via CSS variables but secondary.
- **Flat depth.** Depth comes from layered backgrounds (`zinc-800` → `zinc-900`), never borders or outlines.
- **Single accent.** One primary action color: `#00bbff` (cyan). Everything else is zinc-scale neutrals.
- **Borderless cards.** Data cards use background-only separation — no border, ring, or outline.
- **Subtle motion.** Animations are functional (entrance, exit, state change), not decorative.

---

## 2. Color System

### Brand Tokens

| Token | Value | Use |
|---|---|---|
| `--color-primary` | `#00bbff` | CTAs, user bubble, selection highlight, links |
| `--color-primary-foreground` | `#000000` | Text on primary backgrounds |
| `--color-primary-bg` | `#111111` | Main app background |
| `--color-secondary-bg` | `#1a1a1a` | Sidebar background |

### Semantic Variables (Shadcn / Radix)

Use on layout surfaces and standard components. Switch automatically between light and dark.

| Variable | Light | Dark |
|---|---|---|
| `--background` | `hsl(0 0% 100%)` | `hsl(224 71% 4%)` |
| `--foreground` | `hsl(222.2 47.4% 11.2%)` | `hsl(213 31% 91%)` |
| `--muted` | `hsl(210 40% 96.1%)` | `hsl(223 47% 11%)` |
| `--muted-foreground` | `hsl(215.4 16.3% 46.9%)` | `hsl(215.4 16.3% 56.9%)` |
| `--accent` | `hsl(210 40% 96.1%)` | `hsl(216 34% 17%)` |
| `--border` | `hsl(214.3 31.8% 91.4%)` | `hsl(216 34% 17%)` |
| `--ring` | `hsl(215 20.2% 65.1%)` | `hsl(216 34% 17%)` |
| `--destructive` | `hsl(0 100% 50%)` | `hsl(0 63% 31%)` |

### Zinc Scale (cards and dark surfaces)

Dark card surfaces use zinc directly — not CSS variables.

| Role | Class |
|---|---|
| Outer card background | `bg-zinc-800` |
| Inner item background | `bg-zinc-900` |
| Hover / secondary accent | `bg-zinc-700` |
| Primary text on dark | `text-zinc-100` |
| Item title | `text-zinc-200` |
| Body / secondary text | `text-zinc-400` |
| Meta / timestamps | `text-zinc-500` |

**Rule:** Layout surfaces → `bg-background / text-foreground`. Dark cards → zinc directly.

### Status Colors

Always `/10` opacity background with matching text. Never solid color backgrounds for status.

| Status | Background | Text |
|---|---|---|
| Success | `bg-emerald-400/10` | `text-emerald-400` |
| Warning | `bg-amber-400/10` | `text-amber-400` |
| Error | `bg-red-400/10` | `text-red-400` |
| Info | `bg-blue-400/10` | `text-blue-400` |
| Pending | `bg-zinc-700/50` | `text-zinc-400` |
| Priority high | `bg-red-500/10` | `text-red-500` |
| Priority medium | `bg-yellow-500/10` | `text-yellow-500` |
| Priority low | `bg-blue-500/10` | `text-blue-500` |

### Selection

```css
::selection { background: #00364b; color: #0bf; }
```

---

## 3. Typography

### Font Families

| Token | Family | Use |
|---|---|---|
| `font-sans` | Inter | All UI — body, labels, buttons, inputs |
| `font-serif` | PP Editorial New (200, 400) | Editorial headings, landing hero text |
| `font-mono` | Anonymous Pro | Code blocks, `<code>`, technical content |

Never set `font-family` inline. Use the Tailwind class.

### Heading Scale

Set globally — use semantic HTML tags, styles apply automatically.

```
h1 → text-3xl font-bold
h2 → text-2xl font-bold
h3 → text-xl font-bold
h4 → text-lg font-bold
h5 → text-base font-bold
h6 → text-sm font-bold
```

### Text Patterns

**Uppercase section labels** (settings panels, card headers, form groups):
```tsx
<p className="text-xs font-medium uppercase tracking-wider text-zinc-500">Section Title</p>
```

**Truncation** — always truncate long strings in constrained containers:
```tsx
<span className="truncate">...</span>           // single line
<p className="line-clamp-2">...</p>             // two lines max
<p className="line-clamp-1 max-w-[200px]">...</p>
```

### Code

Inline code gets `border-radius: 10px` and `padding: 4px` globally. Use `font-mono` or `.monospace` class.

---

## 4. Spacing

Consistent spacing values used across the codebase:

| Value | Use |
|---|---|
| `gap-1` / `gap-1.5` | Icon + label pairs |
| `gap-2` | Standard row items |
| `gap-3` | Section spacing inside cards |
| `space-y-2` | Vertical list of items inside a card |
| `p-3` | Inner card item padding |
| `p-4` | Outer card padding |
| `px-3` / `px-4` | Horizontal padding on inputs, buttons |

---

## 5. Border Radius

### Tokens

```
--radius: 0.5rem (8px) → rounded-md   — buttons, inputs, standard UI
```

### Decision Table

| Context | Class |
|---|---|
| Dark cards — outer | `rounded-2xl` (16px) |
| Dark cards — inner items | `rounded-2xl` or `rounded-xl` (12px) |
| Images | `rounded-3xl` (24px) |
| Buttons, inputs | `rounded-md` (6px) |
| Badges, pills | `rounded-full` |
| Context menus | `rounded-xl` (12px) |

Never use `rounded-lg` on card containers — that's the Shadcn base radius, visually too small for cards.

---

## 6. Depth & Elevation

Depth primarily via background layering and blur, not shadow.

| Context | Value |
|---|---|
| Buttons, inputs | `shadow-xs` |
| Dialogs, sheets | `shadow-lg` |
| Dark cards (solid) | No shadow — flat design |
| Dark cards (glass) | `bg-zinc-800/40 backdrop-blur-xl` — semi-transparent + blur |
| Hover on dark surfaces | `hover:bg-white/5` — subtle white overlay |

### Backdrop Blur Scale

| Level | Class | Use |
|---|---|---|
| Moderate | `backdrop-blur-lg` | Glass cards |
| Standard | `backdrop-blur-xl` | Panels overlaying content, floating cards |
| Maximum | `backdrop-blur-2xl` | Search overlays, full-screen modals |

---

## 7. Icons

All icons come from `@icons` (`@theexperiencecompany/gaia-icons`). Never raw SVGs.

```typescript
import { CheckmarkCircle02Icon, Alert01Icon, Copy01Icon } from "@icons";
```

Icons accept `className`, `height`, `width`, and `size` props.

### Sizing

| Context | Value |
|---|---|
| Inline (badges, text) | `height={17}` |
| Action buttons | `size={16}` |
| Prominent / decorative | `size={24}` |

### Patterns

```tsx
// In a button
<Button variant="ghost" size="icon">
  <Copy01Icon className="h-4 w-4" />
</Button>

// In a chip / badge
<Alert01Icon className="text-warning-500" height={17} />

// With hover animation
<SomeIcon className="transition-all duration-200 group-hover:scale-110" />
```

Icons are named `{Name}Icon` — e.g. `Brain02Icon`, `CheckmarkCircle01Icon`.

---

## 8. Animations

### Available Classes

| Class | Duration | Use |
|---|---|---|
| `animate-spin` | Infinite | Loading spinner |
| `animate-pulse` | Infinite | Skeleton placeholder |
| `animate-accordion-down` | 0.2s ease-out | Accordion open |
| `animate-accordion-up` | 0.2s ease-out | Accordion close |
| `animate-scale-in` | 0.4s bounce | Element entrance |
| `animate-scale-in-blur` | 0.5s bounce | Blurred entrance |
| `animate-shimmer` | 2s linear | Shimmer effect |
| `animate-shake` | 0.7s | Error shake |

### Transitions

Default: `transition-all duration-200`. Use this everywhere unless a specific property needs targeting.

| Scenario | Classes |
|---|---|
| All properties | `transition-all duration-200` |
| Color only | `transition-colors duration-200` |
| Button press | `active:scale-95 transition-all! duration-300` |

### Easing

| Name | Value | Use |
|---|---|---|
| Default | `ease` | Most transitions |
| Exit / entrance | `ease-out` | Entrances, exits |
| Bounce | `cubic-bezier(0.34, 1.56, 0.64, 1)` | `scale-in`, `scale-in-blur` |

### Framer Motion

Import from `motion/react` — not `framer-motion`.

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

`AnimatePresence` is required for exit animations. Keep durations ≤ 300ms for micro-interactions, ≤ 500ms for entrances.

---

## 9. Toast / Notifications

Library: **Sileo**. Already mounted globally — just call the toast function. Never add another `<Toaster>` or import from `sonner` / `react-hot-toast`.

Toast style: dark fill (`#262626`), white title, white/75 description, top-right position.

Action button colors are applied automatically by type: error → red, warning → amber, success → green, info → blue.

---

## 10. Styling Tools

### cn()

Use `cn()` from `@/lib/utils` for all conditional class merging. Never string concatenation.

```typescript
import { cn } from "@/lib/utils";

<div className={cn("base-class", condition && "conditional-class", className)} />
```

### cva

Use `cva` from `class-variance-authority` for components with multiple visual variants.

```typescript
import { cva } from "class-variance-authority";

const cardVariants = cva("rounded-2xl p-4", {
  variants: {
    depth: {
      outer: "bg-zinc-800",
      inner: "bg-zinc-900",
    },
  },
});
```

---

## 11. Component Library

### Shadcn (`src/components/ui/`)

Style: `new-york`, base: `zinc`, CSS variables on.

| Component | Key details |
|---|---|
| `Button` | Variants: `default`, `destructive`, `outline`, `secondary`, `ghost`, `link` · Sizes: `default`, `sm`, `lg`, `icon` |
| `Input` | `h-9 rounded-md shadow-xs` · focus ring · `aria-invalid` error state |
| `Textarea` | Same as Input · `min-h-16` · auto-height via `field-sizing-content` |
| `Dialog` | Zoom + fade entrance/exit — use for confirmations, forms requiring focus |
| `Sheet` | Fade-in slide panel — use for side panels, settings drawers |
| `Popover` | Anchored overlay — use for inline pickers, contextual options |
| `Tooltip` | Hover label only — no interactive content |
| `DropdownMenu` / `ContextMenu` | Action lists |
| `Accordion` | Animated expand/collapse |
| `Avatar` | `rounded-full`, image + fallback |
| `Skeleton` | `animate-pulse rounded-md` |
| `ScrollArea` | Radix scrollable with edge shadows |
| `Sidebar` | Collapsible, `Cmd/Ctrl+B` toggle, cookie-persisted |

### HeroUI (`@heroui/*`)

Used for richer UI inside cards.

| Component | Standard usage |
|---|---|
| `Chip` | Status badges · `variant="flat"` |
| `Button` | Card actions · `variant="flat"` or `variant="solid"` |
| `Accordion` / `AccordionItem` | Expandable card sections |
| `Progress` | Progress bars |
| `Tabs` / `Tab` | Tabbed card content |
| `Avatar` | Contact / user avatars |
| `ScrollShadow` | Wraps overflowing lists |

Chart palette (Recharts): `["#a78bfa", "#34d399", "#60a5fa", "#f472b6", "#fb923c"]`

### Overlay Hierarchy

Pick the right overlay for the context:

| Use case | Component |
|---|---|
| Destructive confirmation, focused form | `Dialog` |
| Side panel, settings, multi-step flow | `Sheet` |
| Inline picker, date selector, contextual detail | `Popover` |
| Single-line label on hover | `Tooltip` |
| Action list from a trigger | `DropdownMenu` |
| Right-click actions | `ContextMenu` |

---

## 12. Dark Card Styling Contract

All data cards, tool sections, and info panels use this. Two-tone zinc depth, no borders.

| Layer | Classes |
|---|---|
| Outer container | `rounded-2xl bg-zinc-800 p-4 w-fit min-w-[400px]` |
| Outer (accordion variant) | `rounded-2xl bg-zinc-800 p-3 py-0` |
| Inner item | `rounded-2xl bg-zinc-900 p-3` |
| Inner item (compact) | `rounded-xl bg-zinc-900 p-3` |
| Section header | `text-sm font-semibold text-zinc-100 mb-3` |
| Item title | `text-sm font-medium text-zinc-200` |
| Item title (prominent) | `text-sm font-medium text-zinc-100` |
| Body text | `text-xs text-zinc-400` |
| Meta / timestamp | `text-xs text-zinc-500` |
| Item spacing | `space-y-2` |
| Status badge | `rounded-full px-2 py-0.5 text-xs` + status color |
| Section divider | `<Divider className="bg-zinc-700/50" />` (HeroUI) |
| Glass variant | `rounded-2xl bg-zinc-800/40 p-4 backdrop-blur-xl` |
| Hoverable list item | `p-4 transition-all hover:bg-white/5` (no bg, just overlay on hover) |

**Constraints:**
- ❌ Never `border-`, `ring-`, `outline-` anywhere in the card tree
- ✅ `rounded-2xl` on outer containers always
- ✅ `zinc-800` outer → `zinc-900` inner — this two-tone is the entire separation mechanism
- ✅ Status colors always use `/10` opacity backgrounds

### Card Template

```tsx
"use client";

const statusClasses = {
  success: "bg-emerald-400/10 text-emerald-400",
  error: "bg-red-400/10 text-red-400",
  warning: "bg-amber-400/10 text-amber-400",
  info: "bg-blue-400/10 text-blue-400",
  pending: "bg-zinc-700/50 text-zinc-400",
} as const;

export default function MyCard({ title, items, badge }) {
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
        {items.map((item) => (
          <div key={item.id} className="rounded-2xl bg-zinc-900 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-zinc-200">{item.label}</span>
              <span className={`rounded-full px-2 py-0.5 text-xs ${statusClasses[item.status]}`}>
                {item.value}
              </span>
            </div>
            {item.meta && <p className="text-xs text-zinc-500 mt-1">{item.meta}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}
```

### New Card Checklist

- [ ] Outer: `rounded-2xl bg-zinc-800 p-4`
- [ ] Inner items: `rounded-2xl bg-zinc-900 p-3`
- [ ] No `border-`, `ring-`, `outline-` anywhere
- [ ] Icons from `@icons` only
- [ ] Status colors use `/10` opacity backgrounds
- [ ] Width: `w-fit min-w-[400px]` or `w-full`
- [ ] If it's a native tool card: registered in `TOOL_RENDERERS`

---

## 13. Forms & Validation

### Field Pattern

```tsx
<FormField
  control={form.control}
  name="fieldName"
  render={({ field }) => (
    <FormItem>
      <FormLabel>Label</FormLabel>
      <FormControl>
        <Input placeholder="..." {...field} />
      </FormControl>
      <FormMessage />  {/* auto-shows error */}
    </FormItem>
  )}
/>
```

### Input States

| State | Visual |
|---|---|
| Default | `border-input bg-transparent` |
| Focus | `ring-ring/50 ring-[3px] border-ring` |
| Error | `ring-destructive/20 border-destructive` (via `aria-invalid`) |
| Disabled | `opacity-50 cursor-not-allowed` |
| Loading | `cursor-wait` (set `disabled` on the input) |

Error state is driven by `aria-invalid={!!error}` — the styling is applied automatically via the Input component.

---

## 14. Loading & Empty States

### Loading

| Pattern | When |
|---|---|
| `<Skeleton className="h-4 w-32 rounded-md" />` | Known content shape, replacing text/images |
| `animate-pulse` on the container | Unknown shape, shimmer a region |
| `animate-spin` on an icon | Inline action in progress |
| Full `<LoadingIndicator />` | Whole chat response pending |

Skeleton inherits: `bg-accent animate-pulse rounded-md`. Match the skeleton shape to the content it replaces.

### Empty States

No shared component — build inline. Standard pattern:

```tsx
<div className="flex flex-col items-center gap-2 py-8 text-center">
  <SomeIcon className="text-zinc-600" size={24} />
  <p className="text-sm text-zinc-400">No items yet</p>
  <p className="text-xs text-zinc-500">Optional sub-text</p>
</div>
```

---

## 15. Interactive States

| State | Classes |
|---|---|
| Hover (standard) | `hover:bg-accent` · `hover:bg-primary/90` · `hover:opacity-80` |
| Hover (dark surface) | `hover:bg-white/5` — subtle white overlay on zinc backgrounds |
| Focus visible | `focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:border-ring` |
| Active / press | `active:scale-95` |
| Disabled | `disabled:opacity-50 disabled:pointer-events-none disabled:cursor-not-allowed` |
| Error | `aria-invalid:ring-destructive/20 aria-invalid:border-destructive` |
| Hover reveal | `opacity-0 transition-all group-hover:opacity-100` (parent needs `group`) |

---

## 16. Dark / Light Mode

Class-based: `.dark` on `<html>`. Tailwind `dark:` modifier works everywhere.

- **Layout surfaces** → `bg-background text-foreground` (auto-switches via CSS vars)
- **Dark cards** → `bg-zinc-800 / bg-zinc-900` (always dark — no `dark:` needed)
- **Explicit overrides** → `dark:bg-input/30` etc. only when CSS variables don't cover it
- Brand cyan (`#00bbff`) is the same in both modes

---

## 17. Responsiveness

| Breakpoint | Value | Impact |
|---|---|---|
| Mobile | `max-width: 600px` | Full-width layouts, larger tap targets |
| Tablet | `max-width: 990px` | Navbar becomes full-width strip |
| `md:` | 768px | Text size shifts (`text-base` → `text-sm`) |

Core layout does not use `lg:`, `xl:`, or `2xl:` breakpoints.

---

## 18. Scrollbars

Global scrollbar is already styled (8px, pill-shaped, zinc-700 thumb). Use `.no-scrollbar` to suppress chrome on scroll areas where it would be distracting.
