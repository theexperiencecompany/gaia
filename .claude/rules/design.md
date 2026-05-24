---
description: Design system rules — tokens, colors, components, card contract, animations, icons
paths:
  - "**/*.tsx"
  - "**/*.ts"
  - "**/*.css"
---

# Design System Rules

All design tokens, patterns, and rules are in **`DESIGN.md`** at the repo root. Read it before writing any UI code.

Visual style guide (rendered in docs): `docs/design-system.mdx` → [docs.heygaia.io/design-system](https://docs.heygaia.io/design-system)

Chat bubble / OpenUI architecture (rendering rules, component checklist): `apps/web/src/features/chat/components/bubbles/bot/CLAUDE.md`

---

## Behavioral Rules (not in DESIGN.md)

### HeroUI — Do Not Override Default Styling

Use HeroUI components as-is. Do not pass `classNames`, `className`, or inline `style` to override HeroUI's internal styling unless:
- The user explicitly asks for a visual customisation, or
- The component truly needs a one-off layout adjustment (e.g. `className="w-full"`)

Use HeroUI variant/color props first (`variant="flat"`, `color="primary"`, etc.) before reaching for `classNames`. Custom overrides make components fragile across theme changes and upgrades.

### OpenUI Components

OpenUI components must render **outside** the `imessage-bubble` wrapper — never inside it. Both use `bg-zinc-800`, so rendering inside makes them invisible against the bubble background.

See `apps/web/src/features/chat/components/bubbles/bot/CLAUDE.md` for the full OpenUI lifecycle and component checklist.
