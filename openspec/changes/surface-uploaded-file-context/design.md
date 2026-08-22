## Context

The upload pipeline already does the expensive work. `upload_file_service` (`app/services/file_service.py:44`) calls `generate_file_summary` (`app/utils/file_utils.py:234`), which runs the vision model on images (`process_image`, base64 → `image_url` content block) and LlamaParse + LLM on documents. The result is persisted in two shapes:

- `description` — a short summary string (the "what is this") in MongoDB `files_collection`.
- `page_wise_summary` — full per-page content/summaries in MongoDB, and per-page embeddings in ChromaDB.

What's missing is **delivery to the agent**:

- The user-facing **comms agent** only receives file *paths*. `format_files_list` (`app/helpers/message_helpers.py:720`) emits `- name → /workspace/sessions/<conv>/user-uploaded/<file>` and points at the workspace GUIDE. No summary.
- The comms agent has only three tools (`call_executor`, `add_memory`, `search_memory`) — it cannot call `query_file`.
- `query_file` (`app/agents/tools/file_tools.py`) *is* registered (`registry.py:259`) in the executor's ChromaDB-retrievable pool, but `format_files_list`'s own prose tells the agent to ignore it ("no `query_files` tool indirection"). The name is also generic — nothing signals it searches only user-uploaded files, inviting the model to misuse it.
- Reading an image path via `read`/`bash` yields raw bytes — there is no agent-time vision; the only image understanding is the upload-time `description`/`page_wise_summary`, which never reaches the agent.

The `FileData` object the agent layer receives (`app/models/message_models.py:18`) carries `fileId/url/filename/type` but **not** `description`, so the summary isn't even reachable where the message is built.

Constraints:
- Prompt-cache prefix stability — the static system message is byte-identical across users by design (`messages.py:73`). Per-file summary must go in the dynamic/human portion, never the cached prefix.
- JuiceFS is unavailable in native dev (`mise dev`); anything gated on the sandbox mount won't run there. The inline summary must depend only on MongoDB; the summary *file* is mount-gated exactly like the upload itself.
- Context budget — `page_wise_summary` for a 50-page PDF must not be injected. Only a truncated inline summary belongs in context; the full summary lives in a file the agent reads on demand.

## Goals / Non-Goals

**Goals:**
- The comms agent knows what every uploaded file is (especially images) the moment the user references it, with no extra LLM call or tool round-trip.
- The full summary is available to read on demand from a file in the VFS, surfaced by path next to the upload.
- One coherent, documented contract for working with uploaded files, with a clearly-scoped, correctly-named search tool that the model cannot confuse with generic file/web search.
- The inline summary works in native dev (no JuiceFS dependency).

**Non-Goals:**
- Re-architecting upload storage or the JuiceFS/Cloudinary/Mongo/Chroma split. Summaries are already generated and stored; this surfaces and projects them.
- Injecting full document text or page-wise summaries into context.
- A separate agent-time vision tool. The upload-time summary (vision for images) written to the summary file is the canonical image understanding; a dedicated `describe_image` tool is **deferred** unless the upload summary proves insufficient in practice (see Open Questions).
- Frontend changes.

## Decisions

### Decision 1: Full summary → a VFS sidecar file, surfaced by path

At upload (and at `seed_uploads_for_new_conversation` time), render the stored summary to a markdown file co-located with the upload and write it via `write_session_file` — the same primitive that mirrors the upload itself.

- **Location**: a sibling next to the original, `user-uploaded/<safe_filename>.summary.md`. Workspace view: `/workspace/sessions/<conv>/user-uploaded/<file>.summary.md`. Placing it right beside the file makes the pairing obvious — an agent listing `user-uploaded/` sees each upload and its summary together.
- **Content**: a header with filename/type, the short `description`, then the rendered `page_wise_summary` (per-page content + summaries). This is a pure projection of MongoDB data — no recompute.
- **Write path**: factor a `_persist_summary_to_sandbox` sibling to `_persist_upload_to_sandbox`. Best-effort and mount-gated: on `JuiceFSUnavailable` (native dev) it no-ops, exactly like the upload mirror — the inline summary (Decision 2) still works.

The `.summary.md` suffix on the original filename keeps the pairing self-evident and avoids a hidden subdir the agent has to know about; the workspace GUIDE notes that `*.summary.md` files are generated companions, not user uploads.

### Decision 2: Truncated inline summary + read-more pointer in context

`format_files_list` emits, per file:

```
- <filename>
    path: `/workspace/sessions/<conv>/user-uploaded/<file>`
    summary: <description truncated to MAX chars>… (full summary: `…/user-uploaded/<file>.summary.md`)
```

- The inline text is `description` truncated to a max-character constant (`UPLOADED_FILE_INLINE_SUMMARY_MAX_CHARS`, in `app/constants/`). `description` is already short (1–2 sentences) and usually fits; the cap is a defensive bound, not the primary trim.
- The read-more pointer names the summary-file path so the agent can read the full text on demand.
- `format_files_list` stays sync and pure-formatting — it receives `description` and the summary path on the `FileData`, it does not do I/O.

