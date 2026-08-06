## Why

When a user uploads a file — especially an image — GAIA cannot tell what it is. The upload pipeline already runs vision on every image and LlamaParse on every document, then stores a summary in MongoDB and ChromaDB. But the user-facing **comms agent** only ever receives the file's *path* (via `format_files_list`). It has no vision, no access to the pre-computed summary, and cannot call `query_file` (executor-only). So "what's in this image?" gets answered from nothing: reading the path returns raw bytes, and the summary that was already computed never reaches the agent.

This is a regression introduced by the workspace-v2 migration: surfacing files as filesystem paths replaced the old `query_file`-over-ChromaDB path, but filesystem reads cannot "see" an image, and the short summary that used to reach the agent was dropped.

## What Changes

- **Write each uploaded file's full summary to its own file in the session VFS, right next to the upload.** At upload (and at session-seed time), render the stored summary (`description` + `page_wise_summary`) to a markdown sibling beside the original, `user-uploaded/<file>.summary.md`. This is a projection of data already in MongoDB — no recompute.
- **Surface both paths plus a truncated inline summary into the comms agent's context.** Extend `format_files_list` so each attachment line carries: the file's workspace path, the summary-file path, and the `description` truncated to a max-character budget with a "read the full summary at `<summary-path>`" pointer. The agent knows *what* each attachment is immediately, and can read the full summary on demand without an LLM round-trip.
- **Bring back `query_file` as a real, usable tool — renamed to remove model confusion.** The tool only ever searches files the *user uploaded* (semantic search over ChromaDB), so rename it to make that scope explicit (e.g. `search_uploaded_files`) and write a docstring that states exactly when and how to use it. This stops the model from treating it as a generic file/web search.
- **Keep deep/large content behind the VFS and the renamed tool, not in context.** Only the truncated inline summary goes into context. Full per-page content lives in the summary file (read via `read`/`bash`) and in ChromaDB (semantic lookup via the renamed tool).
- **Resolve the `query_file` vs filesystem-path contradiction.** Today the registry exposes `query_file` while `format_files_list` tells the agent to ignore it. Establish one coherent, documented contract: truncated summary + paths in context, full summary in the sidecar file, semantic cross-file search via the renamed tool.
- The inline summary degrades gracefully when JuiceFS is unavailable (native dev): the truncated summary comes from MongoDB metadata, independent of the sandbox mount; only the summary *file* path is mount-gated, exactly like the upload path itself.

## Capabilities

### New Capabilities
- `uploaded-file-context`: How an uploaded file's content is made available to the agents — where the short summary lives (context), where full content lives (VFS + `query_file`), and how images become understandable to the agent (context summary + on-demand vision tool). Defines the contract across the comms agent, the executor, and the upload pipeline.

### Modified Capabilities
<!-- No existing spec covers file context; existing specs (fs-metrics-prometheus, tracked-todos-vfs) are unrelated. -->

## Impact

- **Summary file write**: `app/services/file_service.py` (`upload_file_service`, `_persist_upload_to_sandbox`, `seed_uploads_for_new_conversation`) — render the stored summary to a VFS sidecar via `write_session_file`, alongside the existing upload mirror. Best-effort, mount-gated like the upload itself.
- **Context assembly**: `app/helpers/message_helpers.py` (`format_files_list`), `app/agents/core/messages.py` (`construct_langchain_messages`) — emit file path + summary-file path + truncated inline summary.
- **Upload metadata flow**: `app/models/message_models.py` (`FileData`) and the chat request path must carry `description` (and the summary-file path) through to `format_files_list` (today it carries only `fileId`/`url`/`filename`/`type`). The summary already exists in MongoDB `files_collection`; it needs to reach the agent context layer.
- **Tool rename**: `app/agents/tools/file_tools.py` (`query_file` → e.g. `search_uploaded_files`), its docstring in `app/templates/docstrings/file_tool_docs.py` (`QUERY_FILE`), its registry entry (`app/agents/tools/core/registry.py:259`), and its label in `app/constants/tool_labels.py`. Also update the workflow-prompt reference (`app/agents/prompts/workflow_prompts.py:263`).
- **Tool/prompt reconciliation**: the renamed tool's docstring and the `format_files_list` guidance text — converge on one contract.
- **Constant**: a max-character budget for the inline summary, in `app/constants/`.
- **No new storage backend**: summaries are already generated and persisted at upload (`file_service.upload_file_service` → `generate_file_summary`). This change *surfaces* and *projects* existing data, not recomputes it.
- **Frontend**: none required for the core fix; the chat UI already uploads files and renders artifacts.
