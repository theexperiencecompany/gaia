---
name: parallel-worktrees
description: Use when running several GAIA branches at once with worktrunk (`wt`) — creating a worktree, giving it its own dev ports, provisioning env/deps, and merging back. Covers the port scheme, the single-instance bot constraint, and troubleshooting collisions.
---

# Parallel Worktrees (worktrunk + mise)

Run multiple GAIA branches side by side. Each worktree gets its own copy of the
repo, its own gitignored env files, and a deterministic set of dev ports so
`mise dev` in one worktree never collides with another. Shared Docker infra
(Mongo/Postgres/Redis/RabbitMQ/Chroma) is used by all worktrees at once.

`wt` is pinned in `mise.toml [tools]` (`ubi:max-sixty/worktrunk`), so every clone
has it. Run it via the mise shim (`wt ...`) or `mise exec -- wt ...`.

## One-time setup (per machine)

```bash
wt config shell install   # enables `wt switch` to cd for you; restart the shell after
wt config state default-branch set master   # GAIA merges everything into `master`
```

**GAIA's base branch is `master`** — the remote's `origin/HEAD` points at `master`,
so worktrunk detects it correctly on fresh clones. New feature branches are cut from
`master` — fetch it fresh before branching, and merge `master` back in to keep the
PR mergeable.

## Create a worktree and start working

```bash
wt switch -c feat/my-thing      # creates the worktree + branch, runs pre-start hooks
mise dev                        # API + web on THIS worktree's ports (see below)
mise seed                       # mint + seed the dev bypass user against this API
```

`wt switch -c` fires the `.config/wt.toml` `pre-start` hooks, which run once at
creation and block until done:

1. `wt step copy-ignored` — copies the gitignored secret files listed in
   `.worktreeinclude` (`apps/api/.env`, `apps/web/.env.local`, `apps/bots/.env`)
   from the main worktree.
2. `mise run wt:env` — allocates this worktree's ports → `.env.worktree`.
3. `pnpm install` + `nx run api:sync` — concurrently; both are fast (pnpm shared
   store + uv cache), and neither copies `node_modules`/`.venv`.

When the command returns, `mise dev` works immediately with isolated ports.

## Ports

**OAuth / integration work needs the default 8000 + 3000.** Redirect URIs are
registered with the provider (WorkOS, Composio, Google, …), and only
`localhost:8000` / `localhost:3000` are registered — a worktree on 8140/3140
gets its callback rejected, so connecting an integration cannot complete. Any
task that connects an account, tests a connect card, or touches an OAuth
callback runs on the default ports: `rm .env.worktree` in that worktree (mise
falls back to 8000/3000), and make sure no other worktree holds them. Register
the offset ports with the provider only if you genuinely need two OAuth-capable
worktrees at once.

`mise run wt:env` hashes the worktree path → an offset (a multiple of 10, 10–1990)
and writes `.env.worktree` at the repo root. mise auto-loads that file for every
task via `[env]._.file`; the main worktree has no file (offset 0) and keeps
today's defaults. Delete `.env.worktree` to fall back to defaults.

| Service | Var | Value | Main (offset 0) |
|---|---|---|---|
| API (uvicorn) | `API_PORT` | `8000 + offset` | 8000 |
| API (dockered, `dev:vm`) | `API_HOST_PORT` | `8000 + offset` | 8000 |
| Web (Next.js) | `WEB_PORT` | `3000 + offset` | 3000 |
| API → web URL (redirects, links) | `FRONTEND_URL` | `http://localhost:$WEB_PORT` | …:3000 |
| Web → API URL | `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:$API_PORT/api/v1/` | …8000/api/v1/ |
| Bots/`gaia-sim` → API URL | `GAIA_API_URL` | `http://localhost:$API_PORT` | …:8000 |
| Scripted LLM stub (`dev --sim`) | `LLM_STUB_PORT` | `9797 + offset` | 9797 |
| Discord bot | `BOT_DISCORD_PORT` | `3200 + offset` | 3200 |
| Slack bot | `BOT_SLACK_PORT` | `3201 + offset` | 3201 |
| Telegram bot | `BOT_TELEGRAM_PORT` | `3202 + offset` | 3202 |
| WhatsApp bot | `BOT_WHATSAPP_PORT` | `3203 + offset` | 3203 |

