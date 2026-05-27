## Context

GAIA's executor agent runs inside an e2b sandbox that sees a JuiceFS-backed workspace at `/workspace`. Today, the agent can `ls /workspace/integrations/` and `cat /workspace/skills/<slug>/skill.md` because those are real files materialized to JuiceFS by `apps/api/app/services/storage/sessions/skills.py`. Tracked todos — the long-term memory layer the executor uses via `gaia-task-tracking/SKILL.md` — have no filesystem surface. Their canvas and log live as fields on the Mongo `todos` document (`apps/api/app/services/todo_canvas_storage.py`); the `vfs_path` field is a display label, not a real path. The team previously removed the per-todo VFS files for cost reasons, so any reintroduction must keep R2 write traffic bounded.

JuiceFS is only mounted in dockered API mode (`mise dev:vm`); native `mise dev` raises `JuiceFSUnavailable`. The 8GB self-host box co-locates API + worker + infra (Mongo is off-box). Both constraints rule out a background sync daemon or any second canonical store.

## Goals / Non-Goals

**Goals:**

- `ls /workspace/todos/` lists one folder per active tracked todo, and `cat /workspace/todos/<id>/canvas.md` returns the same string `read_canvas(todo_id, user_id)` would.
- Mongo remains the single source of truth; reads come from JuiceFS, writes flow through the existing tracked-todo tools.
- Steady-state turns do zero I/O (matches the SKILL.md catalog's `.gaia/skills.v` hash-marker pattern).
- One bootstrap-time sync per session repairs any drift caused by crashes between Mongo writes and FS rewrites.
- Native mode (`mise dev`, no JuiceFS) keeps working — the materializer soft-fails identically to `materialize_skills` today.

**Non-Goals:**

- No write-through-files surface. `canvas.md`, `log.md`, `meta.json` are mode `0444`. Editing through `Write`/`Edit` is unsupported in this change.
- No `mkdir` / `rm` for creating or deleting todos. Lifecycle stays on the existing tools.
- No FUSE sidecar, 9P server, or `gaia` CLI shim.
- No ctl-files (`.status`, `.due`). The tool surface covers state transitions.
- No materialization for completed-and-archived-long-ago todos. `search_todo_context` continues to cover that range via ChromaDB.
- No feature flag — this lands on directly. Rollback is `rm -rf /mnt/jfs/users/<uid>/todos /mnt/jfs/users/<uid>/.gaia/todos*` plus reverting the commit.
- No changes to executor system prompts in this change. A follow-up change nudges the agent toward the new paths once telemetry is green.

## Decisions

### D1. Mongo stays canonical; filesystem is a hash-gated projection

The agent reads from files, but every byte on disk is derived from a Mongo document. Tools that mutate todos write to Mongo first, then schedule a fire-and-forget projection sync.

*Alternatives considered:* (a) JuiceFS-as-source-of-truth — rejected because every canvas keystroke would round-trip to R2 and Mongo would still need to mirror the data for the existing search/list paths. (b) FUSE/9P synthetic FS served by a sidecar — rejected as unjustified complexity on an 8GB box. (c) Read-only virtual `gaia ls/cat` CLI — rejected because the user explicitly wants literal `ls`.

### D2. Reuse the SKILL.md hash-marker scheme

Per-user marker at `<uid>/.gaia/todos.v` (sha256 of `id:per_doc_v` pairs) gates the full-tree rewrite. Per-todo marker at `<uid>/.gaia/todos/<id>.v` (sha256 of canvas + log + meta) gates the single-folder rewrite. The materializer is otherwise a copy of `materialize_skills`' shape: idempotent, pure-function, soft-failing on missing mount.

*Alternatives considered:* (a) Mongo change streams pushing to JuiceFS — rejected because no other piece of GAIA depends on change streams, and adding the dependency for this is disproportionate. (b) ETag stored on the Mongo doc and compared on every read — rejected because it forces a Mongo round-trip even when nothing changed.

### D3. Read-only mode `0444` on projected files

After writing each `canvas.md` / `log.md` / `meta.json`, chmod to `0444`. This turns "agent ran `sed -i` on canvas.md" from a silent-loss bug into an `EACCES` the agent will see and surface.

`GUIDE.md` and `index.md` stay `0644` because we author them; no need to harden against ourselves.

*Alternatives considered:* (a) Allow raw edits + watch with inotify and re-import to Mongo — rejected as a foot-gun multiplier (concurrent edits, partial writes, conflict resolution, etc.). (b) Document the contract in GUIDE.md but leave files writable — rejected; the user previously noted that silent suppression of failure beats loud failure ([feedback_no_inline_suppression]). Loud `EACCES` is exactly that.

### D4. Active window: not archived AND (status != completed OR completed within 30 days)

Matches the spirit of the existing `list_tracked_todos` cap of 50 active items. Older items remain searchable via `search_todo_context` (ChromaDB embeds completed canvases too).

*Alternatives considered:* (a) All todos forever — rejected because users with hundreds of historical todos would see a cluttered `ls`. (b) Active-only (no completed) — rejected because users routinely revisit very-recently-completed todos.

### D5. Sync triggers on every mutating write path

`tracked_todo_service.create_tracked_todo`, `update_tracked_todo`, `complete_tracked_todo`, `archive_tracked_todo`, and `todo_canvas_storage.{write,append}_{canvas,log}` each call `schedule_sync(user_id)` as the last step after Mongo commits. Sync is fire-and-forget; the user-facing tool response does not block on it.

*Alternatives considered:* (a) Sync only at bootstrap — rejected; agents that touch a canvas mid-conversation would see stale content on the next `cat`. (b) Synchronous sync inside the tool — rejected because the chat-turn latency cost is not worth it; the agent rarely re-reads a file it just wrote in the same turn.

### D6. Bootstrap-time sync repairs drift

`apps/api/app/services/storage/sessions/lifecycle.py::bootstrap_user_session` calls `sync_user_todos(user_id)` after the existing skills materialization. This catches: first deploy, schema migrations, lost fire-and-forget tasks (process restart), and any race where a previous sync raced its own update.

### D7. Native mode soft-fails identically to the skill catalog

`sync_user_todos` short-circuits on `_is_mounted() == False`. Same code path as `materialize_user_integrations`. The agent in native mode sees no `/workspace/todos/` and falls back to the existing tools — same way the integrations subtree is absent today.

## Risks / Trade-offs

- **[Stale projection between Mongo commit and FS write]** → fire-and-forget sync may lose updates if the process crashes mid-flight. Mitigation: bootstrap-time sync recomputes from Mongo; the marker-mismatch detection self-heals on next session entry. Worst case: one chat turn sees stale content; never lost data, because Mongo is canonical.

- **[Agent ignores GUIDE.md and tries to edit canvas.md directly]** → file is `0444`, so the write fails with `EACCES`. The agent's error output makes the misuse obvious. Documented in `TODOS_GUIDE_MD`. Better than the "silent overwrite on next sync" behavior of writable projections.

- **[Two parallel sessions edit the same todo simultaneously]** → Mongo `update_one` serializes; last-writer-wins is the existing contract for canvas appends. The on-disk projection converges within one sync (≤ a few hundred ms). A `cat` between commit and sync sees the older string; never a torn write because materializer overwrites whole files via `Path.write_text`.

- **[Per-user listing cost on bootstrap]** → one `find()` over `{user_id, is_tracked: true, ...}` per session entry. The query is indexed (existing `user_id` + `is_tracked` index). With the marker check, 99% of bootstraps short-circuit without touching the files.

- **[R2 cost growth]** → every materialization writes 3 small files per changed todo, batched by JuiceFS writeback. Order-of-magnitude estimate: 10 canvas edits/user/day × 3 files = 30 small-file writes coalesced into ~10 R2 PUTs/user/day after writeback. Bounded by the same writeback policy that already governs skill catalogs.

- **[Background task GC]** → fire-and-forget tasks can be garbage-collected if not held. Mitigation: module-level `_background_tasks: set[asyncio.Task]` plus `add_done_callback(_background_tasks.discard)`, mirroring `tracked_todo_tools._background_tasks` and `apps/api/app/agents/core/agent.py::_background_tasks`.

- **[Race between fire-and-forget sync and bootstrap sync]** → both call `read_todos_marker` + materialize. Re-running materialization with the same Mongo state is idempotent (per-doc marker matches, no rewrites). The two callers cannot corrupt each other; worst case is one wasted Mongo `find()`.

- **[`is_tracked` / `archived_at` field name drift]** → query in `_fetch_active_projections` hard-codes field names. Mitigation: implement Task 4 by reading the actual fields off `tracked_todo_service` and matching exactly; add an integration test that creates → archives → completes → re-reads via the materializer to catch schema mismatches.

## Migration Plan

1. Land Tasks 1–6 in a single PR. No data migration; the materializer back-fills lazily on first session entry per user.
2. Deploy. First session per user incurs a one-time write of their active-todo folders (typically ≤ 50 todos × 3 files = under 200 small files on JuiceFS, coalesced by writeback).
3. Monitor JuiceFS-write and FS-bootstrap metrics for ≥ 24h. Look for: bootstrap-time outliers, sync-after-write tail latency, marker-mismatch rate (should converge near zero after backfill completes).
4. **Rollback**: revert the PR; run `rm -rf /mnt/jfs/users/*/todos /mnt/jfs/users/*/.gaia/todos*` on the host as a follow-up cleanup. Mongo is untouched; no data is lost.
5. Once telemetry is green, ship a separate change updating the executor system prompt to mention `/workspace/todos/`. Without that, the agent still works but doesn't use the new tree.

## Open Questions

- **Q1**: Should `meta.json` include a `vfs_path` echoing the on-disk folder (`"path": "/workspace/todos/<id>"`) to ease cross-referencing in canvas references, or is the directory location obvious enough? *Default: omit; the file IS at that path, and the agent already knows it.*
- **Q2**: Do we want `index.md` to include completed-within-30-days todos with a "✅ " prefix, or only currently-active ones? *Default: include both; the prefix makes the line scannable, and dropping completeds defeats the 30-day window.*
- **Q3**: Should the materializer write `log.md` even when empty? *Default: yes, write an empty file; consistent shape across all folders makes `find /workspace/todos -name log.md` predictable.*
