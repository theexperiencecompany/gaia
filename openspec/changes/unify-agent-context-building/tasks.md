## 1. Hook-chain harness

- [x] 1.1 Add `tests/_harness/context_chain.py` exposing `effective_context(tier, *, user, query, configurable_overrides, now)` that seeds a tier's context and runs it through that tier's real pre-model hook list via `execute_hooks` from `app/override/langgraph_bigtool/hooks.py` — no compiled graph, no checkpointer, no LLM.
- [x] 1.2 Register the five tiers in the harness with their real hook lists: comms (`filter_messages`, `executor_status`, `manage_system_prompts`), executor (`filter_messages`, `adapt_media`, `manage_system_prompts`, todo hook), provider subagent (same as executor), spawn (`filter_messages`, `adapt_media`, `manage_system_prompts`), workflow authoring (provider-subagent stack, `authoring_only`).
- [x] 1.3 Add a fixed-clock fixture so `build_current_time_message` is deterministic, and assert two runs with identical inputs produce byte-identical arrays.
- [x] 1.4 Add fakes for the five IO edges the sections touch: `memory_engine.recall` / `get_core_context`, `gaia_knowledge_service.search_knowledge`, `tracked_todo_service.get_active_tracked_summary`, `get_provider_metadata` / `get_instructions`, `get_connected_integrations_named`. Assert no DB/cache/vector-store/model call escapes the harness.
- [x] 1.5 Add a `slots_of(messages)` helper that maps each message to its canonical slot, so tests assert slot sequences rather than message indices.

## 2. Characterize today's behaviour

- [x] 2.1 Snapshot the effective array for all five tiers under a common fixture (named user, timezone, memories, skills, one connected integration).
- [x] 2.2 Snapshot the executor and provider-subagent tiers with an active todo and `execution_mode="background"` so both banners appear.
- [x] 2.3 Snapshot a multi-turn thread carrying stale duplicates in every slot, to pin the "latest survives" behaviour.
- [x] 2.4 Read every snapshot and record an explanation for each line; log anything unexplained as a defect in this change's design Open Questions.

## 3. Invariant tests that must pass today

- [x] 3.1 System block is leading and contiguous — no `SystemMessage` follows the first non-system message, on first turn and multi-turn, for all five tiers.
- [x] 3.2 Static prompt is byte-identical across two different users on the same tier and channel, and contains no user name, id, or timezone.
- [x] 3.3 Clock is the final message, is a `HumanMessage`, and no system message contains a timestamp.
- [x] 3.4 Exactly one message survives per slot; the survivor is the latest.
- [x] 3.5 Legacy markers resolve: `memory_message`-only, and marker present in `model_extra` instead of `additional_kwargs`.
- [x] 3.6 `vfs_session_id` absent from configurable yields no workspace-session banner and never falls back to `thread_id`.
- [x] 3.7 Mutation-check the new assertions per the `accurate-testing` skill: break each invariant in production code, confirm the matching test fails, restore.

## 4. Failing-first tests for the three defects

- [x] 4.1 Provider subagent with recalled memories, skills, and a run banner places that content in the `memory_recall` slot and leaves `dynamic_stable` free of per-query content — **must fail** against current code.
- [x] 4.2 Workflow authoring tier contains exactly one time-context `HumanMessage` — **must fail** against current code.
- [x] 4.3 Every tier's seed array is already in canonical slot order before hooks run — **must fail** for comms (`human` before `time`) against current code.
- [x] 4.4 Same user, same tier, two queries with different recalled memories: static and `dynamic_stable` are byte-identical and all difference is confined to `memory_recall` — **must fail** for subagent tiers against current code.

## 5. Fix the defects in the existing structure

- [x] 5.1 Stamp the `memory_recall` marker on the volatile portion of `create_agent_context_message` and split its output into stable and volatile messages; 4.1 and 4.4 go green.
- [x] 5.2 Add the clock message to `WorkflowSubagentRunner.execute` initial state; 4.2 goes green.
- [x] 5.3 Unify seed order to canonical in `construct_langchain_messages` and `build_initial_messages`; 4.3 goes green.
- [x] 5.4 Re-record snapshots from task 2 and confirm every movement is attributable to a named test from task 4.

## 6. Extract the section registry

