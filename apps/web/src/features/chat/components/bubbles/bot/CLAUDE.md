# Chat Bubbles (bot)

Bot-side message rendering. This directory holds `ChatBubbleBot` (the outer chrome: avatar, actions, memory indicator), `TextBubble` (the renderer that decides what each message becomes), and every native GAIA tool card (`*Section.tsx` / `*Card.tsx`). The sibling `../user/` holds the user-side bubble; `../actions/` holds the hover action rows.

For design tokens and the card styling contract: `DESIGN.md` (repo root). For the OpenUI lifecycle (LLM-emitted generic components): `apps/web/src/config/openui/CLAUDE.md`. Do not duplicate either here.

## Rendering architecture

`ChatBubbleBot` is layout-only: it picks `ImageBubble` when `image_data` exists, else `TextBubble`, and wraps it in the avatar + actions chrome. All routing logic lives in `TextBubble.tsx`.

`TextBubble` renders, in order:

1. **Thinking** — `parseThinkingFromText` strips `<thinking>` content into a `ThinkingBubble`; `cleanText` is what gets bubbled.
2. **Tool cards** — `tool_data[]` entries are matched against `TOOL_RENDERERS` and rendered **outside** any bubble (see gotchas). `todo_progress` is special-cased before the map.
3. **Text** — `cleanText` is split into parts, each part further split into markdown vs OpenUI segments.

Two distinct paths produce visual blocks. Know which one applies:

| Path | Source | Where registered | Renders |
|---|---|---|---|
| **TOOL_RENDERERS** | Structured `tool_data` streamed by a known GAIA tool | `TOOL_RENDERERS` map in `TextBubble.tsx`, keyed off `ToolName` | A native, hand-built React card |
| **OpenUI** | `:::openui` fences inside the LLM's text response | `config/openui/genericLibrary.tsx` (not here) | A generic component from the OpenUI library |

A tool lives in exactly one path. If a tool has a `TOOL_RENDERERS` entry, the backend suppresses OpenUI for it. See `config/openui/CLAUDE.md` for that contract.

## Text segmentation

`cleanText` is split by message breaks into parts (`splitByBreaksPreservingFences` if it contains `:::openui`, else `splitMessageByBreaks`). Each part is then run through `parseOpenUISegments`:

- **Pure-markdown part** → one `imessage-bubble imessage-from-them` bubble with `MarkdownRenderer` inside. Grouping classes (`imessage-grouped-first/middle/last`) chain consecutive bubbles. Emoji-only parts drop the bubble and scale up the glyph.
- **Mixed part (markdown + openui)** → markdown segments each get their own compact bubble; openui segments render at the same DOM level as tool cards (no bubble wrapper).

`disclaimer` (a `Chip`) attaches only to the last markdown block.

## Adding a native tool card

1. **Backend** streams a `tool_data` entry with a new `tool_name`.
2. Register the tool in `@/config/registries/toolRegistry.ts` (`TOOL_REGISTRY`) so `ToolName` / `ToolDataMap` know the payload type. Add it to `GROUPED_TOOLS` only if multiple calls of it should merge into one card (then your renderer receives an array).
3. Build the card component in this directory (`MyThingSection.tsx`). It receives the typed `data` and an `index`; it returns the JSX. Props are the deserialized `tool_data.data` for that tool — type it from `toolRegistry`, never re-declare the shape.
4. Add an entry to `TOOL_RENDERERS` in `TextBubble.tsx`: `my_tool_name: (data, index) => <MyThingSection key={...} ... />`. The `key` must be unique; prefer `tool_call_id` when present, else `index`.

Styling: follow the dark-card contract in `DESIGN.md` (outer `rounded-2xl bg-zinc-800 p-4`, inner `rounded-2xl bg-zinc-900 p-3`, no borders). `RateLimitCard.tsx` is a good full-featured reference.

## Gotchas

- **Tool cards and OpenUI render outside the bubble, never inside.** `imessage-from-them` background is `#27272a` (zinc-800), the same as a card's outer container, so a card placed inside the bubble is invisible. The mixed-part branch in `TextBubble` exists solely to lift openui segments out of the bubble. Cards are always siblings of bubbles, not children.
- **A renderer returning `null`** (unregistered tool, or `getTypedData` mismatch) silently renders nothing. If a card does not appear, confirm the `tool_name` is in both `TOOL_REGISTRY` and `TOOL_RENDERERS`.
- **`GROUPED_TOOLS` changes your data shape.** A grouped renderer gets `Data[]` (or `Data[][]` for already-batched payloads like `email_fetch_data`); flatten/dedup inside the renderer as the existing entries do.
- **Cards must dedup their own merged input.** Grouped streams can repeat items (see the `Set`-based dedup in `search_results`, `integration_connection_required`, `rate_limit_data`).
- **HeroUI for every primitive** (`Button`, `Chip`, `Divider`, `Tooltip`, `Spinner`), never raw HTML or icon-based spinners. **Icons only from `@icons`.** No Unicode glyphs (`→`, `•`, `×`) as UI — use icon components. These are house rules, not lint-caught.

## Which path do I use

| You have | Use |
|---|---|
| Structured data from a GAIA tool with a fixed shape | Native tool card (`TOOL_RENDERERS` + component here) |
| Rich layout the LLM should assemble ad hoc from a fixed component vocabulary | OpenUI (`config/openui/`) |
| Plain prose, lists, code, opinions | Nothing — let it flow through `MarkdownRenderer` as a normal bubble |
