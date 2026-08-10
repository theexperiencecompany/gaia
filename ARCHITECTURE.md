# GAIA Architecture — Agent System

Canonical map of GAIA's agent system. Referenced from `CLAUDE.md` and `AGENTS.md` so the architecture is explained once, in one place, and never has to be re-derived per session.

If you are an agent and you are about to touch any of the components below, **read the relevant section first** before grepping blindly. The file paths listed here are the authoritative entry points.

---

## 1. Bird's-Eye View

GAIA's agent runtime is a **three-tier system**:

```
┌──────────────────────────────────────────────────────────────┐
│  Comms Agent  (user-facing, conversational)                  │
│  - Talks to the user                                          │
│  - Delegates ALL work via call_executor                       │
│  - Small tool surface: call_executor, cancel_executor, memory │
└─────────────────────┬────────────────────────────────────────┘
                      │  call_executor(task)  → background asyncio task
                      ▼
┌──────────────────────────────────────────────────────────────┐
│  Executor Agent  (worker tier)                               │
│  - Full tool registry: bash, read, retrieve_tools, todos,     │
│    tracked_todos, memory, deep_research, ...                  │
│  - Handoff to integration subagents (blocking OR background)  │
│  - Tracked-todo canvas, plan_tasks, update_tasks              │
└─────────────────────┬────────────────────────────────────────┘
                      │  handoff(subagent_id, task, background=...)
                      ▼
┌──────────────────────────────────────────────────────────────┐
│  Subagents  (per-integration specialists)                    │
│  - One graph per provider: gmail, notion, github, calendar,  │
│    slack, linear, sheets, docs, todoist, twitter, ...         │
│  - Basic tools: bash, read, retrieve_tools + integration tools│
│  - finish_task signal + memory node end-hook                 │
└──────────────────────────────────────────────────────────────┘
```

The whole thing is reachable from four surfaces: the **web/mobile UI**, the **voice agent** (LiveKit worker), the **bots** (Telegram / WhatsApp / Discord / Slack), and **workflows** (scheduled / triggered runs).

---

## 2. Comms Agent

The **only** agent the user talks to. Owns the conversation thread, narrates progress, and never performs real work itself — every "do something" goes through `call_executor`.

### Where it lives

- `apps/api/app/agents/core/agent.py` — entry points `call_agent()` (live SSE stream) and `call_agent_silent()` (background/workflow).
- `apps/api/app/agents/core/graph_builder/build_graph.py` — `build_comms_graph()` / `build_comms_agent()`. Comms is built with `disable_retrieve_tools=True` and end-graph hooks `[follow_up_actions_node, memory_node]`.
- `apps/api/app/agents/core/state.py` — `State` Pydantic model: `query`, `intent`, `messages`, `memory_user_id`, `memories`, `active_todo_id`, `execution_mode` (interactive/background).
- `apps/api/app/agents/core/messages.py` — `construct_langchain_messages` builds the message array with per-turn context (calendar, reply-to, file refs, timezone).
- `apps/api/app/agents/core/graph_manager.py` — `GraphManager.get_graph(name)` resolves graphs via lazy providers.

### Comms tool surface (deliberately tiny)

- `call_executor` — the **only** way to do work. Non-blocking; returns `Task accepted (task_id: ...)` immediately.
- `cancel_executor` — cancel the most recent background run.
- Memory tools — `add_memory`, `search_memory`, `forget_memory`, `read_memory_document` (see §8).

That's it. No `bash`. No `read`. No per-integration tools. The comms agent is a router + narrator, not a worker.

---

## 3. Executor Agent (handoff target)

The worker tier. Has access to **everything** that does work.

### Where it lives

- `apps/api/app/agents/core/graph_builder/build_graph.py` — `build_executor_graph()` / `build_executor_agent()`. Built with retry policy `EXECUTOR_RETRY_POLICY`.
- `apps/api/app/agents/tools/executor_tool.py` — `call_executor` and `cancel_executor` LangChain tools.
- `apps/api/app/agents/core/subagents/subagent_runner.py` — `prepare_executor_execution()` and `execute_subagent_stream()`. Each executor call gets a **fresh ephemeral thread** (`executor_{thread_id}_{uuid}`) while VFS session stays pinned to the parent conversation.

### Initial tool IDs (comms → executor handoff)

`handoff`, `plan_tasks`, `update_tasks`, `read`, `bash`, `deep_research`, `wait_for_subagents`, `read_manual`, `create_tracked_todo`, `update_tracked_todo`, `update_tracked_todo_canvas`, `complete_tracked_todo`, `search_todo_context`, `list_tracked_todos`.

### Handoff lifecycle (background, async)

1. Comms invokes `call_executor` → `executor_tool.py`.
2. `executor_tool.py` acquires Redis `executor:busy` lock (or enqueues if busy) and fires `asyncio.create_task(run_executor_background(...))`. Returns immediately.
3. `apps/api/app/agents/core/background/executor_runner.py` — `run_executor_background()` runs the executor graph via `_execute_executor` → `execute_subagent_stream`, then `_finalize_executor_run` signals done → `deliver_result` / `persist_cancelled_run` → close stream → release queue lock.
4. Inherits `langfuse_trace_id` from the comms call for unified tracing.

### Supporting background modules

