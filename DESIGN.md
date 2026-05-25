---
version: alpha
name: GAIA Design System
description: Dark-first, flat, single-accent visual language for GAIA — a proactive personal AI assistant. Depth comes from layered backgrounds, not borders.

colors:
  # Brand
  primary: "#00bbff"
  primary-foreground: "#000000"
  primary-bg: "#111111"
  secondary-bg: "#1a1a1a"
  selection-bg: "#00364b"
  selection-fg: "#00bbff"

  # Neutral (Zinc scale — dark surfaces and text)
  neutral-100: "#f4f4f5"
  neutral-200: "#e4e4e7"
  neutral-300: "#d4d4d8"
  neutral-400: "#a1a1aa"
  neutral-700: "#3f3f46"
  neutral-800: "#27272a"
  neutral-900: "#18181b"

  # Surfaces (semantic — auto-switch dark/light via CSS variables)
  surface: "#030711"
  on-surface: "#e1e7ef"
  surface-accent: "#1d293a"
  border: "#1d293a"

  # Status (always rendered with /10 opacity background, full color text)
  success: "#34d399"
  warning: "#fbbf24"
  error: "#f87171"
  info: "#60a5fa"
  destructive: "#7f1d1d"
  priority-high: "#ef4444"
  priority-medium: "#eab308"
  priority-low: "#3b82f6"

typography:
  display:
    fontFamily: PP Editorial New
    fontSize: 48px
    fontWeight: 200
    lineHeight: 1.1
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 30px
    fontWeight: 700
    lineHeight: 1.2
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: 700
    lineHeight: 1.25
  headline-sm:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: 700
    lineHeight: 1.3
  title-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: 700
    lineHeight: 1.4
  title-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: 600
    lineHeight: 1.4
  title-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: 600
    lineHeight: 1.4
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.5
  body-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.5
  body-xs:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: 0.05em
  code:
    fontFamily: Anonymous Pro
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.5

rounded:
  none: 0px
  sm: 6px
  md: 8px
  lg: 12px
  xl: 16px
  xxl: 24px
  full: 9999px

spacing:
  none: 0px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  xxl: 32px
  gutter: 16px

components:
  card-outer:
    backgroundColor: "{colors.neutral-800}"
    rounded: "{rounded.xl}"
    padding: "{spacing.lg}"
  card-inner:
    backgroundColor: "{colors.neutral-900}"
    rounded: "{rounded.xl}"
    padding: "{spacing.md}"
  card-glass:
    backgroundColor: "{colors.neutral-800}"
    rounded: "{rounded.xl}"
    padding: "{spacing.lg}"
  card-hoverable:
    backgroundColor: "{colors.neutral-800}"
    rounded: "{rounded.xl}"
    padding: "{spacing.lg}"
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.md}"
    padding: "{spacing.md}"
    height: 36px
  button-primary-hover:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
  button-secondary:
    backgroundColor: "{colors.neutral-800}"
    textColor: "{colors.neutral-100}"
    rounded: "{rounded.md}"
    padding: "{spacing.md}"
  button-ghost:
    backgroundColor: "{colors.neutral-800}"
    textColor: "{colors.neutral-200}"
    rounded: "{rounded.md}"
    padding: "{spacing.md}"
  button-destructive:
    backgroundColor: "{colors.destructive}"
    textColor: "{colors.neutral-100}"
    rounded: "{rounded.md}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.md}"
    padding: "{spacing.md}"
    height: 36px
  input-error:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.md}"
  chip-status-success:
    backgroundColor: "{colors.neutral-900}"
    textColor: "{colors.success}"
    rounded: "{rounded.full}"
  chip-status-warning:
    backgroundColor: "{colors.neutral-900}"
    textColor: "{colors.warning}"
    rounded: "{rounded.full}"
  chip-status-error:
    backgroundColor: "{colors.neutral-900}"
    textColor: "{colors.error}"
    rounded: "{rounded.full}"
  chip-status-info:
    backgroundColor: "{colors.neutral-900}"
    textColor: "{colors.info}"
    rounded: "{rounded.full}"
  chip-status-pending:
    backgroundColor: "{colors.neutral-700}"
    textColor: "{colors.neutral-300}"
    rounded: "{rounded.full}"
  chip-priority-high:
    backgroundColor: "{colors.neutral-900}"
    textColor: "{colors.priority-high}"
    rounded: "{rounded.full}"
  chip-priority-medium:
    backgroundColor: "{colors.neutral-900}"
    textColor: "{colors.priority-medium}"
    rounded: "{rounded.full}"
  chip-priority-low:
    backgroundColor: "{colors.neutral-900}"
    textColor: "{colors.priority-low}"
    rounded: "{rounded.full}"
  tooltip:
    backgroundColor: "{colors.neutral-900}"
    textColor: "{colors.neutral-100}"
    rounded: "{rounded.md}"
  toast:
    backgroundColor: "{colors.neutral-800}"
    textColor: "{colors.neutral-100}"
    rounded: "{rounded.lg}"
  app-shell:
    backgroundColor: "{colors.primary-bg}"
    textColor: "{colors.neutral-100}"
  sidebar:
    backgroundColor: "{colors.secondary-bg}"
    textColor: "{colors.neutral-200}"
  text-selection:
    backgroundColor: "{colors.selection-bg}"
    textColor: "{colors.selection-fg}"
  text-body:
    backgroundColor: "{colors.neutral-900}"
    textColor: "{colors.neutral-400}"
  divider:
    backgroundColor: "{colors.surface-accent}"
    height: 1px
  border-subtle:
    backgroundColor: "{colors.border}"
    height: 1px
