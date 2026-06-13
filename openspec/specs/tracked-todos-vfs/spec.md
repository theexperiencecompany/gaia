# tracked-todos-vfs Specification

## Purpose
TBD - created by archiving change tracked-todos-as-files. Update Purpose after archive.
## Requirements
### Requirement: Active tracked todos appear as folders under `/workspace/todos/`

The system SHALL materialize one folder per active tracked todo at `{user_root}/todos/{todo_id}/` on the JuiceFS host mount, visible inside the executor sandbox as `/workspace/todos/{todo_id}/`. A tracked todo is "active" when its `labels` array contains the `gaia-tracked` label AND either `completed` is false/missing OR `completed_at >= now - 30 days`. There is no separate "archived" field in the schema — `archive_tracked_todo` calls `complete_tracked_todo`, so archived and completed are the same state.

#### Scenario: Active todo is materialized

- **WHEN** a user has a tracked todo whose `labels` includes `"gaia-tracked"` and whose `completed` field is `false` or absent
- **AND** a sync runs (either bootstrap-time or post-write)
- **THEN** the directory `{user_root}/todos/{todo_id}/` exists
- **AND** it contains `canvas.md`, `log.md`, and `meta.json`

#### Scenario: Completed todo within window stays projected

- **WHEN** a tracked todo's `completed` becomes `true` with `completed_at` within the last 30 days
- **AND** a sync runs
- **THEN** the directory `{user_root}/todos/{todo_id}/` continues to exist

#### Scenario: Completed todo outside window drops out

- **WHEN** a tracked todo's `completed_at` is older than 30 days
- **AND** a sync runs
- **THEN** the directory `{user_root}/todos/{todo_id}/` is removed if previously present, and SHALL NOT be re-created

#### Scenario: Archive cascades through completion

- **WHEN** `archive_tracked_todo` is invoked (which internally calls `complete_tracked_todo`)
- **AND** a sync runs
- **THEN** the todo's folder follows the completed-within-30-days lifecycle above — it remains projected until `completed_at` falls outside the 30-day window

### Requirement: Projected file contents mirror MongoDB fields exactly

For every projected todo folder, `canvas.md` SHALL contain the exact byte string of the Mongo `canvas_content` field, `log.md` SHALL contain the exact byte string of `log_content`, and `meta.json` SHALL contain a JSON object with the todo's metadata fields (`title`, `completed`, `completed_at`, `priority`, `due_date`, `due_date_timezone`, `labels`, `references`, `scheduled_at`, `recurrence`, `expires_at`, `project_id`, `created_at`, `updated_at`, `vfs_path`). All files SHALL be UTF-8 encoded.

#### Scenario: Empty canvas projects as an empty file

- **WHEN** a todo has `canvas_content` unset or `""`
- **AND** a sync runs
- **THEN** `canvas.md` exists with zero bytes

#### Scenario: Empty log projects as an empty file

- **WHEN** a todo has `log_content` unset or `""`
- **AND** a sync runs
- **THEN** `log.md` exists with zero bytes

#### Scenario: Canvas edit is reflected on disk

- **WHEN** `update_tracked_todo_canvas` commits a new `canvas_content` value to Mongo
- **AND** the post-write sync completes
- **THEN** `cat {user_root}/todos/{todo_id}/canvas.md` returns the new value byte-for-byte

#### Scenario: Meta JSON serializes dates as ISO-8601 strings

- **WHEN** the materializer writes `meta.json`
- **THEN** every datetime field (`due_date`, `scheduled_at`, `created_at`, `updated_at`, `completed_at`) is serialized as an ISO-8601 string with timezone offset, or `null` if unset

### Requirement: Projected files are read-only

`canvas.md`, `log.md`, and `meta.json` inside any `{user_root}/todos/{todo_id}/` directory SHALL have file mode `0444` immediately after each rewrite by the materializer.

#### Scenario: Agent attempting to write canvas.md gets EACCES

- **WHEN** the executor agent (or any process inside the sandbox) attempts to open `canvas.md` for writing
- **THEN** the open fails with `EACCES` / Permission denied
- **AND** the Mongo `canvas_content` is unchanged

#### Scenario: `GUIDE.md` and `index.md` remain writable

- **WHEN** the materializer writes `{user_root}/todos/GUIDE.md` and `{user_root}/todos/index.md`
- **THEN** those files are mode `0644` (the materializer is allowed to rewrite them in place)

### Requirement: Hand-authored `GUIDE.md` is materialized once per user under `/workspace/todos/`

The system SHALL write a `GUIDE.md` file at `{user_root}/todos/GUIDE.md` whose contents are sourced from the hand-authored constant `TODOS_GUIDE_MD` in `apps/api/app/agents/workspace/system_docs.py`. The file SHALL be rewritten only when its current on-disk content does not match the constant byte-for-byte.

#### Scenario: GUIDE.md is created on first sync

- **WHEN** a user's first sync runs after deploy
- **THEN** `{user_root}/todos/GUIDE.md` exists with contents equal to `TODOS_GUIDE_MD`

#### Scenario: GUIDE.md is rewritten when the constant changes

- **WHEN** a deploy ships a new `TODOS_GUIDE_MD` value
- **AND** any subsequent sync runs
- **THEN** `{user_root}/todos/GUIDE.md` is overwritten with the new value

#### Scenario: GUIDE.md is not rewritten when unchanged

