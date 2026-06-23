## 1. Verify current data flow

- [ ] 1.1 Confirm whether the `apps/web` upload flow round-trips `description` and `sandbox_path` from the upload response into `MessageRequestWithHistory.fileData`; record the finding (decides whether the Mongo fallback in 3.3 is needed)
- [ ] 1.2 Confirm `files_collection` reliably holds `description` and `page_wise_summary` for uploaded files, keyed by `file_id`

## 2. Write the full summary to a VFS file

- [ ] 2.1 Add a renderer that turns `description` + `page_wise_summary` into markdown (header with filename/type, short description, per-page content/summaries)
- [ ] 2.2 Add `_persist_summary_to_sandbox` in `app/services/file_service.py` (sibling to `_persist_upload_to_sandbox`) that writes `user-uploaded/<safe_filename>.summary.md` beside the upload via `write_session_file`; best-effort, no-op on `JuiceFSUnavailable`
- [ ] 2.3 Call it from `upload_file_service` (when `conversation_id` is present) and from `seed_uploads_for_new_conversation`
- [ ] 2.4 Ensure generated `*.summary.md` companions are not surfaced as uploaded originals in artifact/upload listings, and note the convention in the workspace GUIDE

## 3. Thread paths + summary to the context layer

- [ ] 3.1 Add `description: str | None` and `summary_path: str | None` to the agent-facing `FileData` in `app/models/message_models.py`
- [ ] 3.2 Populate both on `FileData` from the request payload where the chat message is assembled (`app/agents/core/messages.py` / `app/agents/core/agent.py`)
- [ ] 3.3 If (and only if) 1.1 shows the payload lacks them, add one batched `files_collection` lookup keyed on the turn's `fileIds` in the async message-assembly layer (never inside the sync `format_files_list`)

## 4. Inject path + summary-path + truncated summary into context

- [ ] 4.1 Add `UPLOADED_FILE_INLINE_SUMMARY_MAX_CHARS` to `app/constants/`
- [ ] 4.2 Update `format_files_list` in `app/helpers/message_helpers.py` to emit, per file: the workspace path, the summary-file path, and `description` truncated to the max with a "full summary: `<summary-path>`" pointer; degrade to path-only when `description` absent and omit the pointer when no summary file
- [ ] 4.3 Verify injection stays in the per-turn human/dynamic region, not the static cached system prefix (`messages.py:73`)
- [ ] 4.4 Replace the contradictory "no `query_files` tool indirection" guidance with the reconciled single-contract wording

## 5. Rename and revive the search tool

- [ ] 5.1 Rename `query_file` → `search_uploaded_files` in `app/agents/tools/file_tools.py` (function + internal references)
- [ ] 5.2 Update the registry entry (`app/agents/tools/core/registry.py:259`) and the label (`app/constants/tool_labels.py:112`)
- [ ] 5.3 Rewrite the docstring (`app/templates/docstrings/file_tool_docs.py` `QUERY_FILE`) to state scope (only user-uploaded files), when to use it, and when to read a path/summary file instead
- [ ] 5.4 Update the workflow-prompt reference (`app/agents/prompts/workflow_prompts.py:263`) and grep for any other `query_file` references
- [ ] 5.5 Re-embed the ChromaDB tool-retrieval index so the renamed tool + new description are discoverable

## 6. Verification

- [ ] 6.1 Run `nx type-check api` and `nx lint api` — clean
- [ ] 6.2 Manual (dockered `mise dev:vm`): upload an image, ask "what's in this image?", confirm the comms agent answers from the inline summary with no executor round-trip, and that the context shows file path + summary path
- [ ] 6.3 Manual: confirm the `<file>.summary.md` file exists beside the upload and the agent can `read` it for the full summary
- [ ] 6.4 Manual: ask a cross-file question ("which file mentions X"), confirm the executor invokes `search_uploaded_files` and it returns matching uploads
- [ ] 6.5 Manual (native `mise dev`, no JuiceFS): confirm the truncated inline summary still appears and the read-more pointer is omitted
- [ ] 6.6 Manual: upload a multi-page PDF, confirm only the truncated summary is in context and full content is reachable via the summary file / search tool
