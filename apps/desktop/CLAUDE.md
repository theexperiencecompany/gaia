# apps/desktop

Electron desktop wrapper for the GAIA web app. It embeds the Next.js app (from `apps/web`) as a standalone server and loads it in a BrowserWindow. Built with electron-vite.

## Key Commands

```bash
# Dev (starts web app + Electron in parallel)
nx dev desktop

# Build Electron main/preload only
nx build desktop

# Package for distribution (builds web first, then packages)
nx dist:mac desktop
nx dist:win desktop
nx dist:linux desktop

# Lint
nx lint desktop

# Type check
nx type-check desktop
```

## Architecture

- `src/main/` — Electron main process only. No renderer code lives here.
  - `index.ts` — Entry point: startup sequence, single-instance lock, lifecycle
  - `server.ts` — Spawns the embedded Next.js server in production
  - `ipc.ts` — All IPC handler registrations
  - `windows/` — BrowserWindow creation (main window + splash screen)
  - `auto-updater.ts`, `deep-link.ts`, `protocol.ts`, `session.ts` — Single-responsibility modules
- `src/preload/` — Preload scripts (context bridge between main and renderer)
- The renderer UI is the `apps/web` Next.js app — do not add UI code here

**Startup order**: protocol registration → single-instance lock → splash screen → IPC/session setup → Next.js server start + main window creation (parallel) → splash-to-main swap on `window-ready` IPC or 10 s fallback.

**`gaia://` deep link** protocol is registered before `app.ready`. Deep links received before the window is ready are queued via `setPendingDeepLink`.

**Production vs dev**: In dev, Electron loads the Next.js dev server URL directly. In production, `server.ts` starts the embedded Next.js standalone server.

## Code Style

- Package manager: **pnpm** (never npm or yarn)
- Linter: **Biome** (`nx lint desktop` / `nx lint:fix desktop`) — not ESLint
- TypeScript strict mode; **never use `any`**
- All imports at the top of the file — no inline imports
- Before creating new types, check if they already exist in this file or `src/main/`
- Do not create test files unless explicitly asked
- `noConsole` rule is disabled in `biome.json` — console logs are allowed in the main process

## Gotchas

- `implicitDependencies: ["web"]` — the desktop app depends on `apps/web`; a web build is required before packaging
- Distribution targets (`dist:mac`, `dist:win`, `dist:linux`) run `nx build web --skip-nx-cache` and a `prepare-next-server` script before packaging; do not skip these steps
- `NEXT_PUBLIC_API_BASE_URL` is set to `https://api.heygaia.io/api/v1/` during packaging — override via env if targeting a different backend
- Path alias `@/*` maps to `./src/*`
- Output dirs: `out/` (electron-vite build), `dist/` (electron-builder packages)
