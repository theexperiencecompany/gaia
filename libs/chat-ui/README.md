# @heygaia/chat-ui

GAIA chat presentation components, extracted from `gaia/apps/web` so they can be reused across surfaces — the GAIA web app, the motion studio (Remotion), demo recording flows, and any future product surface — without copy-paste duplication.

## Install

```bash
pnpm add @heygaia/chat-ui
```

The package ships ESM only. React 19+ is required.

```tsx
import {
  ChatBubbleUser,
  ChatBubbleBot,
  TextBubble,
  LoadingIndicator,
  ChatRenderer,
  FollowUpActions,
  ToolCallsSection,
  ThinkingBubble,
  ImageBubble,
  MarkdownRenderer,
} from "@heygaia/chat-ui";

import "@heygaia/chat-ui/styles.css";
```

## Peer dependencies

The package declares heavy presentation deps as **peer dependencies** so consumers dedupe them. Your app must install:

```bash
pnpm add react react-dom
pnpm add @heroui/accordion @heroui/button @heroui/chip @heroui/skeleton @heroui/spinner @heroui/tooltip
pnpm add @theexperiencecompany/gaia-icons motion react-markdown remark-gfm
pnpm add zustand class-variance-authority clsx date-fns tailwind-merge
```

Optional (only if you use Next.js features in the components):

```bash
pnpm add next
```

## What's inside

| Export | Purpose |
|---|---|
| `ChatBubbleUser` | Right-aligned user message bubble (iMessage-style) |
| `ChatBubbleBot` | Left-aligned bot message bubble with logo, follow-up actions slot, tool data slot |
| `TextBubble` | Renders bot text with markdown, code blocks, embedded tool data cards (calendar/email/weather/workflow/reddit/etc.) |
| `ImageBubble` | Renders generated images |
| `ThinkingBubble` | Collapsible reasoning/thinking block |
| `FollowUpActions` | Suggested next-action chips below a bot message |
| `ToolCallsSection` | Vertical timeline of tool execution results |
| `LoadingIndicator` | Animated loading state with tool category icon + shimmering text |
| `ChatRenderer` | Full conversation layout (renders an array of messages) |
| `MarkdownRenderer` | Standalone markdown component used internally |

Plus the full type surface (`ChatBubbleBotProps`, `ChatBubbleUserProps`, message types, tool data types) and the `toolRegistry` config.

## Architecture

The chat UI lives at `gaia/libs/chat-ui` as a workspace package and publishes to npm under `@heygaia/chat-ui`.

```
gaia/
├── apps/web/                          ← imports @heygaia/chat-ui
│   └── src/features/chat/
│       ├── api/                       ← stays here (real impl)
│       ├── hooks/                     ← stays here (real impl)
│       └── (components moved out)
├── libs/chat-ui/                      ← this package
│   ├── src/
│   │   ├── features/chat/components/  ← moved from apps/web
│   │   ├── features/{calendar,mail,weather,workflows,...}/  ← cards used in chat
│   │   ├── components/{shared,ui}/    ← shared primitives
│   │   ├── types/, config/, utils/
│   │   ├── shared/                    ← @gaia/shared utilities snapshot
│   │   ├── stubs/                     ← typed no-op stubs for runtime deps
│   │   └── index.ts                   ← public API
│   ├── tsup.config.ts                 ← ESM build with tsconfig-paths resolution
│   └── package.json
```

### Path aliases preserved

The package uses `tsconfig.json` `paths` to mirror GAIA's original `@/...` and `@shared/...` namespace internally. This means moved files keep their original imports unchanged — zero rewrites of the 164 import statements across 552 source files. tsup resolves these aliases during bundling so the published `dist/` has them inlined.

### Stubs at the boundary

The chat components reference runtime dependencies (stores, db, api clients, sync, auth, analytics) that don't belong in a presentation library. The package provides typed no-op stubs in `src/stubs/` for these so:

- The package builds standalone (no broken imports)
- Consumers compile against the same types as the real impls
- A future `<ChatProvider>` API can let consumers inject their real store/auth/api at runtime

Stubbed surfaces:

- `@/stores/*` — chat, loading, composer, reply-to, calendar/workflow selection, ui, sidebar, pricing modal
- `@/lib/{db,api,toast,analytics,utils}` — db handles, api client, notifications, tracking
- `@/services/{api,syncService}` — sync engine, notifications API
- `@/i18n/{navigation,config,routing}` — Next.js i18n routing
- `@/features/auth/hooks/{useUser,useAuth}` — auth state
- `@/features/chat/{api,hooks,actions}/*` — chat orchestration (chatApi, useLoading, useConversation, etc.)
- `@/hooks/{useSendMessage,useBackgroundSync}` — top-level hooks
- `@/features/integrations/hooks/useIntegrations` — integration state
- `@/config/openui/*` — OpenUI library

## Publishing

CI workflow `publish-chat-ui.yml` auto-publishes a per-commit prerelease (`0.0.0-feat-chat-ui.<sha>`) on push to `feat/chat-ui-package`. Manual `workflow_dispatch` with a version input handles stable releases.

Authentication is via npm Trusted Publishers (OIDC) — no token stored anywhere. Provenance signatures are attached to every published version.

### Bumping the version in `apps/web`

```bash
# in apps/web (or wherever the package is consumed)
pnpm up @heygaia/chat-ui@latest
```

Or pin to a specific prerelease for testing:

```bash
pnpm add @heygaia/chat-ui@0.0.0-feat-chat-ui.<sha>
```

## Consumer setup

### `apps/web` (this monorepo)

This package is referenced as a regular dependency in `apps/web/package.json`. The `@heygaia/*` scope resolves to the public npm registry. After publishing a new version, run `pnpm install` at the workspace root to pick up the bump.

### Motion studio (`lyon`, separate repo)

```json
"dependencies": {
  "@heygaia/chat-ui": "0.0.0-feat-chat-ui.<sha>"
}
```

Then:

```tsx
import { ChatBubbleBot, ChatBubbleUser, LoadingIndicator } from "@heygaia/chat-ui";
import "@heygaia/chat-ui/styles.css";
```

The Remotion `<GaiaScenario>` composition uses these to render scenario JSON as state-machine-driven video.

## Development

```bash
# from monorepo root
pnpm --filter @heygaia/chat-ui build       # one-shot build
pnpm --filter @heygaia/chat-ui dev         # tsup watch mode
pnpm --filter @heygaia/chat-ui type-check  # strict tsc check
```

## Status

**Pre-1.0.** The package is being shaken down on the `feat/chat-ui-package` branch (PR #677). Known follow-ups:

- TypeScript declaration emission (`dts: true`) currently disabled — re-enable after tightening residual stub typing in `Conversation.system_purpose`
- Stubs for runtime deps are no-ops; the long-term shape is a `<ChatProvider>` injection API so consumers plug in real impls
- Cross-feature components (calendar/mail/etc.) are bundled together with chat presentation — splitting into sub-paths (e.g. `@heygaia/chat-ui/calendar`) is on the roadmap

## License

UNLICENSED — internal use only.
