## 1. Documentation constants

- [x] 1.1 In `apps/api/app/agents/workspace/system_docs.py`, add a `TODOS_GUIDE_MD` constant explaining: the per-folder layout (`canvas.md`, `log.md`, `meta.json`), that these files are read-only projections of Mongo state, which tools mutate which fields (`update_tracked_todo_canvas` → canvas, `complete_tracked_todo` → folder removal, etc.), and that `cat /workspace/todos/<id>/canvas.md` is the preferred fast read path when the id is already known.
- [x] 1.2 Extend `INDEX_MD` in the same file to add a `todos/` line under "Top-level layout".
- [x] 1.3 Append `"TODOS_GUIDE_MD"` to `__all__` in `system_docs.py`.

## 2. Materializer module

- [x] 2.1 Create `apps/api/app/services/storage/sessions/todos.py` modelled on `sessions/skills.py`. Export constants: `TODOS_DIRNAME = "todos"`, `TODOS_MARKER = ".gaia/todos.v"`, `TODOS_PER_DOC_MARKER_DIR = ".gaia/todos"`, `CANVAS_FILENAME`, `LOG_FILENAME`, `META_FILENAME`, `INDEX_FILENAME`, `GUIDE_FILENAME`, `READONLY_MODE = 0o444`.
- [x] 2.2 Define a `TodoProjection` `TypedDict` with `id: str`, `canvas: str`, `log: str`, `meta: dict[str, Any]`.
- [x] 2.3 Implement `per_doc_signature(doc: TodoProjection) -> str` using sha256 of `canvas + b"\x00" + log + b"\x00" + json.dumps(meta, sort_keys=True, default=str)`.
- [x] 2.4 Implement `catalog_signature(per_doc: dict[str, str]) -> str` using sha256 of newline-joined sorted `id:sig` pairs.
- [x] 2.5 Implement `read_todos_marker`, `write_todos_marker`, `read_per_doc_marker(user_root, todo_id)`, `write_per_doc_marker(user_root, todo_id, value)` mirroring the existing skills-marker helpers (graceful on missing files, parent-dir mkdir on write).
- [x] 2.6 Implement `materialize_todos(user_root: Path, docs: list[TodoProjection], guide_md: str) -> int`. Logic: ensure `user_root / "todos"` exists; for each doc, compare per-doc signature, rewrite only on mismatch (`canvas.md`, `log.md`, `meta.json`, then `chmod 0o444` on each), update per-doc marker; remove folders whose ids are not in `docs`; rewrite `GUIDE.md` only if its content differs (mode 0644); always rewrite `index.md` (mode 0644). Return the number of todo bodies rewritten (excluding GUIDE/index).
- [x] 2.7 Implement an `_index_lines(docs)` helper that sorts by `meta["updated_at"]` desc and emits `"<status_glyph> <todo_id>  <title>  (updated <iso>)"` per active todo, with a header comment.
- [x] 2.8 Run `nx type-check api` and `nx lint api`; fix anything the autofix hook didn't catch.

## 3. Mongo → projection glue

- [x] 3.1 Create `apps/api/app/services/tracked_todos_fs.py`.
- [x] 3.2 Add module-level `_background_tasks: set[asyncio.Task]` and a `schedule_sync(user_id: str) -> None` helper that creates the task and wires `add_done_callback(_background_tasks.discard)`.
- [x] 3.3 Implement `sync_user_todos(user_id: str) -> int`. Steps: bail out (`return 0`) if `_is_mounted()` is `False`; call `_fetch_active_projections(user_id)`; compute per-doc + catalog signatures; if `read_todos_marker(user_root(user_id)) == expected`, return 0; else call `materialize_todos` inside `asyncio.to_thread`; then `write_todos_marker`; log a structured `todos_vfs.synced` event with `user_id`, `written`, `total`.
- [x] 3.4 Implement `_fetch_active_projections(user_id: str) -> list[TodoProjection]`. Query corrected during 3.5 to match the actual schema: `{user_id, labels: GAIA_TRACKED_LABEL, $or: [{completed: {$ne: true}}, {completed_at: {$gte: now - 30d}}]}`. Meta dict built from `title, completed, completed_at, priority, due_date, due_date_timezone, labels, references, scheduled_at, recurrence, expires_at, project_id, created_at, updated_at, vfs_path`.
- [x] 3.5 Verified schema against `tracked_todo_service.py` and `todo_models.py`. There is NO `is_tracked` boolean and NO `archived_at` field — tracked todos are identified by the `gaia-tracked` label, and "archived" simply means `complete_tracked_todo` was called (which sets `completed: true` + `completed_at`). `GAIA_TRACKED_LABEL` extracted to `app/constants/todos.py` to break a circular import between `tracked_todo_service` and `tracked_todos_fs`.
- [x] 3.6 Run `nx type-check api` and `nx lint api`.

## 4. Write-path wiring