- `apps/api/app/agents/core/background/executor_capture.py` — per-stream collector for executor tool events so background/workflow runs render identically to live chat.
- `apps/api/app/agents/core/background/executor_queue.py` — per-conversation FIFO queue with `busy` Redis lock. `pop_next_queued_run`, `reclaim_stranded_task`, `try_acquire_lock` (SET NX), `enqueue_task`.
- `apps/api/app/agents/core/background/result_delivery.py` — `deliver_result()` and `persist_cancelled_run()`. Finished text → narrate and deliver as new bot message; cancelled → persist `tool_data` only if `executor_owns_tool_data`.
- `apps/api/app/agents/core/background/session.py` — `StreamSession`, `ExecutorRun`, `RunKind` (LIVE/QUEUED). **One session per `stream_id`** replaces the old module-level dict soup.
- `apps/api/app/agents/core/background/redis_writer.py` — `make_redis_stream_writer(stream_id)` routes executor tool events back to the SSE consumer.
- `apps/api/app/agents/core/background/comms_narrator.py` — comm-side re-narration of the executor's terminal message.

### Pre-model hooks (shared by comms + executor + subagents)

- `apps/api/app/agents/core/nodes/filter_messages.py` — `filter_messages_node` trims history.
- `apps/api/app/agents/core/nodes/manage_system_prompts.py` — `manage_system_prompts_node` collapses repeat system messages for cache-prefix stability.
- `apps/api/app/agents/core/nodes/memory_node.py` — `memory_node` end-graph hook on every subagent + comms turn for passive durable-memory learning.
- `apps/api/app/agents/core/nodes/follow_up_actions_node.py` — **comms-only** end hook for proactive suggestions.

### Helper layer

- `apps/api/app/helpers/agent_helpers.py` — `build_agent_config`, `build_initial_state`, `execute_graph_streaming`, `execute_graph_silent`.
- `apps/api/app/core/lazy_loader.py` — `lazy_provider` / `providers.aget()` for on-demand graph creation.
- `apps/api/app/core/stream_manager.py` — Redis-backed SSE stream + cancel signaling.

---

## 4. Subagents (integration specialists)

Every integration is a `CompiledStateGraph` of its own. The executor hands off to the matching subagent via the `handoff` tool.

### Core subagent files

- `apps/api/app/agents/core/subagents/__init__.py`
- `apps/api/app/agents/core/subagents/registry.py` — `all_subagents()` and `get_subagent_by_id()`. **Single source of truth** that combines OAuth-derived subagents + builtins. Process-lifetime `@cache`'d.
- `apps/api/app/agents/core/subagents/builtin_subagents.py` — `BUILTIN_SUBAGENTS` (currently `docgen`, `gaia_knowledge_guide`). Excluded from the marketplace.
- `apps/api/app/agents/core/subagents/base_subagent.py` — `SubAgentFactory.create_provider_subagent()`. Wires the per-integration graph: scoped tool dict, `SubagentMiddleware`, todo tools, MCP/Composio tools, end-hook `[memory_node]`, checkpointer, and the three pre-model hooks.
- `apps/api/app/agents/core/subagents/provider_subagents.py` — `create_subagent()` (non-auth MCP) and `create_subagent_for_user()` (per-user auth MCP; rebuilt on every handoff, no memoization). `register_subagent_providers()` registers lazy loaders.
- `apps/api/app/agents/core/subagents/handoff_tools.py` — `@tool handoff(subagent_id, task, config, background=False)`. Resolves the subagent via `_resolve_subagent()`, builds a `SubagentExecutionContext`, then runs blocking (`_run_blocking_handoff`) or fires `run_subagent_background()`. Includes `_get_subagent_by_id` (Redis cached at `SUBAGENT_CACHE_PREFIX`), `_sanitize_task_user_reference` (replaces Gaia display name with service username), and `index_custom_mcp_as_subagent` (ChromaDB indexing for semantic search). Also exports `check_integration_connection()`.
- `apps/api/app/agents/core/subagents/subagent_runner.py` — `SubagentExecutionContext`, `build_initial_messages` (builds `[static_system, dynamic_context, current_time, human_task]` triplet for cache stability), `execute_subagent_stream` (handles `messages`/`custom`/`updates` events; emits `subagent_start`/`subagent_end` lifecycle), `prepare_executor_execution` (builds executor context with `DIRECT EXECUTION HINT`).
- `apps/api/app/agents/core/subagents/subagent_helpers.py` — `create_subagent_system_message` (provider-specific prompt + integration instructions), `create_agent_context_message` (dynamic context block: user_name, memories, skills, integration metadata).

### OAuth integration definitions (source of subagent configs)

- `apps/api/app/config/oauth_config.py` — `OAUTH_INTEGRATIONS: list[OAuthIntegration]`. Each entry has `subagent_config=SubAgentConfig(has_subagent, agent_name, tool_space, handoff_tool_name, domain, capabilities, use_cases, system_prompt, use_direct_tools, disable_retrieve_tools, auto_bind_tools, include_finish_task)`.
- `apps/api/app/config/oauth_content.py` — per-integration UI content (icons, descriptions, setup screens).
- `apps/api/app/models/oauth_models.py` — `OAuthIntegration` Pydantic model.
- `apps/api/app/models/mcp_config.py` — `SubAgentConfig`, `MCPConfig`, `ComposioConfig`, `OAuthScope`, `ProviderMetadataConfig`, `ToolMetadataConfig`, `VariableExtraction`.
- `apps/api/app/models/subagent_models.py` — `Subagent` canonical model.

### Example subagent entry points in `oauth_config.py`

