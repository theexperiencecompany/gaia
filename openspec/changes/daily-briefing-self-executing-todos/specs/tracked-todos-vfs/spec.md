## MODIFIED Requirements

### Requirement: Active tracked todos appear as folders under `/workspace/todos/`

The system SHALL materialize one folder per active GAIA-assigned todo at `{user_root}/todos/{todo_id}/` on the JuiceFS host mount, visible inside the executor sandbox as `/workspace/todos/{todo_id}/`. A todo is "active" when `assignee == "gaia"` AND either `completed` is false/missing OR `completed_at >= now - 30 days`. During the one-release migration window the projector SHALL dual-read: a todo whose `labels` still contains `gaia-tracked` is treated as `assignee == "gaia"`. Projected file contents are unchanged by this modification.

#### Scenario: Assignee-based todo is materialized
- **WHEN** a user has a todo with `assignee: "gaia"` and `completed: false`
- **THEN** its folder is materialized under `/workspace/todos/{todo_id}/`

#### Scenario: Legacy-labeled todo still projects during migration window
- **WHEN** an unmigrated todo carries `labels: ["gaia-tracked"]` without an `assignee` field
- **THEN** it is projected identically until the backfill completes