- **WHEN** the on-disk `GUIDE.md` already matches `TODOS_GUIDE_MD`
- **AND** any sync runs
- **THEN** the materializer SHALL NOT call `write_text` on `GUIDE.md`

### Requirement: `index.md` summarises active todos

The system SHALL write a `{user_root}/todos/index.md` file containing one line per active todo, sorted by `updated_at` descending. Each line SHALL include enough information for an agent to scan and pick the relevant todo without opening individual `meta.json` files (at minimum: todo id, status indicator, title, and last-updated timestamp).

#### Scenario: Index lists every active folder

- **WHEN** a sync completes for a user with N active todos
- **THEN** `index.md` contains exactly N data lines (excluding any header)
- **AND** every `{todo_id}` referenced in `index.md` corresponds to an existing folder under `todos/`

#### Scenario: Index updates when a canvas is appended

- **WHEN** a canvas append commits and triggers a sync
- **THEN** the affected todo's line in `index.md` is moved to the top (its `updated_at` is now the most recent)

### Requirement: Steady-state syncs perform zero filesystem writes

The system SHALL maintain a per-user marker file at `{user_root}/.gaia/todos.v` containing the sha256 of the sorted `{todo_id}:{per_doc_signature}` pairs, and a per-todo marker at `{user_root}/.gaia/todos/{todo_id}.v` containing the sha256 of the projected body. When the computed catalog signature matches the marker, the sync SHALL return without writing any file under `todos/`. When a per-todo signature matches its marker, that todo's folder SHALL NOT be rewritten.

#### Scenario: Bootstrap with no changes is a no-op

- **WHEN** `bootstrap_user_session` runs for a user whose todos have not changed since the last sync
- **THEN** no file under `{user_root}/todos/` is written
- **AND** no file under `{user_root}/.gaia/todos/` is written
- **AND** `{user_root}/.gaia/todos.v` is not rewritten

#### Scenario: Single canvas edit only rewrites one folder

- **WHEN** exactly one todo's `canvas_content` changes between syncs
- **THEN** only that todo's `canvas.md` is rewritten (plus `meta.json` because `updated_at` changed)
- **AND** every other todo folder is left untouched at the filesystem level
- **AND** `index.md`, `todos.v`, and the changed todo's `.v` marker ARE rewritten

### Requirement: Mutations to tracked todos schedule a projection sync

The system SHALL invoke a fire-and-forget `sync_user_todos(user_id)` at the end of every code path that commits a change to a tracked todo's Mongo document. Two direct hooks suffice because the rest cascade through these: (a) `create_tracked_todo` and `complete_tracked_todo` in `tracked_todo_service.py` (note: `archive_tracked_todo` already calls `complete_tracked_todo`, so it cascades); (b) `write_canvas` and `write_log` in `todo_canvas_storage.py` (note: `append_canvas` calls `write_canvas`, `append_log` calls `write_log`, so they cascade). The result is exactly one `schedule_sync` per Mongo `update_one` — no double-firing.

#### Scenario: Canvas append triggers a sync

- **WHEN** `append_canvas(todo_id, user_id, "new line")` commits to Mongo
- **THEN** `schedule_sync(user_id)` is called before the function returns

#### Scenario: Tool response does not block on sync

- **WHEN** the agent calls `update_tracked_todo_canvas` and the tool returns a response
- **THEN** the tool response is NOT delayed by the projection rewrite (sync runs in the background)

#### Scenario: Background sync task is retained

- **WHEN** `schedule_sync(user_id)` creates a task
- **THEN** the task is stored in a module-level `set[asyncio.Task]` and removed via `add_done_callback` so it cannot be garbage-collected mid-flight

### Requirement: Bootstrap-time sync repairs drift

The system SHALL call `sync_user_todos(user_id)` as part of `bootstrap_user_session`, after the existing skills materialization, so any drift between Mongo and the projection (caused by a missed fire-and-forget, a process restart, or a schema migration) self-heals on the next chat-turn entry.

#### Scenario: Crash between Mongo write and FS write self-heals next turn

- **WHEN** the process crashes after Mongo commits a canvas update but before the post-write sync writes the file
- **AND** the user starts a new chat turn
- **THEN** `bootstrap_user_session` runs `sync_user_todos`
- **AND** `cat {user_root}/todos/{todo_id}/canvas.md` returns the post-crash Mongo content

#### Scenario: Bootstrap sync runs after skills materialization

- **WHEN** `bootstrap_user_session` executes
- **THEN** `materialize_skills` (or the existing `_materialize_if_stale` path) completes before `sync_user_todos` is invoked

### Requirement: Materializer soft-fails when JuiceFS is unmounted

When the JuiceFS host mount is unavailable (`_is_mounted() == False`, e.g. native `mise dev`), `sync_user_todos` SHALL return immediately without raising, log nothing as an error, and SHALL NOT cause the caller (tool, bootstrap, or otherwise) to fail.

#### Scenario: Native dev mode does not raise

- **WHEN** the API runs without a JuiceFS mount and `schedule_sync(user_id)` is invoked from a tracked-todo write path
- **THEN** the call returns successfully
- **AND** no exception propagates to the tool caller
- **AND** the Mongo write is not rolled back

#### Scenario: Bootstrap still succeeds without JuiceFS

- **WHEN** `bootstrap_user_session` runs natively (no mount)
- **THEN** the todos sync is skipped silently
- **AND** the rest of the bootstrap (session dirs, skill catalog) follows its existing native-mode behavior