- **Gmail** — line 433, `tool_space="gmail"`, `agent_name="gmail_agent"`, `auto_bind_tools=[GMAIL_CUSTOM_GATHER_CONTEXT, GMAIL_FETCH_EMAILS, GMAIL_CREATE_EMAIL_DRAFT, ...]`, `managed_by="composio"`, `toolkit="GMAIL"`.
- **Notion** — line 522, `tool_space="notion"`.
- **GitHub** — line 796, `tool_space="github"`.
- **Google Calendar** — `composio`, `toolkit="GOOGLECALENDAR"`.
- **Slack** — line 1129, `toolkit="SLACK"`.

### Tools per subagent

- **Composio subagents** — `tool_registry.register_provider_tools(toolkit_name, space_name, specific_tools)` in `provider_subagents.py`. User OAuth token attached server-side via `@composio.tools.custom_tool`.
- **MCP subagents (auth-required)** — live tools read from `MCPClient` (source of truth), not copied into a registry. `get_mcp_client(user_id)` in `apps/api/app/services/mcp/mcp_client.py`.
- **Custom MCP subagents** — `_create_custom_mcp_subagent` in `provider_subagents.py` reads from `integrations_collection` in MongoDB. If `1 <= tool_count <= 10`, sets `use_direct_tools=True, disable_retrieve_tools=True` for low latency.
- **Always-on tools for every subagent** (in `base_subagent.py::_build_scoped_tool_dict`): `search_memory`, `read`, `bash`, `web_search_tool`, `fetch_webpages`, `deep_research`, `update_integration_instructions`, and optionally `finish_task`.

### Subagent middleware

- `apps/api/app/agents/middleware/subagent.py` — `SubagentMiddleware` allows a subagent to spawn its **own** child subagents (nested). The subagent's tool dict is the **full** registry, not the scoped one, so children can pick up `read`, `bash`, `web_search`, etc.
- `apps/api/app/agents/middleware/{__init__,factory,executor,runtime_adapter,accounting,compaction,summarization}.py` — token accounting, conversation compaction, summarization, runtime config.
- `apps/api/app/agents/llm/retry_policies.py` — `SUBAGENT_RETRY_POLICY`, `COMMS_RETRY_POLICY`, `EXECUTOR_RETRY_POLICY`.

### Per-integration tool files (Composio-backed)

- `apps/api/app/agents/tools/integrations/` — 23 files, one per provider. Each uses `@composio.tools.custom_tool`. Notable entries: `gmail_tool.py`, `calendar_tool.py`, `github_tool.py`, `slack_tool.py`, `notion_tool.py`, `linear_tool.py`, `linkedin_tool.py`, `airtable_tool.py`, `asana_tool.py`, `clickup_tool.py`, `google_docs_tool.py`, `google_maps_tool.py`, `google_meet_tool.py`, `google_sheets_tool.py`, `google_tasks_tool.py`, `hubspot_tool.py`, `instagram_tool.py`, `microsoft_teams_tool.py`, `reddit_tool.py`, `todoist_tool.py`, `trello_tool.py`, `twitter_tool.py`, `urgency_tool.py`.
- `apps/api/app/services/composio/composio_service.py` — `get_composio_service()`.
- `apps/api/app/services/composio/proxy_client.py` — `proxy_request_sync` (Composio custom-tool proxy).

---

## 5. Bots (Telegram, WhatsApp, Discord, Slack)

All four bots live in `apps/bots/`, share a unified command system in `libs/shared/ts/`, and use the **adapter pattern** — each platform implements `BaseBotAdapter`.

### Per-bot source (TypeScript, bundled with `tsup`)

- `apps/bots/telegram/` — `src/index.ts`, `src/adapter.ts` (grammY), `src/set-commands.ts`. Long polling; private DMs + group @mentions; `TELEGRAM_PHOTO_MAX_BYTES = 10MB`, `TELEGRAM_CAPTION_MAX_CHARS = 1024`.
- `apps/bots/discord/` — `src/index.ts`, `src/adapter.ts` (discord.js), `src/deploy-commands.ts`. Slash-command bot.
- `apps/bots/slack/` — `src/index.ts`, `src/adapter.ts` (Slack Bolt, Socket Mode).
- `apps/bots/whatsapp/` — `src/index.ts`, `src/adapter.ts`, `src/webhook.ts` (Kapso signature verification, media extraction), `src/webhook.types.ts`, `src/constants.ts`. Webhook-driven via Kapso.
- `apps/bots/` — root `package.json`, `project.json`, `CLAUDE.md`, `Dockerfile`, `tsconfig.test.json`, `vitest.config.ts`, `__tests__/`.

### Shared bot framework

