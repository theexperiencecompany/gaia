# OpenUI System — Maintenance Guide

OpenUI lets the backend LLM emit rich React components inside its chat response, written in
**OpenUI Lang** (a declarative DSL parsed by `@openuidev/react-lang`).

GAIA **adopts `@openuidev/react-ui`** — the official Generative UI component library — themed to
match GAIA exactly. We do **not** hand-roll the component set; we extend it only where react-ui
has no equivalent.

---

## 1. Architecture

```text
Backend LLM                         Frontend
────────────────────────            ──────────────────────────────────────────────
response text with         →        TextBubble splits at :::openui fences
:::openui fences                    OpenUIRenderer → <Renderer library={genericLibrary}>
                                    renders react-ui components under <ThemeProvider>
```

- **Runtime**: `@openuidev/react-lang` (parser + `Renderer` + `createLibrary` + `generatePrompt`).
- **Components**: `@openuidev/react-ui`'s `openuiLibrary` (Stack, Card, CardHeader, Charts,
  Table/Col, Tag, Steps, forms, Modal, …) — see `genui-lib`.
- **Theme**: `theme.ts` (`gaiaOpenUITheme`) maps every `--openui-*` token to GAIA's design
  system. Mounted once via `<ThemeProvider mode="dark" darkTheme={gaiaOpenUITheme}>` in
  `apps/web/src/layouts/RootProviders.tsx`. Layered CSS is imported in `globals.css`.

## 2. The merged library (`genericLibrary.tsx`)

`genericLibrary` = react-ui's `openuiLibrary.components` **+** GAIA-only components react-ui
lacks. GAIA components can override react-ui ones by name (only `ImageGallery` does, for
session-file artifact resolution).

GAIA-only components (in `components/`): `GaugeChart`, `MapBlock`, `Timeline` (event feed),
`FileTree`, `TextDocument`, `NumberTicker`, `AudioPlayer`, `VideoBlock`, `Progress`, `Avatar`,
`CopyableContent`, `KbdRow`.

## 3. Adding / changing a component

1. **Does react-ui already have it?** If yes, just use it — nothing to do here. The LLM learns
   it automatically from the generated prompt.
2. **Only if react-ui has no equivalent**, add a GAIA component:
   - Define the React view + `defineComponent` in `components/<area>.tsx`.
   - Put its Zod schema + name + description in **`promptSpecs.ts`** (the Node-safe single
     source) and import it back into the component file. **Never** define a GAIA component
     schema only inside a component file — the prompt generator can't import browser code.
   - Register the def in `genericLibrary.tsx` (`gaiaComponents` + the `GAIA` component group).

## 4. The LLM prompt is generated — never hand-edit it

`scripts/openui/generate-prompt.ts` merges `openuiLibrary.toSpec()` with the GAIA specs from
`promptSpecs.ts` and writes `apps/api/app/agents/prompts/openui_generated.txt`. The Python
agent (`openui_prompts.py`) reads that artifact and prepends GAIA's SURFACE POLICY +
`OPENUI_SUPPRESSED_TOOLS` (derived from `tool_fields` in `chat_models.py`).

- Regenerate: `pnpm openui:gen-prompt`.
- A **prek pre-commit hook** regenerates and fails if `openui_generated.txt` is stale, so the
  prompt can never drift from the library. `openui_generated.txt` is committed.

## 5. Styling contract

OpenUI renders **outside** the `imessage-bubble` wrapper (both use `bg-zinc-800`, so inside is
invisible). react-ui components are themed via `theme.ts`; GAIA components use the same zinc
tokens (`rounded-2xl`, zinc-800 outer / zinc-900 inner, borderless). Status colors: emerald /
amber / red / blue. Primary `#00bbff`.

## 6. Actions

Interactive components emit through `Renderer`'s `onAction`. `OpenUIRenderer` routes events via
`dispatchOpenUIAction` (`libs/shared/ts/src/utils/openui-actions.ts`): `continue_conversation`
→ append to composer, `open_url` → `window.open`.

## 7. Dev playground

`/dev/openui-samples` (dev-only) — live DSL editor + example dashboards (analytics, kanban,
GAIA components, form). Client-only (`dynamic({ ssr: false })`) because charts/maps are
browser-only. Examples live in `examples/index.ts`.

## 8. Error handling

`OpenUIRenderer` wraps the tree in `OpenUIErrorBoundary` (raw-code fallback) and logs structured
validation errors via the `Renderer`'s `onError`. Tool outputs handled by a native GAIA tool
card are suppressed — the LLM must not emit `:::openui` for tools in `OPENUI_SUPPRESSED_TOOLS`.