### Decision 3: Thread `description` (and summary path) through `FileData` to the context layer

Add `description: str | None` and `summary_path: str | None` to the agent-facing `FileData` (`message_models.py`), populated where the chat message is assembled (`messages.py`/`agent.py`). Prefer the request payload (the frontend already receives `description` and `sandbox_path` from the upload response, `file_service.py:144`); fall back to a single batched `files_collection` lookup keyed on the turn's `fileIds` only if the payload lacks them (older clients). The lookup, if needed, lives in the async message-assembly layer — never inside the sync `format_files_list`.

### Decision 4: Bring back `query_file`, renamed and scoped, as the cross-file search tool

Keep the tool; fix its name and docs so the model uses it correctly.

- **Rename** `query_file` → `search_uploaded_files` (semantic search over the user's uploaded files in this conversation). Update the function, registry entry (`registry.py:259`), label (`tool_labels.py:112`), docstring (`file_tool_docs.py` `QUERY_FILE`), and the workflow-prompt reference (`workflow_prompts.py:263`).
- **Docstring states scope and usage explicitly**: searches ONLY files the user uploaded; use it to find *which* uploaded file mentions a topic, or to pull relevant passages across several uploads; for a single known file, read its path or its `<file>.summary.md` directly instead. This is the "how to properly read it" guard against the model treating it as generic file/web search.
- Make it reachable: it stays in the executor's retrievable pool (where it already is), now correctly advertised. The comms agent answers simple "what is this" from the inline summary; deeper search routes through the executor as usual.

### Decision 5: One documented contract; remove the contradiction

Replace `format_files_list`'s "no `query_files` tool indirection" prose with the single contract, stated consistently across the file-listing text and the tool docstring:

- **What is this file?** → inline summary in context (Decision 2).
- **Full summary?** → read the `<file>.summary.md` sibling file (Decision 1).
- **Exact bytes / raw content?** → `read`/`bash` on the file path.
- **Which uploaded file mentions X / cross-file passages?** → `search_uploaded_files` (Decision 4).

## Risks / Trade-offs

- **Stale or missing `description`** (summarization failed, or file predates summarization) → inline line degrades to path-only; summary file is simply not written. Never error. Treat `description`/`summary_path` as optional throughout.
- **Summary file write fails / no mount (native dev)** → no-op, mirroring `_persist_upload_to_sandbox`; the inline summary from Mongo still surfaces. The read-more pointer is omitted when no summary file exists.
- **Context bloat from many attachments** → bounded: N files × (one path + one capped summary) is acceptable; full content is explicitly excluded. The max-char cap backstops a pathological `description`.
- **Prompt-cache disruption** → summaries are per-turn dynamic content; inject via the existing `format_files_list` append on the human message, never the static system prefix (`messages.py:73`).
- **Rename churn / dangling references** → grep every reference to `query_file` (registry, labels, docstrings, prompts, tool retrieval embeddings) and update all; the ChromaDB tool-retrieval index must be re-embedded so the new name/description is discoverable. Leaving the old embedding stale would make the tool unfindable.
- **`*.summary.md` companions appearing as uploads** → they sit in `user-uploaded/` beside the originals; ensure the agent isn't told to treat them as user content and that artifact/upload listings distinguish a generated `*.summary.md` from an actual upload.

## Migration Plan

1. Add `description` + `summary_path` (optional) to agent-facing `FileData`; thread through the chat request → `construct_langchain_messages`.
2. Add `_persist_summary_to_sandbox` and call it from `upload_file_service` and `seed_uploads_for_new_conversation` (best-effort, mount-gated).
3. Add the inline-summary max-char constant; update `format_files_list` to emit path + summary-path + truncated summary, and to carry the reconciled contract text.
4. Rename `query_file` → `search_uploaded_files` across function/registry/label/docstring/prompt; re-embed the tool-retrieval index.
5. No backfill: summaries already exist in Mongo for prior uploads; the summary file is regenerated on the next reference/upload, and missing ones degrade to inline-only.

Rollback: revert the `FileData`/`format_files_list`/tool-name changes and drop the summary-file write — the agent returns to path-only behavior with no data loss (summaries remain in Mongo/Chroma).

## Open Questions

- **Inline summary for all file types, or only images + documents?** Plain `.txt`/`.csv` are cheaply readable via `read`, so a summary adds less value — but a summary already exists for all types. Lean: all types, for consistency.
- **Does the frontend round-trip `description`/`sandbox_path` into the chat request `fileData`?** Determines whether Decision 3's Mongo fallback is needed in practice — verify against the `apps/web` upload flow before implementation.
- **Is the upload-time image summary detailed enough** (OCR, fine detail) that a separate agent-time `describe_image` vision tool is genuinely unnecessary? Defer the tool; revisit only if real "read the text on this image" cases fail against the summary file.