- `libs/shared/ts/src/bots/adapter/base.ts` — `BaseBotAdapter` abstract class. Lifecycle: `constructor` → `boot(commands)` → `initialize` → `registerCommands` → `registerEvents` → `start` → `stop`. Exposes `dispatchCommand`, `buildContext`, `handleStreamingChat`.
- `libs/shared/ts/src/bots/adapter/base-server.ts` — `BotServer` (webhook server for WhatsApp).
- `libs/shared/ts/src/bots/adapter/rich-renderer.ts` — `renderForPlatform` (platform-specific Markdown rendering: Slack/Telegram markdown, Discord embeds).
- `libs/shared/ts/src/bots/commands/` — unified `BotCommand` implementations: `gaia.ts` (main `/gaia` chat), `help.ts`, `settings.ts`, `new.ts` (new conversation), `stop.ts` (cancel executor), `status.ts`, `workflow.ts` (`/workflow create/list/run`), `todo.ts`, `conversations.ts`, `auth.ts`, `unlink.ts`. Each command receives a `CommandContext` and the `GaiaClient`.
- `libs/shared/ts/src/bots/consumer/outbound-consumer.ts` — outbound message delivery (RabbitMQ topology for cross-process fan-out).
- `libs/shared/ts/src/bots/consumer/envelope.ts` — envelope types for cross-bot routing.
- `libs/shared/ts/src/bots/consumer/topology.ts` — RabbitMQ exchange/queue setup.
- `libs/shared/ts/src/bots/api/` — `GaiaClient` (HTTP client to the FastAPI backend).
- `libs/shared/ts/src/bots/config/secrets.ts`, `config/index.ts` — bot config + secret loading.
- `libs/shared/ts/src/bots/utils/` — `streaming.ts` (SSE), `media.ts` (universal media pipeline, `OUTBOUND_FILE_LIMITS`), `text.ts`, `formatters.ts`, `commands.ts`, `logger.ts`, `index.ts`.
- `libs/shared/ts/src/bots/types/index.ts` — `BotCommand`, `CommandContext`, `BotConfig`, `PlatformName`, `RichMessage`, `RichMessageTarget`, `SentMessage`, `BotFileData`, `IncomingMedia`, `MediaKind`, `OutboundAttachment`, `STREAMING_DEFAULTS`.
- `libs/shared/ts/src/bots/index.ts` — public exports (`allCommands`, etc.).

### How a bot message reaches the agent

Bot receives message → adapter builds `CommandContext` → unified `BotCommand` (`gaia.ts` etc.) → `GaiaClient` HTTP call to API → `apps/api/app/agents/core/agent.py::call_agent()` → comms graph → executor → subagents → SSE stream back through `outbound-consumer.ts`.

---

## 6. Voice Mode

- `apps/voice-agent/` — separate Python app: `pyproject.toml`, `Dockerfile`, `mise.toml`, `project.json`, `CLAUDE.md`.
- `apps/voice-agent/src/worker.py` — LiveKit worker. Uses:
  - **STT** — `livekit.plugins.deepgram` (Deepgram).
  - **TTS** — `livekit.plugins.elevenlabs` (ElevenLabs).
  - **VAD** — `livekit.plugins.silero` (Silero VAD).
  - **Turn detection** — `livekit.plugins.turn_detector.multilingual.MultilingualModel`.
  - **Noise cancellation** — `livekit.plugins.noise_cancellation`.
  - **AgentSession** — streams chat responses from the backend over HTTP, pipes to TTS.
- `apps/voice-agent/src/config.py` — voice worker config.
- `apps/voice-agent/src/__main__.py` — CLI entrypoint: `start` or `download-files`.
- **Wake word** — `libs/wake-word/` (`@gaia/wake-word`): `src/core` (3-stage openWakeWord pipeline), `src/web` (onnxruntime-web + AudioWorklet + React hook), `src/native` (onnxruntime-react-native), `models/` (mel + embedding + VAD + classifier ONNX), `training/` (Piper TTS + LibriSpeech negatives + MPS training). 122 KB ONNX, ~80ms time-to-wake.

The voice worker is **just a transport** — speech in, speech out. All reasoning still goes through the comms → executor → subagent chain via HTTP.

---

## 7. Skills System

Follows the open **Agent Skills spec** (agentskills.io). Skills are folders of `SKILL.md` + scripts/resources installed into the user's JuiceFS workspace, exposed to the agent at runtime via the `<available_skills>` XML block in the system prompt.

### Core skill modules

- `apps/api/app/agents/skills/__init__.py` — module docstring.
- `apps/api/app/agents/skills/models.py` — `Skill`, `SkillMetadata`, `SkillSource` (github, inline, builtin, system).
- `apps/api/app/agents/skills/parser.py` — `parse_skill_md(content) -> (SkillMetadata, body)`. Parses YAML frontmatter; maps `allowed-tools` → `allowed_tools`; maps `subagent_id` → `target` (GAIA extension).
- `apps/api/app/agents/skills/registry.py` — MongoDB-backed CRUD in the `skills` collection. Redis-cached (`USER_SKILLS_CACHE_KEY`, TTL 12h). `_SKILLS_INVALIDATION_PATTERNS = ["skills:user:{user_id}:agent:*", "skills:text:v2:{user_id}:*"]`.
- `apps/api/app/agents/skills/installer.py` — `install_from_github`, `install_from_inline`, `uninstall_skill_full`.
- `apps/api/app/agents/skills/github_discovery.py` — clones GitHub repos and extracts skill folders.
- `apps/api/app/agents/skills/discovery.py` — generates the `<available_skills>` XML for system prompts.
- `apps/api/app/agents/skills/utils.py` — helpers.

### Built-in skills (37, in `apps/api/app/agents/skills/builtin/`)

Each is a directory containing a `SKILL.md` with YAML frontmatter. Examples:

- Calendar: `calendar-create-event/`, `meeting-create-invite/`, `plan-my-day/`
- Documents: `create-artifacts/`, `create-docx/`, `create-pdf/`, `create-pptx/`, `create-spreadsheet/`
- Gmail: `gmail-clean-inbox/`, `gmail-draft-send/`, `gmail-find-contacts/`, `gmail-search-context/`
- Notion: `notion-create-page/`, `notion-find-items/`, `notion-search-content/`, `notion-update-content/`
- GitHub: `github-create-issue/`, `github-create-pr/`
- Slack: `slack-send-message/`, `slack-gather-context/`, `meet-invite-slack/`
- Google: `googledocs-create-document/`, `googlesheets-analyze-data/`, `googlesheets-charts-graphs/`
- Other: `linear-create-issue/`, `linear-gather-context/`, `linkedin-create-post/`, `reddit-research-post/`, `posthog-find-metrics/`, `twitter-create-thread/`, `twitter-send-dm/`, `twitter-send-dm-legacy/`, `todoist-organize-tasks/`, `task-management/`
- GAIA system skills: `gaia-custom-instructions/`, `gaia-self-knowledge/`, `gaia-task-tracking/`

A skill's `target:` frontmatter binds it to a subagent (e.g. `target: gmail_agent`).

### Skill tools (for the skills subagent)

- `apps/api/app/agents/tools/skill_tools.py` — `install_skill_from_github`, `install_skill_inline`, `uninstall_skill`, `enable_skill`, `disable_skill`, `list_skills`. Consumed by the `skills` OAuth integration's subagent (system prompt `SKILLS_AGENT_SYSTEM_PROMPT` in `subagent_prompts.py`).
- The skills integration is itself defined in `oauth_config.py` (`subagent_config.tool_space="skills"`, `agent_name="skills_agent"`).

### Workspace mounting

- `apps/api/app/agents/workspace/skill_loader.py` — loads skills from VFS.
- `apps/api/app/agents/workspace/paths.py` — `WORKSPACE_ROOT`, `runs_log_dir`, `session_dir`, `INLINE_ARTIFACT_MAX_BYTES`, `is_under_workspace`, `detect_content_type`.
- `apps/api/app/agents/workspace/system_docs.py` — system-level docs loaded into the workspace.
- `apps/api/app/agents/workspace/system_files.py` — system file bodies.
- `apps/api/app/agents/workspace/operational_docs.py` — operational docs.

---

## 8. Memory

A **PG-backed** memory engine projected to VFS as Markdown (`/workspace/memory/...`), with ChromaDB for retrieval and passive learning.

### Memory engine

- `apps/api/app/memory/` — core memory engine (separate package):
  - `engine.py` — `memory_engine` (add/search/update/forget/journal/document actions).
  - `pg_store.py` — Postgres storage of core documents, last-30-days journal episodes, live facts by category.
  - `projection.py` — materializes memory to JuiceFS as Markdown (`materialize_memory`, `render_facts_page`, `render_journal_page`).
  - `retrieval.py` — `EpisodeHit` type, semantic search.

### Memory agent & active learning

- `apps/api/app/agents/memory/`
  - `__init__.py`
  - `email_processor.py` — LLM-based profile extraction from platform emails (GitHub username, LinkedIn URL, etc.). Uses `PydanticOutputParser`; validates via platform regex; builds canonical profile URLs.
  - `profile_crawler.py` — crawls discovered profiles.
  - `profile_extractor.py` — structured extraction.
  - `PLATFORM_CONFIG` — `sender_domains` + `regex_patterns` for twitter / github / linkedin / reddit.

### Memory services & projection

- `apps/api/app/services/memory_fs.py` — orchestrates PG → VFS projection with hash-gated fire-and-forget scheduler.
- `apps/api/app/services/_vfs_scheduler.py` — `make_scheduler`, `run_hashed_sync` (hash-gated VFS sync to avoid unnecessary writes).

### Memory models & constants

- `apps/api/app/models/memory_models.py` — `MemoryEntry`, `MemoryDocument`, `MemoryEpisode`.
- `apps/api/app/constants/memory.py` — `DEFAULT_RECALL_LIMIT`, `MEMORY_DOC_FILENAMES`, `MEMORY_TOOL_CONTENT_MAX_CHARS`, `MEMORY_TOOL_DOCUMENT_MAX_CHARS`, `MemoryDocType`, `MemorySourceType`, `ReconcileOutcome`, `PROJECTION_JOURNAL_DAYS`.

### Memory tools (comms + subagents)

- `apps/api/app/agents/tools/memory_tools.py` — LangChain tools: `add_memory`, `search_memory`, `update_memory`, `forget_memory`, `get_journal`, `search_journal`, `read_memory_document`. Each emits a `memory_data` stream event with a discriminated `action` field (the frontend contract).

### Memory prompts & docs

- `apps/api/app/agents/prompts/memory_prompts.py` — `SEARCH_MEMORY`, `ADD_MEMORY`, `FORGET_MEMORY`, `GET_JOURNAL`, `SEARCH_JOURNAL`, `READ_MEMORY_DOCUMENT` + per-integration `*_MEMORY_PROMPT` for context.
- `apps/api/app/templates/docstrings/memory_tool_docs.py` — tool docstrings.
- `apps/api/app/agents/workspace/system_docs.py` — `MEMORY_GUIDE_MD`.

### Active learning

`memory_node` (`apps/api/app/agents/core/nodes/memory_node.py`) is the end-graph hook on every comms + subagent turn. It runs LLM-based memory extraction passively, so conversational disclosures become durable memories without explicit `add_memory` calls.

### Frontend types

- `libs/shared/ts/src/types/memory.ts`.

---

## 9. Tools

### 9.1 Coding / sandbox tools (executor + subagents)