- [x] 6.1 Add `app/agents/context/slots.py`: a `PromptSlot` enum declaring canonical order, plus marker read/write helpers preserving the `additional_kwargs` → `model_extra` fallback.
- [x] 6.2 Rewrite `manage_system_prompts_node` to resolve each message to a `PromptSlot` and sort by the enum, replacing the parallel `latest_*_idx` scan and the fixed if/elif chain. Snapshots must not move.
- [x] 6.3 Add `app/agents/context/sections.py`: a `Section(id, slot, applies_to, order, fetch)` declaration plus the section table from design decision 1.
- [x] 6.4 Port the comms-only section bodies verbatim from `message_helpers.py` (`core_memory`, `gaia_knowledge`, `tracked_todos`, `user_prefs`).
- [x] 6.5 Port the worker-tier section bodies verbatim from `subagent_helpers.py` (`workspace_session`, `provider_metadata`, `custom_instructions`).
- [x] 6.6 Port the shared section bodies (`user_identity`, `memory_recall`, `skills`, `integrations_manifest`, `bg_banner`, `active_todo_banner`), unifying memory formatting on `entry_to_note` and moving both banners to trail their slot per design decision 6.
- [x] 6.7 Add `app/agents/context/assemble.py` exposing the single entry point that gathers applicable sections concurrently and emits the stable + volatile system messages.
- [x] 6.8 Preserve the `dynamic_context` wide-event fields (`stable_chars`, `memory_recall_chars`, `has_*`) so post-deploy comparison stays possible.

## 7. Port call sites and delete the old implementations

- [x] 7.1 Port comms (`app/agents/core/messages.py`) to the registry.
- [x] 7.2 Port the shared `build_initial_messages` (`app/agents/core/subagents/subagent_runner.py`), covering executor, provider subagent, and spawn.
- [x] 7.3 Port workflow authoring (`app/services/workflow/workflow_subagent.py`); resolve the design Open Question on whether its hand-folded integrations manifest can become a real `dynamic_stable` section.
- [x] 7.4 Delete `build_dynamic_context_messages`, `DynamicContextMessages`, and the `_get_*_section` fetchers from `message_helpers.py`.
- [x] 7.5 Delete `create_agent_context_message` and its `_fetch_*_block` helpers from `subagent_helpers.py`.
- [x] 7.6 Confirm no caller of either removed function remains anywhere in `app/` or `tests/`.
- [x] 7.7 Update the existing tests that target the removed functions: `tests/unit/agents/test_messages.py`, `tests/unit/helpers/test_message_helpers.py`, `tests/unit/agents/test_subagent_runner.py`, `tests/unit/agents/nodes/test_manage_system_prompts.py`.

## 8. Delete the dead prefetch plumbing

- [x] 8.1 Remove `__pinned_memories__` / `__pinned_skills__` from `build_agent_config` and their entries in `_inherit_from_parent_configurable` (`app/helpers/agent_helpers.py`).
- [x] 8.2 Remove the never-passed `memories_text` / `skills_text` parameters from `build_initial_messages` and the assembly entry point.
- [x] 8.3 Remove the `used_pinned_memories` wide-event field and update `tests/unit/helpers/test_agent_helpers.py`.
- [x] 8.4 Confirm no reference to any pinned-prefetch key or parameter remains.

## 9. Prefix-stability guarantee

- [x] 9.1 Measure the real common-prefix length for each tier across a clock tick and across a query change; record the numbers.
- [x] 9.2 Resolve the design Open Question on fixed byte floor vs ratio of the static+stable block, then add the prefix-floor test for all five tiers.
- [x] 9.3 Add an integration-tier test for the two sections with the most complex real behaviour — connected-integrations manifest and tracked-todos summary — so the unit fakes stay honest.

## 10. Verify and document

- [x] 10.1 `nx type-check api` and `nx lint api` clean.
- [x] 10.2 Test suite green, run in chunks: unit 12,761 passed / 2 xfailed, integration 836 passed / 179 skipped, e2e 507 passed / 5 skipped, meta+stress 15 passed. No test weakened or skipped to get there. One pre-existing failure remains in `tests/unit/app/` — the `_env_pollution_guard` trips on `GAIA_SERVICE_NAME`, set by `os.environ.setdefault` at import of `app/workers/lifecycle/startup.py`. Which test it lands on varies with xdist sharding. Every input (the two smoke tests, `tests/conftest.py`, `startup.py`) is untouched by this change.
- [ ] 10.3 Drive a live headless/background run via the `driving-gaia` skill and confirm the banner-recency change (design decision 6, row 3) still yields an action-only run with no clarifying questions.
- [ ] 10.4 Drive a live provider-subagent handoff and confirm provider metadata and custom instructions still reach the subagent.
- [x] 10.5 Update `ARCHITECTURE.md` §2/§4: replace the non-existent `app/agents/core/state.py` reference and point the context-building entries at the new module.
