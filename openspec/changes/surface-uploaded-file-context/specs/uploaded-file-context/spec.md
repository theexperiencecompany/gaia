## ADDED Requirements

### Requirement: Full file summary written to a VFS file

The system SHALL write each uploaded file's full summary (`description` + `page_wise_summary`) to a markdown file in the session VFS, as a sibling next to the upload (`user-uploaded/<safe_filename>.summary.md`). The write MUST be a pure projection of the summary already stored in MongoDB (no recompute) and MUST reuse the same VFS write primitive used to mirror the upload. The write MUST be best-effort and mount-gated: when the sandbox mount is unavailable, it no-ops without failing the upload.

#### Scenario: Summary file created next to upload

- **WHEN** a user uploads a file in a conversation with the sandbox mounted
- **THEN** a markdown summary file is written beside the original at `user-uploaded/<file>.summary.md`
- **AND** its content is the stored `description` plus the rendered per-page summary, not a recomputed one

#### Scenario: Summary file write is best-effort

- **WHEN** the sandbox mount is unavailable (native dev)
- **THEN** the summary file is not written
- **AND** the upload itself still succeeds

### Requirement: File path, summary path, and truncated summary in agent context

The system SHALL surface, for each uploaded file referenced in a turn, the file's workspace path, the summary-file path, and the file's `description` truncated to a maximum character budget with a pointer to read the full summary file. These MUST be carried on the agent-facing `FileData` and injected at the human-message file-listing point, never in the cached static system prefix. When `description` is absent the line MUST degrade to path-only; when the summary file is absent the read-more pointer MUST be omitted.

#### Scenario: Image upload is described in context with paths

- **WHEN** a user uploads an image and sends a message referencing it
- **THEN** the comms agent's context includes the file path, the summary-file path, and a truncated summary of the image
- **AND** the agent can answer "what is this image?" without invoking the executor or any tool

#### Scenario: Truncated summary respects the max-character budget

- **WHEN** a file's `description` exceeds the configured inline maximum
- **THEN** the inline summary is truncated to that maximum
- **AND** a pointer to the full summary file is included

#### Scenario: Missing summary degrades gracefully

- **WHEN** an uploaded file has no stored `description`
- **THEN** the context line falls back to path-only
- **AND** message assembly does not error

#### Scenario: Summary stays out of the cached prefix

- **WHEN** file summaries are injected into context
- **THEN** they appear in the per-turn human/dynamic message region, not the byte-identical static system message
- **AND** the prompt-cache prefix remains stable across users

### Requirement: Inline summary works without the sandbox mount

The system SHALL produce the truncated inline summary from MongoDB-backed metadata alone, so a user gets file understanding in context even when JuiceFS is not mounted. Only the summary-file path and read-more pointer depend on the mount.

#### Scenario: Inline summary available in native dev

- **WHEN** the API runs without a JuiceFS mount and a file with a stored summary is referenced
- **THEN** the truncated summary is still injected into the agent context
- **AND** the read-more pointer to the summary file is omitted because the file was not written

### Requirement: Full content stays out of context

The system SHALL keep full document text and page-wise summaries out of the agent context. Only the truncated inline summary belongs in context; full content MUST be reachable on demand via the summary file, via `read`/`bash` on the workspace path, or via the uploaded-file search tool.

#### Scenario: Large document does not flood context

- **WHEN** a user uploads a multi-page document
- **THEN** only its truncated summary is injected into context
- **AND** the full per-page content is reachable via the summary file or the search tool, not via context

### Requirement: Renamed, scoped search tool for uploaded files

The system SHALL provide a semantic search tool that operates ONLY over files the user uploaded, named to make that scope unambiguous (replacing the generic `query_file`). Its documentation MUST state that it searches only uploaded files, when to use it (find which uploaded file mentions a topic, or pull passages across uploads), and when not to (for a single known file, read its path or summary file directly). All references to the old name — function, registry entry, label, docstring, and prompts — MUST be updated, and the tool-retrieval index MUST be re-embedded so the renamed tool is discoverable.

#### Scenario: Cross-file semantic lookup over uploads

- **WHEN** a user asks which uploaded file mentions a given topic
- **THEN** the search tool performs semantic search over the user's uploaded files
- **AND** returns the matching files and relevant passages

#### Scenario: Tool scope is unambiguous to the model

- **WHEN** the model reads the search tool's name and docstring
- **THEN** it is clear the tool searches only user-uploaded files
- **AND** the tool is not presented as a generic file or web search

#### Scenario: No dangling references to the old name

- **WHEN** the rename is applied
- **THEN** no registry entry, label, docstring, or prompt references the old `query_file` name
- **AND** the renamed tool is discoverable via tool retrieval

### Requirement: Single coherent contract for working with uploaded files

The system SHALL expose one documented contract for uploaded files, removing the current contradiction where the search tool is registered while the file-listing guidance instructs the agent to ignore it. The file-listing guidance and the tool docstring MUST consistently describe: truncated summary in context, full summary in the `<file>.summary.md` sibling file, raw bytes via `read`/`bash` on the path, and cross-file semantic search via the renamed tool.

#### Scenario: Guidance no longer contradicts the registry

- **WHEN** the agent reads the file-listing guidance and the search tool's docstring
- **THEN** neither instructs the agent to ignore an available tool
- **AND** each names when to use which access path