- `apps/api/app/agents/tools/coding/bash_tool.py` — `bash` (persistent shell, runs in user's E2B sandbox, base64 artifact publish, `truncate_head_tail` output cap, Prometheus `Counter`, `with_rate_limiting`).
- `apps/api/app/agents/tools/coding/read_tool.py` — `read` (reads via host-side JuiceFS mount to avoid sandbox spin-up; falls back to sandbox read in native dev; cap `MAX_SANDBOX_READ_BYTES = 10 MB`, `DEFAULT_LIMIT = 2000`, `MAX_LIMIT = 10_000`).
- `apps/api/app/agents/tools/coding/edit_tool.py` — in-place edits.
- `apps/api/app/agents/tools/coding/write_tool.py` — file writes.
- `apps/api/app/agents/tools/coding/_artifacts.py` — `publish_artifact` (sends inline files to frontend).
- `apps/api/app/agents/tools/coding/_context.py` — `get_session_id`, `get_user_id`, `safe_emit`, `canonical_path`, `sh_quote`.
- `apps/api/app/agents/tools/file_tools.py` — higher-level file ops.
- `apps/api/app/agents/tools/context_tool.py` — file/context gathering.

### 9.2 Tool discovery (`retrieve_tools`)

- `apps/api/app/agents/tools/core/registry.py` — `ToolRegistry`, `DynamicToolDict` (a `Mapping[str, BaseTool]` that lets tools added after graph compilation be visible to the agent), `get_tool_registry()` async singleton. `_CatalogToolMeta` — lightweight provider-tool metadata for warmup-time indexing.
- `apps/api/app/agents/tools/core/retrieval.py` — `get_retrieve_tools_function()` factory. Supports semantic search (query mode), exact binding (exact_tool_names mode), namespace filtering by user's connected integrations, subagent filtering. `WEBPAGE_TOOLS = [web_search_tool, fetch_webpages, deep_research]`. `_user_mcp_tool_names(user_id)` reads live tools from `MCPClient._tools` (post-resilience refactor).
- `apps/api/app/agents/tools/core/store.py` — `get_tools_store()` (ChromaDB store for tool embeddings).
- `apps/api/app/agents/tools/core/injectors.py` — dependency injection for tools.
- `apps/api/app/agents/tools/core/tool_runtime_config.py` — `build_child_tool_runtime_config`, `build_create_agent_tool_kwargs`, `build_provider_parent_tool_runtime_config`, `build_executor_child_tool_runtime_config`.

### 9.3 Subagent coordination

- `apps/api/app/agents/tools/wait_for_subagents_tool.py` — `wait_for_subagents(timeout=120)`. Polls `get_pending_subagents(stream_id)`; returns concatenated results from all background-dispatched subagents. Used by the executor for parallel subagent dispatch.

### 9.4 Lifecycle / orchestration

- `apps/api/app/agents/tools/executor_tool.py` — `call_executor`, `cancel_executor` (see §3).
- `apps/api/app/agents/tools/finish_task_tool.py` — `finish_task` (subagents signal completion with the final answer; absence = normal AIMessage).
- `apps/api/app/agents/tools/skill_tools.py` — see §7.

### 9.5 Workflows, todos, notifications, etc.

- `apps/api/app/agents/tools/workflow_tool.py` + `workflow_shared_tools.py` — see §10.
- `apps/api/app/agents/tools/notification_tool.py` — see §11.
- `apps/api/app/agents/tools/reminder_tool.py` — reminders.
- `apps/api/app/agents/tools/goal_tool.py` — goal management.
- `apps/api/app/agents/tools/todo_tool.py` — classic user-facing todos.
- `apps/api/app/agents/tools/todo_tools.py` — `plan_tasks`, `update_tasks` (in-state todo channel).
- `apps/api/app/agents/tools/tracked_todo_tools.py` — see §12.
- `apps/api/app/agents/tools/integration_instructions_tools.py` — `update_integration_instructions` (per-integration user instructions, always-on for subagents).
- `apps/api/app/agents/tools/integration_tool.py` — integration-agnostic tools.
- `apps/api/app/agents/tools/research_tool.py` — `deep_research` (Tavily + multi-source synthesis).
- `apps/api/app/agents/tools/webpage_tool.py` — `fetch_webpages`, `web_search_tool`.
- `apps/api/app/agents/tools/manual_tool.py` — `read_manual` (procedural docs).
- `apps/api/app/agents/tools/flowchart_tool.py` + `apps/api/app/templates/flowchart_template.py` — flowchart rendering.
- `apps/api/app/agents/tools/image_tool.py` — image generation/handling.
- `apps/api/app/agents/tools/weather_tool.py` — weather.
- `apps/api/app/agents/tools/support_tool.py` — support ticket creation.

---

## 10. Workflows

- `apps/api/app/services/workflow/`
  - `service.py` — `WorkflowService` CRUD.
  - `trigger_service.py` — `TriggerService` (composio triggers: gmail, calendar, slack, github, linear, todoist, sheets, docs).
  - `scheduler.py` — cron-based scheduled workflow execution.
  - `queue_service.py` — workflow execution queue.
  - `execution_service.py` — `WorkflowExecutionService` (runs workflows).
  - `generation_service.py` — AI workflow generation from natural language.
  - `context_extractor.py` — `WorkflowContextExtractor` (extracts context from conversation).
  - `workflow_subagent.py` — `WorkflowSubagentRunner` (subagent that generates workflows).
  - `subagent_output.py` — parses subagent JSON responses.
  - `trigger_search.py` — trigger search for `search_triggers` tool.
  - `notifications.py` — workflow notification rules.
  - `validators.py` — workflow validation.
  - `conversation_service.py` — conversation-bound workflows.
- `apps/api/app/agents/tools/workflow_tool.py` — `create_workflow`, `list_workflows`, `search_triggers`, `run_workflow`, etc. Uses `WorkflowSubagentRunner`. Direct creation for simple triggers; confirmation-required for integration triggers with config fields.
- `apps/api/app/agents/tools/workflow_shared_tools.py` — `SUBAGENT_WORKFLOW_TOOLS` shared between executor and the workflow subagent.
- `apps/api/app/models/workflow_models.py` — `Workflow`, `CreateWorkflowRequest`, `UpdateWorkflowRequest`, `WorkflowExecutionRequest`, `WorkflowExecutionResponse`, `WorkflowStatusResponse`, `TriggerConfig`, `TriggerType`, `PublicWorkflowsResponse`.
- `apps/api/app/models/trigger_config.py` — `TriggerConfig`, `TriggerConfigFieldSchema`, `WorkflowTriggerSchema`.
- `apps/api/app/services/system_workflows/`
  - `provisioner.py` — auto-provisions workflows on integration connect.
  - `definitions/` — built-in workflows: `definitions/gmail.py` (e.g. "Inbox Triage"), `definitions/calendar.py` (calendar-triggered workflows).
- `apps/api/app/services/scheduler_service.py` — `ScheduledTaskStatus` model + scheduler.
- `apps/api/app/agents/prompts/workflow_prompts.py` — `WORKFLOW_AUTO_NOTIFY_SECTION`, `WORKFLOW_SILENT_NOTIFY_SECTION`.
- Frontend: `libs/shared/ts/src/types/workflow.ts`, `libs/shared/ts/src/api/workflowsApi.ts`, `libs/shared/ts/src/hooks/useWorkflowsBase.ts`, `libs/shared/ts/src/workflows/`.

---

## 11. Notifications

- `apps/api/app/agents/tools/notification_tool.py` — `get_notifications`, `search_notifications`, `mark_notifications_read`, `send_notification`, `get_notification_count`, `get_notification_preferences`. Uses `get_stream_writer` to push real-time updates.
- `apps/api/app/services/notification_service.py` — `NotificationService` facade around `NotificationOrchestrator`.
- `apps/api/app/utils/notification/`
  - `orchestrator.py` — multi-channel routing.
  - `channels.py` — `ChannelAdapter`.
  - `actions.py` — `ActionHandler`.
  - `channel_preferences.py` — per-channel user prefs.
- `apps/api/app/models/notification/notification_models.py` — `NotificationRecord`, `NotificationRequest`, `NotificationType`, `NotificationStatus`, `NotificationSourceEnum`, `ChannelConfig`, `BulkActions`.
- `apps/api/app/constants/notifications.py` — `ALL_AUTO_INJECTED_CHANNELS`, `CHANNEL_TYPE_INAPP`.
- `apps/api/app/services/outbound_delivery.py` — proxies notifications to the right channel (in-app, email, bot, push).
- Frontend: `libs/shared/ts/src/types/notification.ts`, `libs/shared/ts/src/api/notificationsApi.ts`, `libs/shared/ts/src/hooks/useNotificationsBase.ts`.

---

## 12. Todos (three parallel systems)

### A) Lightweight in-conversation todos (in-state task list)

- `apps/api/app/agents/tools/todo_tools.py` — `plan_tasks`, `update_tasks`. Uses `InjectedState` and `Command(update=...)` to write directly to the `todos` channel. Emits `todo_progress` events via `get_stream_writer()`.
- `create_todo_pre_model_hook` injects task context into the latest non-memory SystemMessage before each LLM call.

### B) Tracked todos (durable, canvas-backed, cross-conversation)

- `apps/api/app/agents/tools/tracked_todo_tools.py` — `create_tracked_todo`, `update_tracked_todo`, `update_tracked_todo_canvas`, `complete_tracked_todo`, `search_todo_context`, `list_tracked_todos`. Backed by `apps/api/app/services/tracked_todo_service.py`. Supports cron recurrence + timezone-aware fire times.
- `apps/api/app/services/todo_canvas_storage.py` — VFS-backed canvas for tracked todos.
- `apps/api/app/db/mongodb/collections.py` — `todos_collection`.
- `apps/api/app/services/user_todos_fs.py` — VFS projection of todos.
- `apps/api/app/services/gaia_tasks_fs.py` — VFS projection of GAIA tasks.
- `apps/api/app/models/todo_models.py` — `TodoModel`, `TodoUpdateRequest`, `TodoResponse`, `Priority`, `ProjectCreate`, `SubTask`.
- `apps/api/app/constants/todos.py` — `GAIA_TRACKED_LABEL`.
- `apps/api/app/utils/canvas_vector_utils.py` — ChromaDB-backed `search_canvas_context` for cross-todo semantic search.

### C) Classic user-facing todos (CRUD UI)

- `apps/api/app/agents/tools/todo_tool.py` — `create_todo`, `update_todo`, `delete_todo`, `bulk_complete_todos`, `bulk_move_todos`, etc.
- `apps/api/app/services/todos/todo_service.py`, `todo_bulk_service.py`, `sync_service.py` — service layer.
- Frontend: `libs/shared/ts/src/types/todo.ts`, `libs/shared/ts/src/api/todosApi.ts`, `libs/shared/ts/src/hooks/useTodosBase.ts`, `libs/shared/ts/src/todos/`.

---

## 13. Sandbox (E2B)

- `apps/api/app/services/sandbox/`
  - `pool.py` — `SandboxPool` (per-user `AsyncSandbox` pool with `asyncio.Lock` and refcount; Prometheus `set_sandbox_pool_size` gauge; per-shard tracking for `JUICEFS_NUM_SHARDS`).
  - `lifecycle.py` — acquire / release / pause-on-idle (refcount-based kill timer).
  - `shard_router.py` — `shard_for(user_id)` distributes users across E2B sandboxes.
  - `artifact_watcher.py` — watches sandbox for produced files; emits to SSE.
  - `__init__.py` — `acquire_sandbox(user_id)` entrypoint + `SandboxAcquisitionError`.
- `apps/api/app/constants/sandbox.py` — `BASH_DEFAULT_TIMEOUT_SECONDS`, `BASH_MAX_COMMAND_LENGTH`, `BASH_MAX_TIMEOUT_SECONDS`, `WORKSPACE_TMP_SUFFIX`.
- All coding tools (bash, read, edit, write) target the user's E2B sandbox + JuiceFS mount.

---

## 14. MCP

- `apps/api/app/services/mcp/mcp_client.py` — `MCPClient` (source of truth for live per-user MCP tools; owns the warm sessions).
- `apps/api/app/services/mcp/mcp_token_store.py` — `MCPTokenStore(user_id)` (stores OAuth tokens for auth-required MCP integrations).
- `apps/api/app/services/mcp/mcp_tools_store.py` — `get_mcp_tools_store()` (ChromaDB for MCP tool embeddings).
- `apps/api/app/constants/mcp.py` — `INSTACART_MCP_SERVER_URL`, `YELP_MCP_SERVER_URL`, etc.

---

## 15. LLM Layer & LangGraph Override

- `apps/api/app/agents/llm/client.py` — `init_llm()`.
- `apps/api/app/agents/llm/chatbot.py` — chatbot-specific client.
- `apps/api/app/agents/llm/retry_policies.py` — `COMMS_RETRY_POLICY`, `EXECUTOR_RETRY_POLICY`, `SUBAGENT_RETRY_POLICY`.
- `apps/api/app/override/langgraph_bigtool/create_agent.py` — custom `create_agent` that integrates with the tool registry.
- `apps/api/app/override/langgraph_bigtool/hooks.py` — `HookType`.

---

## 16. Cross-Cutting Concerns

- **Tracing** — LangSmith (`@traceable` decorators in `executor_runner.py`) + Langfuse (`trace_id_for_message` in `app/config/langfuse.py`).
- **Rate limiting** — `apps/api/app/api/v1/middleware/tiered_rate_limiter.py`, `apps/api/app/decorators/rate_limiting.py`. Used by `notification_tool`, `workflow_tool`, `bash`, `read`, etc.
- **WebSocket** — `apps/api/app/core/websocket_manager.py` (real-time bot/event push).
- **Caching** — `apps/api/app/decorators/caching.py` (`Cacheable`, `CacheInvalidator`).
- **API client (TS)** — `libs/shared/ts/src/api/apiClient.ts`, `queryBuilder.ts`, `responseNormalizer.ts`.
- **Validation schemas (TS)** — `libs/shared/ts/src/validation/` (Zod for workflowSchemas, todoSchemas, reminderSchemas).
- **Workspace path helpers** — `apps/api/app/agents/workspace/paths.py` (canonical `/workspace/...` paths, session_dir, runs_log_dir).
- **Namespace derivation** — `apps/api/app/helpers/namespace_utils.py` (derives tool namespace from integration_id + server_url).
- **Wide-event logging** — `libs/shared/py/wide_events.py` (used throughout for structured logging with `log.set(...)`).

---

## 17. Quick-Reference: "Where do I change X?"

| If you want to… | Go to |
|---|---|
| Change the user-facing chat prompt / behavior | `apps/api/app/agents/core/graph_builder/build_graph.py` (comms) + `apps/api/app/agents/core/nodes/*` |
| Change the executor's tool set or handoff behavior | `apps/api/app/agents/core/graph_builder/build_graph.py` (executor) + `apps/api/app/agents/tools/executor_tool.py` |
| Add a new integration subagent | `apps/api/app/config/oauth_config.py` (register `SubAgentConfig`) + `apps/api/app/agents/tools/integrations/<provider>_tool.py` + `apps/api/app/agents/core/subagents/provider_subagents.py` |
| Add a new tool the executor can use | `apps/api/app/agents/tools/<your_tool>.py` + register in `apps/api/app/agents/tools/core/registry.py` |
| Add a built-in skill | `apps/api/app/agents/skills/builtin/<skill_name>/SKILL.md` |
| Change bot command behavior | `libs/shared/ts/src/bots/commands/<command>.ts` |
| Change voice STT/TTS/VAD | `apps/voice-agent/src/worker.py` + `apps/voice-agent/src/config.py` |
| Change memory projection | `apps/api/app/memory/projection.py` + `apps/api/app/services/memory_fs.py` |
| Change workflow triggers | `apps/api/app/services/workflow/trigger_service.py` + `apps/api/app/models/trigger_config.py` |
| Change tracked-todo canvas | `apps/api/app/services/todo_canvas_storage.py` + `apps/api/app/agents/tools/tracked_todo_tools.py` |
| Change sandbox behavior | `apps/api/app/services/sandbox/{pool,lifecycle,shard_router,artifact_watcher}.py` |
| Change notification routing | `apps/api/app/utils/notification/orchestrator.py` + `apps/api/app/services/outbound_delivery.py` |
