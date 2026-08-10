## Why

Five agent tiers (comms, executor, provider subagent, spawned subagent, workflow authoring) build their run context through two divergent implementations and three hand-rolled variants, so no single place answers "what does this agent actually see?". The prompt-cache contract that every design decision in this code protects — a byte-stable request prefix across turns and users — is enforced only by comments, and it is already broken: `create_agent_context_message` never stamps the `memory_recall` marker, so every subagent's volatile per-turn content lands in the cacheable stable slot, the exact failure `manage_system_prompts_node` exists to prevent. Nothing caught it because no test can observe the message array the model receives.

## What Changes

- Introduce a single **context assembly** layer: a section registry where each context section declares its prompt slot, its fetch, and which tiers it applies to. Tier differences become rows in a table instead of divergent code paths.
- Collapse the two dynamic-context implementations (`build_dynamic_context_messages` for comms, `create_agent_context_message` for everything else) into that one registry. **BREAKING** for internal callers: both functions are removed.
- Make the assembled slot order (`[static, dynamic_stable, todo, bg_exec, exec_status, memory_recall, …conversation…, time]`) an explicit, asserted contract rather than an emergent property of emitters that don't know the slot list exists.
- Add an in-process **hook-chain harness** so tests can assert the *effective* message array — the seed run through `filter_messages_node`, `adapt_media_node`, `executor_status_hook`, `manage_system_prompts_node`, and the todo hook — without compiling a graph or calling an LLM.
- Add prompt-cache invariant tests: same user, two runs minutes apart, must share a request prefix at or above a floor; the static prompt must stay byte-identical across users.
- Fix the defects the harness exposes: subagent volatile content mis-slotted into the stable block; the workflow authoring subagent receiving no clock message at all; seed message ordering that differs between comms and every other tier.
- **BREAKING** (internal): delete the dead prefetch plumbing — the `__pinned_memories__` / `__pinned_skills__` configurable keys, which nothing writes and nothing reads, and the `memories_text` / `skills_text` parameters, which no call site has ever passed.
- Correct `ARCHITECTURE.md`, which cites a non-existent `app/agents/core/state.py`.

Out of scope: config/`configurable` construction (`build_agent_config` stays as-is), middleware behaviour (summarization, compaction, media, loop guard), and re-introducing parent→child memory prefetch as a latency optimization.

## Capabilities

### New Capabilities
- `agent-context-assembly`: how every agent tier's run context is assembled — the section registry, the prompt-slot ordering contract, per-tier section applicability, and the prompt-cache prefix-stability guarantees that ordering exists to protect.

### Modified Capabilities
<!-- None. No existing spec in openspec/specs/ (fs-metrics-prometheus, tracked-todos-vfs) covers agent context. -->

## Impact

**Replaced / removed**
- `app/helpers/message_helpers.py` — `build_dynamic_context_messages`, `DynamicContextMessages`, the `_get_*_section` fetchers, and the marker helpers move into the registry.
- `app/agents/core/subagents/subagent_helpers.py` — `create_agent_context_message` and its `_fetch_*_block` helpers move into the registry.
- `app/helpers/agent_helpers.py` — `__pinned_memories__` / `__pinned_skills__` keys and their inheritance entries deleted.

**Call sites that must be ported**
- `app/agents/core/messages.py` (comms), `app/agents/core/subagents/subagent_runner.py` (executor + shared `build_initial_messages`), `app/agents/core/subagents/handoff_tools.py` (provider subagent), `app/agents/middleware/subagent.py` (spawn), `app/services/workflow/workflow_subagent.py` (workflow authoring).

**Behaviour that must not move**
- The clock stays in a `HumanMessage` at the tail of contents, never in `system_instruction`.
- The system block stays leading and contiguous (`langchain-google-genai` drops any `SystemMessage` after a non-system message).
- The comms narrator's executor result stays a `HumanMessage` (a `SystemMessage` evicts the comms persona; an `AIMessage` yields an empty Gemini completion).
- `vfs_session_id` never falls back to `thread_id`.

**Tests**
- New: hook-chain harness, per-tier assembled-context tests, prompt-cache invariant tests.
- Updated: `tests/unit/agents/test_messages.py`, `tests/unit/helpers/test_message_helpers.py`, `tests/unit/agents/test_subagent_runner.py`, `tests/unit/agents/nodes/test_manage_system_prompts.py`, `tests/unit/helpers/test_agent_helpers.py`.

**Docs**
- `ARCHITECTURE.md` §2/§4 file inventory.
