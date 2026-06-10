## Why

GAIA's executor agent already navigates `/workspace/integrations/` and `/workspace/skills/` as a real filesystem (one folder per integration, `GUIDE.md` per area, `skill.md` per capability). Tracked todos — GAIA's institutional memory — are hidden behind tool calls and only reachable via `list_tracked_todos` + `search_todo_context`. We want the agent to discover and read its own memory the same way it discovers everything else: `ls /workspace/todos/`, `cat /workspace/todos/<id>/canvas.md`. This composes with the existing `GUIDE.md` pattern and removes one bespoke vocabulary the agent has to learn.

## What Changes

- Add a new directory tree on JuiceFS at `/mnt/jfs/users/{user_id}/todos/`, visible to the executor sandbox at `/workspace/todos/`.
- Each active tracked todo (`is_tracked: true`, not archived, and either not completed or completed within the last 30 days) gets a folder `<todo_id>/` containing `canvas.md`, `log.md`, and `meta.json`.
- Add a hand-authored `/workspace/todos/GUIDE.md` plus a generated `/workspace/todos/index.md` (one-line-per-todo summary).
- MongoDB stays canonical. The on-disk tree is a hash-gated projection — same machinery as the existing SKILL.md catalog under `apps/api/app/services/storage/sessions/skills.py`.
- Reads come from real files. Writes continue through the existing tracked-todo tools (`create_tracked_todo`, `update_tracked_todo`, `update_tracked_todo_canvas`, `complete_tracked_todo`, `archive_tracked_todo`); each tool now schedules a fire-and-forget projection sync after its Mongo write commits.
- Projected files (`canvas.md`, `log.md`, `meta.json`) are mode `0444`. Raw `Edit` / `Write` calls fail loudly so the agent cannot silently desync the projection.
- The bootstrap path (`apps/api/app/services/storage/sessions/lifecycle.py::bootstrap_user_session`) runs the todos sync each turn so a crash between Mongo write and FS rewrite self-heals on next session entry.
- Native (`mise dev`, no JuiceFS) mode: the sync soft-fails when the mount is missing, identical to the skill catalog's existing degradation. No new code path.

## Capabilities

### New Capabilities
- `tracked-todos-vfs`: filesystem projection of MongoDB tracked todos under `/workspace/todos/`, plus the hash-gated materializer and sync-on-write glue that keeps it consistent.

### Modified Capabilities
<!-- None. The tracked-todo Mongo schema, write-tool signatures, and search semantics are unchanged. -->

## Impact

- **Code**:
  - New: `apps/api/app/services/storage/sessions/todos.py` (materializer), `apps/api/app/services/tracked_todos_fs.py` (Mongo → projection glue).
  - Modified: `apps/api/app/agents/workspace/system_docs.py` (add `TODOS_GUIDE_MD`, extend `INDEX_MD`), `apps/api/app/services/storage/sessions/lifecycle.py` (call todos sync from `bootstrap_user_session`), `apps/api/app/services/tracked_todo_service.py` (schedule sync after each mutating method), `apps/api/app/services/todo_canvas_storage.py` (schedule sync after canvas/log writes).
  - Optional follow-up (separate change): executor system prompt mentions `/workspace/todos/` so the agent uses the new surface.
- **APIs**: no public-API changes; no new endpoints; no schema migrations.
- **Dependencies**: none added. Reuses `JuiceFS`, `Motor`, `asyncio.to_thread`, existing `app.services.storage.sessions._paths` helpers, and the existing fire-and-forget pattern (`_background_tasks: set[asyncio.Task]`).
- **Storage**: per active todo we write three small files plus one per-doc hash marker under `.gaia/todos/`. JuiceFS writeback batches the actual R2 PUTs, so the steady-state cost is one R2 flush per write-back interval (seconds), not per edit.
- **Runtime**: bootstrap adds one Mongo query (`db.todos.find` over the user's active set) per session entry. Marker check makes this a no-op when nothing changed since the last sync.
- **Backwards compatibility**: zero. Mongo schema unchanged; existing tools have identical signatures; existing tests don't need to know about the projection.