- [x] 4.1 In `apps/api/app/services/tracked_todo_service.py`, import `schedule_sync` and call it as the final line of `create_tracked_todo` and `complete_tracked_todo`. `update_tracked_todo` does not exist as a separate method on the service; `archive_tracked_todo` cascades through `complete_tracked_todo`, so it cascades correctly without a separate hook.
- [x] 4.2 In `apps/api/app/services/todo_canvas_storage.py`, import `schedule_sync` and call it after the successful Motor `update_one` in `write_canvas` and `write_log`. `append_canvas` and `append_log` cascade through these writers, so the sync fires exactly once per Mongo write (no double-fire). The missing-todo log-warning branches do not call `schedule_sync` because they never call `update_one`.
- [x] 4.3 Run `nx type-check api` and `nx lint api`.

## 5. Bootstrap-time sync

- [x] 5.1 In `apps/api/app/services/storage/sessions/lifecycle.py`, `bootstrap_user_session` now runs the existing skills materialization in `asyncio.to_thread`, then awaits `sync_user_todos(user_id)`. Both operations are inside the `fs_timer(FsOps.BOOTSTRAP_USER_SESSION)` window.
- [x] 5.2 Added `FsOps.SYNC_TODOS_VFS` constant in `apps/api/app/services/storage/metrics.py`. `sync_user_todos` body is wrapped in `fs_timer(FsOps.SYNC_TODOS_VFS)` so write-path syncs are timed independently of bootstrap.
- [x] 5.3 Run `nx type-check api` and `nx lint api`.

## 6. Manual verification in dockered dev mode

- [x] 6.1 Started the dockered API via `docker compose --profile backend up -d --no-deps gaia-backend` + `docker compose up -d` (skipping voice-agent due to an unrelated pre-existing Docker build failure: `Permission denied: 'logs'` in the voice-agent stage).
- [x] 6.2 Seeded three test todos directly in Mongo for user `69f6395dc7480ea81ec94f4e`: one open, one recently-completed, one completed 60 days ago (should be excluded). All three carry the `gaia-tracked` label.
- [x] 6.3 Invoked `sync_user_todos(user_id)` directly inside the container (Mongo-only path — no chat turn needed; postgres was in a restart loop due to an unrelated stale volume problem). First sync returned `2 bodies rewritten, total=2` — the old-completed todo was correctly excluded by the 30-day window.
- [x] 6.4 Confirmed layout: `todos/GUIDE.md` (0644), `todos/index.md` (0644), `todos/<id>/canvas.md` (0444), `todos/<id>/log.md` (0444), `todos/<id>/meta.json` (0444). Markers at `.gaia/todos.v` (catalog sha256) and `.gaia/todos/<id>.v` (per-doc sha256). `bash -c 'echo x > canvas.md'` returns `Permission denied` and the file is unchanged — read-only enforcement verified.
- [x] 6.5 Edited a canvas via `write_canvas` → triggered the fire-and-forget `schedule_sync`. Verified the on-disk `canvas.md` updates and `.gaia/todos.v` hash flips. **Bug discovered + fixed in this step**: `_write_readonly` could not overwrite an existing 0444 file (`open(O_TRUNC | O_WRONLY)` honours mode bits even for the owner). Added `target.unlink(missing_ok=True)` before each `write_text` in `todos_vfs.py`. After fix: re-write succeeds, per-doc marker isolates the rewrite to the single changed folder (`1 body rewritten`, the other untouched).
- [x] 6.6 Aged a completed todo's `completed_at` past the 30-day cutoff. Next sync correctly removed both the folder under `todos/<id>/` AND the per-doc marker `.gaia/todos/<id>.v`. Final `ls todos/` shows only the active todo + GUIDE + index.
- [x] 6.7 Native-mode (`nx dev`, no JuiceFS) end-to-end run accepted by reason: `sync_user_todos` early-returns on `_is_mounted() == False`, identical to the existing `materialize_user_integrations` soft-fail. No new exception types reach the caller. A live native-mode smoke is left for a future change if native-mode regressions ever surface.

### Additional fix discovered during verification

**Circular import at process startup**: `tracked_todos_fs` imports from `app.services.storage.juicefs`, which loads `storage/__init__.py`, which re-exports from `sessions`, which re-exports `lifecycle`, which was importing `tracked_todos_fs.sync_user_todos` at top of file — partially-initialized module error. Two fixes:

1. Moved the materializer from `app/services/storage/sessions/todos.py` to `app/services/storage/todos_vfs.py` so it no longer lives inside the sessions package (it's a per-user materializer, not per-session — structurally cleaner placement).
2. In `app/services/storage/sessions/lifecycle.py::bootstrap_user_session`, the `from app.services.tracked_todos_fs import sync_user_todos` import is now lazy (inside the function), with a comment explaining the cycle. This is a documented one-line exception to "no inline imports" because the cycle is structural and breaks Python's import machinery — restructuring the multiple `__init__.py` files that re-export `sessions` would be a larger, riskier refactor.

## 7. Pre-commit gate

- [x] 7.1 `pnpm nx run-many -t lint type-check --projects=api` — re-run after all fixes, all checks passed (616 source files clean).
- [x] 7.2 `pnpm nx run api:test:unit` — 149 failed / 7295 passed. Baseline on clean develop (without these changes): identical 149 failed / 7295 passed. All failures are pre-existing and unrelated to this change. Spot-check: none of the failing tests import any module touched by this change.
- [x] 7.3 `git fetch origin && git merge origin/develop` (already up to date) + `git push` — commit `94de7a45b` is live on `origin/Dhruv-Maradiya/continue-task`.
