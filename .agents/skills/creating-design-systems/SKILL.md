---
name: creating-design-systems
description: Use when reverse-engineering a codebase's implicit design system, creating a DESIGN.md style guide, documenting design tokens, or establishing visual language standards. Also use when asked to audit UI consistency, rationalize ad-hoc styling into a system, or prepare a design reference that enables one-shotting new components.
---

# Creating Design Systems

Reverse-engineer a codebase's implicit visual language into a practical, implementation-ready style guide that lets you (or any agent) one-shot new UI components without configuration or guesswork.

## When to Use

- User asks for a design system, style guide, or DESIGN.md
- You need to build UI in an unfamiliar codebase and there's no design doc
- Existing UI is inconsistent and needs rationalization into standards
- You want to one-shot new components that look native to the app

## Analysis: What to Read

Read actual source files — don't guess from file names.

### Token Sources (read first)

| What | Where to look |
|------|--------------|
| Colors, radius, shadows, fonts | `globals.css`, `tailwind.config.*`, CSS custom properties |
| Component library config | `components.json` (Shadcn), theme files, provider wrappers |
| Base component variants | `button.tsx`, `input.tsx`, `card.tsx` — the primitives |

### Pattern Sources (read second)

| What | Where to look |
|------|--------------|
| Real token usage | 3-5 feature components that ship to users (not storybook demos) |
| Recurring class combos | Grep for `rounded-`, `bg-`, `text-` — find the actual palette in use |
| Interactive states | Button, input, dropdown — how hover/focus/disabled/error look |
| Status/semantic colors | Badges, chips, alerts — how success/warning/error/info are expressed |
| Animation patterns | Grep for `animate-`, `transition-`, `motion` imports |
| Icon system | How icons are imported, sized, colored |
| Toast/notification | Which library, how it's configured, how it's called |
| Overlay usage | When dialog vs sheet vs popover vs tooltip |
| Depth/elevation | Shadows vs background layering vs blur — how the project creates depth |
| Glass/blur patterns | Grep for `backdrop-blur`, `bg-opacity`, `/40` — some apps use transparency as a design tool |
| Gradients | Grep for `gradient`, `linear-gradient` — decorative moments, hero sections |
| Text overflow | How long strings are handled — `truncate`, `line-clamp-*`, `max-w-[]` patterns |
| Class composition | What utility the project uses for conditional classes (`cn`, `clsx`, `cva`, `tv`) |
| Landing vs app UI | Some codebases have two visual registers — check if marketing pages use different fonts, spacing, or tone |

### What NOT to Read

- Git history (stale, not current state)
- Test files (test patterns, not design patterns)
- Build config (not design-relevant)
- Backend code (unless it emits UI — like OpenUI prompts)

## Structure: What to Document

Order matters — philosophy sets the mental model, tokens are the vocabulary, patterns show how to compose.

```
1. Philosophy        — 3-5 bullets. The "why" behind visual choices.
2. Colors            — Brand tokens, semantic variables, neutral scale, status colors.
3. Typography        — Font families and when each is used. Heading scale.
4. Spacing           — Common values and what each is for.
5. Border Radius     — Decision table: which radius for which context.
6. Shadows           — When shadow vs flat. Usually a short section.
7. Icons             — Library, import pattern, sizing convention.
8. Animations        — Available classes, transition defaults, easing, motion library.
9. Toast             — Library name, how to call it, don't configure it.
10. Styling Tools    — cn(), cva, or whatever the project uses for class composition.
11. Component Library — What's available. Overlay hierarchy (dialog vs sheet vs popover).
12. Card/Surface Contract — The reusable pattern for data display. Include a template.
13. Forms            — Field pattern, input states, error display.
14. Loading States   — Skeleton, spinner, empty state patterns.
15. Interactive States — Hover, focus, active, disabled, error, hover-reveal.
16. Dark/Light Mode  — How theming works, what switches and what doesn't.
17. Responsiveness   — Breakpoints and what changes at each.
```

Not every project needs every section. Skip what doesn't apply. Never pad.

## The Refinement Loop

A design system doc is never right on the first pass. Plan for three.

### Pass 1: Extract Everything

Dump every token, pattern, and convention you find. Over-include. Get the raw material down.

### Pass 2: Remove Redundancy

Compare against existing docs (rules files, component-level CLAUDE.md files, READMEs). If something is already documented elsewhere, either:
- **Remove it** and point to the source, or
- **Move it here** and remove it from there (if this is the better home)

Never have the same rule in two files. Pick one owner.

### Pass 3: Remove Implementation Details

This is the critical pass. Ask of every line: *"Is this design language or is this how a specific component works?"*