`NEXT_PUBLIC_API_BASE_URL` is exported into the process env, which Next.js ranks
above `apps/web/.env.local` (Next's load order puts `process.env` first), so the
web app in a worktree talks to that worktree's own API even though `.env.local`
was copied from main.

The offset is deterministic per path but two paths can theoretically hash to the
same offset. If two live worktrees collide, rename one (`wt switch` to a
differently-named branch/dir) and re-run `mise run wt:env`.

## Single-instance bots — do NOT run the same bot twice

Discord, Telegram, Slack, and WhatsApp each authenticate with **one** bot token.
Running the same bot in two worktrees makes both connect with that token:
Telegram returns `409 Conflict` (getUpdates), Discord/Slack sessions fight, and
webhook deliveries get split. The per-worktree bot *ports* only stop the local
HTTP health/webhook servers from colliding — they do not give you a second bot
identity.

Rule: run any given bot in **at most one worktree at a time**. `mise dev` (API +
web only) never starts a bot, so most parallel work is unaffected. If you must
run a bot in a non-main worktree, stop it in the other worktree first. To point a
single bot's health/webhook server at this worktree's port, set the bot's single
override explicitly, e.g. `BOT_SERVER_PORT=$BOT_WHATSAPP_PORT nx dev bot-whatsapp`
(`BOT_SERVER_PORT` overrides all four defaults, so set it per single-bot launch,
not globally).

## Shared database — one seeded dev user at a time

Ports are per-worktree; the Docker infra (Mongo/Postgres/Redis/RabbitMQ/Chroma)
is **shared**. So anything that writes to a fixed key collides across worktrees.
The web e2e suite is the sharp edge: its `global-setup` resets → mints → seeds
`DEV_USER` (default `dev@gaia.local`), so two worktrees running `mise e2e:web`
at once wipe each other's data mid-run.

Rule: run e2e in **one worktree at a time**, or give a worktree its own identity
by setting `DEV_USER=<email>` — the `--agent` / `--sim` flags on `mise dev` /
`dev:vm` derive the API's `DEV_AUTH_BYPASS_EMAIL` from `DEV_USER`, so a single
value sets both the e2e seed target and the server's bypass identity. They must
match because browser page loads carry no `X-Dev-User` header, so the seeded user
has to equal the server's bypass email. Full per-worktree DB isolation is
deferred; until then this is the constraint.

## Merge back

Repo git rules apply (see root `CLAUDE.md`):

- `master` is the single base branch — branch from and merge into `master`.
  If `wt switch -c` creates branches from anything else, the default-branch state is
  wrong on this clone: run `wt config state default-branch set master` (see One-time setup).
- Plain merge only. Never `git rebase` / `git pull --rebase` against `origin/master`.
- Never merge PRs (`gh pr merge` and `wt merge` are both off-limits) — the team merges.

Hand-off flow: sync with master, push the branch, open a PR:

```bash
git fetch origin && git merge origin/master && git push -u origin HEAD
```

```bash
wt list           # show all worktrees + status
wt remove         # remove the current worktree; deletes the branch if merged
```

## Troubleshooting

- **`port NNNN is already in use by PID …` on `mise dev` (incl. `--sim`)** — the
  preflight (`scripts/dev/check-ports.sh`) refused to start because another
  worktree or a stale server holds the port; the message names the process. Kill
  it, or confirm `.env.worktree` exists here (`cat .env.worktree`) and re-run
  `mise run wt:env`. Offset collision between two worktrees → rename one and
  re-run `wt:env`. Without the preflight this failed silently: uvicorn exited,
  nx kept web alive, and every request went to the *other* worktree's API.
- **Web calls the wrong API** — check `NEXT_PUBLIC_API_BASE_URL` in `.env.worktree`
  matches this worktree's `API_PORT`; restart `nx dev web` so Next re-reads the env.
- **`.env.worktree` missing** — run `mise run wt:env`. A brand-new worktree gets it
  from the pre-start hook; running the task again is safe and idempotent.
- **`no task //:wt:env found` during `wt switch -c`** — the branch predates the worktree
  infra (added Jul 2026 in `7f3cd4115`), so its `mise.toml` lacks the `wt:env` task,
  the `_.file = ".env.worktree"` auto-load, and the `--port=${WEB_PORT:-3000}` dev script.
  Run the port script manually (or `git merge origin/master` to bring the infra in),
  then export the port when running the dev server: `pnpm nx run web:next:dev --port=3040`.
- **New worktree has no secrets** — the `copy-ignored` hook only copies files that
  are both gitignored and in `.worktreeinclude`. If you added a new secret file,
  add its path to `.worktreeinclude` and re-run `wt step copy-ignored`.
- **`JuiceFSUnavailable`** — unrelated to worktrees; native `mise dev` cannot mount
  JuiceFS. Use `mise dev:vm` for workspace-v2 / file-upload / sandbox work (see
  `apps/api/CLAUDE.md`).
- **Telegram `409` / bot fighting** — the same bot is running in another worktree.
  Stop it there. See the single-instance section above.