---

# GAIA Design System

The visual language for building any UI in this codebase. Tokens, patterns, and rules — not component internals or workflows.

> **Parsed by docs:** This file is the source of truth for [`docs/design-system.mdx`](docs/design-system.mdx), rendered at [docs.heygaia.io/design-system](https://docs.heygaia.io/design-system). When updating tokens here, keep that page in sync.

**Related files:**
- Token source: `apps/web/src/app/styles/globals.css`
- Claude design rules: `apps/web/CLAUDE.md` (behavioral) + this file (tokens)
- Visual docs: `docs/design-system.mdx` → renders this file as a style guide
- Chat bubble & tool-card design: `apps/web/src/features/chat/components/bubbles/bot/CLAUDE.md`
- OpenUI system guide: `apps/web/src/config/openui/CLAUDE.md`

## Overview

GAIA is a proactive personal AI assistant. The interface should feel calm, confident, and dense without being cluttered — closer to a power tool than a consumer app. Five principles drive every decision:

- **Dark-first.** The primary experience is dark mode (`primary-bg #111111`). Light mode is supported via CSS variables but is secondary.
- **Flat depth.** Depth comes from layered backgrounds (`neutral-800` → `neutral-900`), never borders or outlines.
- **Single accent.** One primary action color (`#00bbff`, brand cyan). Everything else is neutral zinc.
- **Borderless cards.** Data cards use background-only separation — no border, ring, or outline anywhere in the card tree.
- **Subtle motion.** Animations are functional (entrance, exit, state change), not decorative.

## Colors

The palette is rooted in a deep neutral foundation, with a single saturated cyan as the only accent. Status colors are reserved for system feedback and always render at `/10` opacity backgrounds with full-color text.

- **Primary (`#00bbff`):** Saturated cyan used exclusively for the primary action per screen — CTAs, the user chat bubble, selection highlight, and links.
- **Neutral (Zinc scale `#f4f4f5` → `#18181b`):** All non-accent UI. Cards layer `neutral-800` (outer) over `neutral-900` (inner) to create depth without borders.
- **Surfaces (semantic):** `surface` and `on-surface` are paired tokens that auto-switch between light and dark via CSS variables. Use them on layout chrome (page backgrounds, app shell), not on cards.
- **Status (`success`, `warning`, `error`, `info`):** Always paired as `<color>/10` background + full `<color>` text. Never solid status backgrounds.
- **Priority (high/medium/red, yellow, blue):** Reserved for task and todo priority indicators.

### Brand Tokens (CSS variables)

| Token | Value | Use |
|---|---|---|
| `--color-primary` | `#00bbff` | CTAs, user bubble, selection, links |
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

## Typography

Three families do all the work. **Inter** for every UI surface, **PP Editorial New** for editorial moments only (landing hero, marketing display), and **Anonymous Pro** for code and technical content. Heading styles are set globally — use semantic HTML and styles apply automatically.

- **Display (PP Editorial New, 48px / 200):** Reserved for landing hero text. Never used inside the product.
- **Headline scale (Inter, 30 → 14px / 700):** `headline-lg` through `title-sm` map to `<h1>` through `<h6>`.
- **Body scale (Inter, 16 / 14 / 12px / 400):** Default product text.
- **Label (Inter, 12px / 500 / uppercase / wider tracking):** Section labels in settings panels and form groups.
- **Code (Anonymous Pro, 14px):** Inline code and code blocks. Inline code gets `border-radius: 10px` and `padding: 4px` globally.

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

## Layout

The layout grid is a 4px-base spacing scale (`xs 4px` → `xxl 32px`). Most cards use `padding: lg (16px)` outer, `padding: md (12px)` inner. Vertical rhythm inside cards is `space-y-2` (8px). The product avoids fixed maximum widths in chat areas; settings and modals cap around 600px.

| Value | Use |
|---|---|
| `gap-1` / `gap-1.5` | Icon + label pairs |
| `gap-2` | Standard row items |
| `gap-3` | Section spacing inside cards |
| `space-y-2` | Vertical list of items inside a card |
| `p-3` | Inner card item padding |
| `p-4` | Outer card padding |
| `px-3` / `px-4` | Horizontal padding on inputs, buttons |

### Responsive Breakpoints

| Breakpoint | Value | Impact |
|---|---|---|
| Mobile | `max-width: 600px` | Full-width layouts, larger tap targets |
| Tablet | `max-width: 990px` | Navbar becomes full-width strip |
| `md:` | 768px | Text size shifts (`text-base` → `text-sm`) |

Core layout does not use `lg:`, `xl:`, or `2xl:` breakpoints.

## Elevation & Depth

Depth is conveyed through **tonal layering**, not shadows. Cards stack `neutral-800` over `neutral-900` to read as recessed without any border. Shadows are reserved for true overlays (dialogs, sheets); cards never carry them. Glass surfaces (`bg-zinc-800/40 backdrop-blur-xl`) handle floating panels and search overlays.

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

## Shapes

The shape language is **soft and rounded**. Cards default to `rounded-xl (16px)` for outer containers — large enough to read as a deliberate card, never `rounded-lg` (the Shadcn default which feels cramped). Buttons and inputs use `rounded-md (8px)`. Pills and avatars are fully rounded. Sharp corners (`rounded-none`) are not used anywhere in the product surface.

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

## Components

GAIA composes from three component families: **Shadcn** (`src/components/ui/`) for layout primitives, **HeroUI** (`@heroui/*`) for richer in-card UI (chips, accordions, progress, tabs), and a small set of GAIA-native cards built directly to the dark card contract. Pick the right overlay for the context — `Dialog` for focus, `Sheet` for side panels, `Popover` for inline pickers, `Tooltip` for labels only.

### Dark Card Styling Contract

All data cards, tool sections, and info panels follow this two-tone zinc contract. No borders anywhere.

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

| Use case | Component |
|---|---|
| Destructive confirmation, focused form | `Dialog` |
| Side panel, settings, multi-step flow | `Sheet` |
| Inline picker, date selector, contextual detail | `Popover` |
| Single-line label on hover | `Tooltip` |
| Action list from a trigger | `DropdownMenu` |
| Right-click actions | `ContextMenu` |

### Forms & Validation

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

| State | Visual |
|---|---|
| Default | `border-input bg-transparent` |
| Focus | `ring-ring/50 ring-[3px] border-ring` |
| Error | `ring-destructive/20 border-destructive` (via `aria-invalid`) |
| Disabled | `opacity-50 cursor-not-allowed` |
| Loading | `cursor-wait` (set `disabled` on the input) |

Error state is driven by `aria-invalid={!!error}` — styling is applied automatically by the Input component.

### Interactive States

| State | Classes |
|---|---|
| Hover (standard) | `hover:bg-accent` · `hover:bg-primary/90` · `hover:opacity-80` |
| Hover (dark surface) | `hover:bg-white/5` — subtle white overlay on zinc backgrounds |
| Focus visible | `focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:border-ring` |
| Active / press | `active:scale-95` |
| Disabled | `disabled:opacity-50 disabled:pointer-events-none disabled:cursor-not-allowed` |
| Error | `aria-invalid:ring-destructive/20 aria-invalid:border-destructive` |
| Hover reveal | `opacity-0 transition-all group-hover:opacity-100` (parent needs `group`) |

### Loading & Empty States

| Pattern | When |
|---|---|
| `<Skeleton className="h-4 w-32 rounded-md" />` | Known content shape, replacing text/images |
| `animate-pulse` on the container | Unknown shape, shimmer a region |
| `animate-spin` on an icon | Inline action in progress |
| Full `<LoadingIndicator />` | Whole chat response pending |

Empty state pattern (no shared component — build inline):

```tsx
<div className="flex flex-col items-center gap-2 py-8 text-center">
  <SomeIcon className="text-zinc-600" size={24} />
  <p className="text-sm text-zinc-400">No items yet</p>
  <p className="text-xs text-zinc-500">Optional sub-text</p>
</div>
```

## Do's and Don'ts

- Do use `primary` (`#00bbff`) for the single most important action per screen — never on multiple buttons in the same view.
- Do layer cards as `bg-zinc-800` outer over `bg-zinc-900` inner — this two-tone is the entire separation mechanism.
- Do render status with `<color>/10` background + full `<color>` text. Never solid status backgrounds.
- Do use icons from `@icons` (`@theexperiencecompany/gaia-icons`). Never raw SVG.
- Do use `cn()` from `@/lib/utils` for conditional class merging, and `cva` for components with multiple visual variants.
- Do use Sileo for toasts — it is mounted globally; just call the toast function.
- Do truncate long strings in constrained containers with `truncate` or `line-clamp-N`.
- Don't put `border-`, `ring-`, or `outline-` anywhere in the card tree. Depth comes from tonal layering only.
- Don't use `rounded-lg` on card containers. It is the Shadcn default and visually too cramped — use `rounded-xl` (16px).
- Don't use Unicode symbols (`→`, `↗`, `•`, `✓`, `×`) as UI elements. Always use icon components from `@icons`.
- Don't use solid color backgrounds for status states. Always pair `/10` background with full color text.
- Don't import from `framer-motion` — import from `motion/react`. `AnimatePresence` is required for exit animations.
- Don't add another `<Toaster>` or import from `sonner` / `react-hot-toast`. Sileo is the only toast library.
- Don't set `font-family` inline. Use the Tailwind class (`font-sans` / `font-serif` / `font-mono`).
- Don't mix `rounded-md` and `rounded-xl` corners on adjacent siblings — pick one rhythm per surface.

## Icons

All icons come from `@icons` (`@theexperiencecompany/gaia-icons`). Never raw SVGs.

```typescript
import { CheckmarkCircle02Icon, Alert01Icon, Copy01Icon } from "@icons";
```

Icons accept `className`, `height`, `width`, and `size` props.

| Context | Value |
|---|---|
| Inline (badges, text) | `height={17}` |
| Action buttons | `size={16}` |
| Prominent / decorative | `size={24}` |

```tsx
<Button variant="ghost" size="icon">
  <Copy01Icon className="h-4 w-4" />
</Button>

<Alert01Icon className="text-warning-500" height={17} />

<SomeIcon className="transition-all duration-200 group-hover:scale-110" />
```

Icons are named `{Name}Icon` — e.g. `Brain02Icon`, `CheckmarkCircle01Icon`.

## Animations

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

Default transition: `transition-all duration-200`. Use this everywhere unless a specific property needs targeting.

| Scenario | Classes |
|---|---|
| All properties | `transition-all duration-200` |
| Color only | `transition-colors duration-200` |
| Button press | `active:scale-95 transition-all! duration-300` |

| Easing | Value | Use |
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

## Toasts & Notifications

Library: **Sileo**. Already mounted globally — just call the toast function. Never add another `<Toaster>` or import from `sonner` / `react-hot-toast`.

Toast style: dark fill (`#262626`), white title, white/75 description, top-right position.

Action button colors are applied automatically by type: error → red, warning → amber, success → green, info → blue.

## Styling Tools

### `cn()`

Use `cn()` from `@/lib/utils` for all conditional class merging. Never string concatenation.

```typescript
import { cn } from "@/lib/utils";

<div className={cn("base-class", condition && "conditional-class", className)} />
```

### `cva`

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

## Dark / Light Mode

Class-based: `.dark` on `<html>`. Tailwind `dark:` modifier works everywhere.

- **Layout surfaces** → `bg-background text-foreground` (auto-switches via CSS vars)
- **Dark cards** → `bg-zinc-800 / bg-zinc-900` (always dark — no `dark:` needed)
- **Explicit overrides** → `dark:bg-input/30` etc. only when CSS variables don't cover it
- Brand cyan (`#00bbff`) is the same in both modes

## Scrollbars

Global scrollbar is already styled (8px, pill-shaped, `zinc-700` thumb). Use `.no-scrollbar` to suppress chrome on scroll areas where it would be distracting.

## New Card Checklist

- [ ] Outer: `rounded-2xl bg-zinc-800 p-4`
- [ ] Inner items: `rounded-2xl bg-zinc-900 p-3`
- [ ] No `border-`, `ring-`, `outline-` anywhere
- [ ] Icons from `@icons` only
- [ ] Status colors use `/10` opacity backgrounds
- [ ] Width: `w-fit min-w-[400px]` or `w-full`
- [ ] If it's a native tool card: registered in `TOOL_RENDERERS`