**Keep (design language):**
- "Outer cards use `rounded-2xl bg-zinc-800 p-4`" — a reusable token/pattern
- "Status colors use `/10` opacity backgrounds" — a system-wide rule
- "Use `font-serif` for editorial headings only" — a design decision
- A card template with status colors — a reusable starting point

**Remove (implementation details):**
- Component architecture trees (`TextBubble → ThinkingBubble → MarkdownRenderer`)
- JSX layout diagrams of specific components
- Developer workflows ("register in TOOL_RENDERERS, add to tool_fields")
- Raw config blocks (full Toaster JSX, HeroUI theme override CSS)
- Specific container widths tied to one component ("PDF container: 330x150px")
- How a specific feature's state management works

**The test:** If someone building a *completely different* feature wouldn't use this info, it's implementation detail — move it to a component-level doc or delete it.

## File Placement

### One Source of Truth

Put the design system in **one file** at the repo root: `DESIGN.md`.

Other files should **point to it**, not duplicate it:

```markdown
# .claude/rules/design.md (or equivalent rules file)
See DESIGN.md at the repo root for the full design system.
```

```markdown
# In CLAUDE.md (or equivalent project instructions)
## Design System
See [DESIGN.md](./DESIGN.md) for the full design system guide.
```

### Separation of Concerns

| File | Contains | Does NOT contain |
|------|----------|-----------------|
| `DESIGN.md` | Visual language, tokens, patterns, templates | Component internals, developer workflows |
| Code rules file (e.g. `typescript.md`) | Code standards, import rules, type rules | Design tokens (just point to DESIGN.md) |
| Component-level docs | Architecture, registration steps, render logic | Design tokens (inherit from DESIGN.md) |

If a code rules file has a Styling section, keep it to one line: "TailwindCSS exclusively — see DESIGN.md for tokens and patterns."

### The Boundary Between Code Rules and Design System

Some things feel like code standards but are actually design decisions. When in doubt: if it governs *how things look*, it's design system; if it governs *how code is written*, it's code rules.

| Belongs in DESIGN.md | Belongs in code rules |
|---|---|
| `cn()` / `cva` usage patterns (class composition is a styling tool) | "Use `import type` for type-only imports" |
| Card contract: `rounded-2xl bg-zinc-800 p-4` | "Named exports only, no default exports" |
| Status color pattern: `bg-emerald-400/10 text-emerald-400` | "No `any` type — use `unknown` and narrow" |
| "Never add borders to cards" | "TailwindCSS exclusively, no inline styles" |
| Animation timing defaults | Import ordering rules |

A common mistake is putting the card contract in the code rules file because it "looks like a coding pattern." It's a visual pattern — move it to the design system and point to it from code rules.

## Card/Surface Contract

Most apps have a dominant card pattern for displaying structured data. Document it as a **contract** with a copy-paste template. This is the highest-value section — it's what enables one-shotting new components.

**What to include:**
1. The exact classes for outer container, inner items, headers, body text, meta text
2. Hard constraints (e.g. "no borders", "always rounded-2xl")
3. Status color application (the `/10` opacity pattern or whatever the project uses)
4. A ready-to-use template component with all patterns applied
5. A checklist to verify before committing

**Example contract (from a dark-first app):**

```
Outer:  rounded-2xl bg-zinc-800 p-4
Inner:  rounded-2xl bg-zinc-900 p-3
Header: text-sm font-semibold text-zinc-100 mb-3
Title:  text-sm font-medium text-zinc-200
Body:   text-xs text-zinc-400
Meta:   text-xs text-zinc-500
Gap:    space-y-2
Status: bg-{color}-400/10 text-{color}-400
```

The template should be a real component someone can copy, rename, and fill in — not pseudocode.

## Common Mistakes

### Being too specific
"The PDF container is 330x150px" — this is one component's spec, not design language. The design system should say "use `rounded-2xl` for cards" and let each component decide its own dimensions.

### Duplicating across files
The card contract appears in DESIGN.md, also in the TypeScript rules, also in a component-level doc. Now they'll drift. Pick one home.

### Documenting what the code already says
Don't list every Shadcn component's props — that's in the component file. Document *when to use which* (the overlay hierarchy) and *what they look like in this project* (the customizations).

### Mixing design language with developer workflow
"Register the component in TOOL_RENDERERS" is a workflow step. "All data cards use `rounded-2xl bg-zinc-800`" is design language. The design system file should only contain the latter.

### Skipping the philosophy section
Without it, the tokens are just a list of values with no rationale. "Flat depth — never borders, only background layering" explains *why* there are no border classes anywhere and prevents someone from adding them.

### Writing a design system that requires reading the design system
If someone needs to read 800 lines before they can build a card, the doc is too long. Front-load the card template and checklist. Put reference material (full color tables, all animation classes) after the actionable patterns.
