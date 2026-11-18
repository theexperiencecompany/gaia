---
name: parallel-worktrees
description: Use when running several GAIA branches at once with worktrunk (`wt`) — creating a worktree, giving it its own dev ports, provisioning env/deps, and merging back. Covers the port scheme, the single-instance bot constraint, and troubleshooting collisions.
---

# Parallel Worktrees (worktrunk + mise)

Run multiple GAIA branches side by side. Each worktree gets its own copy of the
repo, its own gitignored env files, its own dev ports, Mongo database, Redis and
RabbitMQ vhost, so `mise dev` (or `mise dev --sim`) in one worktree never collides
with another. The shared Docker containers (Mongo, Postgres, RabbitMQ, Chroma) are
used by all worktrees at once; Postgres and Chroma are shared, the rest is split.

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
callback runs on the default ports: `mise run wt:env -- --default-ports` in that
worktree (the main checkout's ports and shared database), and make sure no other
worktree holds them. Run `mise run wt:env` again to get the worktree's own slot back.

`mise run wt:env` (`scripts/dev/wt_env.py`) gives each linked worktree a **slot**
(1-199): the one its path hashes to, or the next one no other worktree's
`.env.worktree` holds, skipping any slot whose ports hit the main checkout's or
the shared infra's. Allocation takes a repo-wide lock, so two worktrees never get
the same slot. A worktree keeps its slot on rerun. The offset is `slot * 10`.
mise auto-loads the file for every task via `[env]._.file`. A linked worktree
without it, or a process started outside mise (bare `pnpm dev`, `uv run`), refuses
to start (`scripts/dev/require-worktree-env.sh`) instead of using 8000/3000 and
the `GAIA` database. The main checkout keeps today's defaults.

| Service | Var | Value | Main (offset 0) |
|---|---|---|---|
| API (uvicorn) | `API_PORT` | `8000 + offset` | 8000 |
| API (dockered, `dev:vm`) | `API_HOST_PORT` | `8000 + offset` | 8000 |
| Web (Next.js) | `WEB_PORT` | `3000 + offset` | 3000 |
| API → web URL (redirects, links) | `FRONTEND_URL` | `http://localhost:$WEB_PORT` | …:3000 |
| Web → API URL | `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:$API_PORT/api/v1/` | …8000/api/v1/ |
| Bots/`gaia-sim` → API URL | `GAIA_API_URL` | `http://localhost:$API_PORT` | …:8000 |
| Scripted LLM stub (`dev --sim`) | `LLM_STUB_PORT` | `9797 + offset` | 9797 |
| ARQ worker metrics | `ARQ_METRICS_PORT` | `8005 + offset` | 9100 |
| Discord / Slack / Telegram / WhatsApp / iMessage bot | `BOT_<NAME>_PORT` | `3001..3005 + offset` | 3200..3204 |
| Private Redis | `WT_REDIS_PORT`, `REDIS_URL` | `6383 + offset` | shared :6379 |
| Mongo database | `MONGO_DB_NAME` | `gaia_wt<offset>` | `GAIA` |
| RabbitMQ vhost | `RABBITMQ_VHOST`, `RABBITMQ_URL` | `gaia_wt<offset>` | `/` |
| Chroma collections | `GAIA_CHROMA_COLLECTION_SUFFIX` | `_wt<offset>` | none |

Each range ends in its own last digit, so no two slots share a port. `nx run
docker:docker:up` (`scripts/dev/docker-up.sh`) starts the private Redis as compose
project `gaia-wt<offset>` and creates the vhost; it starts the shared containers
with `--no-recreate`, so a boot from one worktree never restarts another's
Postgres or RabbitMQ.

`NEXT_PUBLIC_API_BASE_URL` is exported into the process env, which Next.js ranks
above `apps/web/.env.local` (Next's load order puts `process.env` first), so the
web app in a worktree talks to that worktree's own API even though `.env.local`
was copied from main.


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
bot's `dev` target serves its health/webhook server on this worktree's
`BOT_<NAME>_PORT`.

## Own database, Redis and vhost per worktree

Each linked worktree writes to its own Mongo database, Redis and RabbitMQ vhost,
so two worktrees can run `mise e2e:web` or two sim stacks at once without wiping
each other's seeded user or taking each other's ARQ jobs. Still shared: Postgres
(LangGraph checkpoints, keyed by thread) and the Chroma server (split by
collection suffix). Drop a worktree's database with `mise run sim:down --purge`.

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
  `mise run wt:env`. A file from before slots may share a port with another
  worktree's: rerun `mise run wt:env`. Without the preflight this failed silently: uvicorn exited,
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
- **`this linked worktree has no .env.worktree` / `is not loaded into this process`**
  — run `mise run wt:env`, then start through mise (`mise dev`, `mise dev --sim`),
  not a bare `pnpm`/`nx`/`uv` command or another checkout's shell.
- **New worktree has no secrets** — the `copy-ignored` hook only copies files that
  are both gitignored and in `.worktreeinclude`. If you added a new secret file,
  add its path to `.worktreeinclude` and re-run `wt step copy-ignored`.
- **`JuiceFSUnavailable`** — unrelated to worktrees; native `mise dev` cannot mount
  JuiceFS. Use `mise dev:vm` for workspace-v2 / file-upload / sandbox work (see
  `apps/api/CLAUDE.md`).
- **Telegram `409` / bot fighting** — the same bot is running in another worktree.
  Stop it there. See the single-instance section above.
