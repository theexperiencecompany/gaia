## Context

Five agent tiers seed a LangGraph thread with an initial message array, which five pre-model hooks then rewrite before every LLM call. The rewrite — not the seed — is what the model receives.

```
                     build_agent_config  (shared, 9 call sites — OUT OF SCOPE)
                                 │
     ┌──────────────┬────────────┼─────────────┬───────────────┐
   comms        executor    provider sa      spawn         workflow
     │              │            │              │               │
construct_       prepare_    prepare_       _build_        WorkflowSubagent
langchain_       executor_   subagent_      context        Runner.execute
messages         execution   execution         │               │
     │              └────────┬───┴──────────────┘               │
     │                build_initial_messages                    │
     │                       │                                  │
build_dynamic_    create_agent_context_message ─────────────────┘
context_messages           (2nd impl)
   (1st impl)

                              ▼  seed
   [filter] → [adapt_media] → [exec_status?] → [manage_system_prompts] → [todo?] → LLM
                                                        ▲
                                    the real assembler — but it only re-orders
                                    whatever the emitters happened to stamp
```

`manage_system_prompts_node` owns the canonical slot order. The emitters do not know that order exists; they stamp marker keys onto `additional_kwargs` and hope. `create_agent_context_message` stamps `dynamic_context` + `memory_message` but never `memory_recall`, so every subagent's volatile per-turn content (memories, skills, provider metadata, banners) is placed in the byte-stable slot at index 1 — inside the region the implicit prompt cache keys on.

Constraints inherited from the existing code, all load-bearing and all currently protected only by comments:

- `langchain-google-genai` promotes a `SystemMessage` to `system_instruction` only while the system block is leading and contiguous; the first non-system message ends the block and every later `SystemMessage` is silently dropped.
- Implicit prompt caching matches on longest common prefix, so any per-minute byte (the clock) must live in `contents`, at the tail, never in `system_instruction`.
- The static per-tier prompt must be byte-identical across users, which is why `create_system_message` takes `user_id` and deliberately discards it.
- The comms narrator's executor result must be a `HumanMessage`: a `SystemMessage` occupies the static slot and evicts the comms persona; an `AIMessage` reads to Gemini as an answered turn and yields an empty completion.

## Goals / Non-Goals

**Goals:**

- One module answers "what does tier X see, and in what order".
- Per-tier differences are declarative data (a section × tier table), not divergent code.
- The prompt-slot order is a named, asserted contract rather than an emergent property.
- Tests can assert the *effective* array — post-hook, pre-LLM — in-process, with no compiled graph, no network, no LLM.
- The prefix-stability invariant that the whole design exists to protect becomes a CI check.

**Non-Goals:**

- `build_agent_config` and configurable inheritance. Already centralized in one function with one inheritance table and reasonable coverage; folding it in grows the class without clarifying anything.
- Middleware behaviour — summarization, compaction, media description, loop guard, HIL. They mutate context, but downstream of the assembly boundary this change owns.
- Re-introducing parent→child memory/skills prefetch. The dead plumbing is deleted here; a real prefetch optimization is a separate, trace-justified change.
- Changing which sections a tier gets, except the three corrections named below.
- Prompt *text*. Section bodies are ported verbatim.

## Decisions

### 1. A section registry, not per-tier builders

Each context section is a declaration: which slot it targets, how to fetch its text, which tiers it applies to, and its order within the slot. Tiers become rows.

```
Section(id, slot, applies_to={tiers}, order, fetch)

                    comms  exec  provider  spawn  workflow   slot
core_memory           ●      ○      ○        ○       ○       memory_recall
memory_recall         ●      ●      ●        ●       ●       memory_recall
gaia_knowledge        ●      ○      ○        ○       ○       memory_recall
tracked_todos         ●      ○      ○        ○       ○       memory_recall
skills                ●      ●      ●        ○       ○       memory_recall
bg_banner             ●      ●      ●        ●       ○       memory_recall
active_todo_banner    ●      ●      ●        ●       ○       memory_recall
user_identity         ●      ●      ●        ●       ●       dynamic_stable
user_prefs            ●      ○      ○        ○       ○       dynamic_stable
integrations_manifest ●      ●      ○        ○       ●       dynamic_stable
workspace_session     ○      ●      ●        ●       ○       dynamic_stable
provider_metadata     ○      ○      ●        ○       ○       dynamic_stable
custom_instructions   ○      ○      ●        ○       ○       dynamic_stable
```

Alternatives rejected: a base class with per-tier subclasses (five subclasses to express what is a boolean per cell, and the override points become the new place divergence hides); keeping two implementations and adding a shared helper (leaves both call graphs live, so the next divergence is one edit away).

The classification into `dynamic_stable` vs `memory_recall` is the correctness fix. Anything whose content depends on the current query or turn is volatile and belongs in the tail slot; anything that changes only when the user edits preferences or connects an integration is stable and belongs in the cacheable prefix.

### 2. Slots become a named enum, and `manage_system_prompts_node` sorts by it

Today the node hand-rolls a marker-per-slot scan with parallel `latest_*_idx` variables and a fixed if/elif chain. Slots move to one enum that declares canonical order; the node resolves each message's slot and sorts. Adding a slot becomes one enum entry, not five edits across a scan, an assignment block, and an append sequence.

Marker reading keeps the existing `additional_kwargs`-then-`model_extra` fallback: checkpointed threads written before the marker migration must keep resolving.

### 3. Test the effective array via `execute_hooks` directly

`execute_hooks(hooks, state, config, store)` (`app/override/langgraph_bigtool/hooks.py`) is a plain async function over a plain state dict. The harness needs no graph, no checkpointer, no LLM:

```
seed = assemble(tier, ...)
state = await execute_hooks(hooks_for(tier), {"messages": seed, ...}, config, store)
assert slots_of(state["messages"]) == CANONICAL_ORDER
```

Alternatives rejected: compiling a real graph (needs Postgres/Chroma/Redis, slow, and the assertion target is buried in stream events); asserting the seed only (the scoping decision explicitly rejected this — the mis-slotted subagent content is invisible at the seed).

Determinism comes from injecting a fixed clock and faking the five IO edges the sections touch: `memory_engine.recall` / `get_core_context`, `gaia_knowledge_service.search_knowledge`, `tracked_todo_service`, `get_provider_metadata` / `get_instructions`, and `get_connected_integrations_named`.

### 4. Characterization snapshots are scaffolding, not the deliverable

Snapshot every tier's effective array before touching production code. Any snapshot that cannot be explained is a bug found. But a snapshot test alone cannot fail meaningfully — it records whatever the code does — so each snapshot ships alongside real assertions: slot order, marker correctness, prefix stability, and absence of per-user bytes in the static prompt. The snapshots exist to make the refactor safe; the assertions are what stays valuable.

### 5. One canonical seed order for all five tiers

Comms emits `[…, human, time]`; the other tiers emit `[…, time, human]`. Harmless today only because `manage_system_prompts_node` reorders — the invariant is enforced in one place and violated in another. All tiers emit the canonical order; the node's reordering becomes idempotent for a fresh seed instead of load-bearing.

### 6. Three intentional behaviour changes

Everything else is ported verbatim. These three are corrections, each with its own failing-first test:

| # | Today | After | Why |
|---|---|---|---|
| 1 | Subagent volatile content sits in `dynamic_stable` | Sits in `memory_recall` | The cache-prefix bug this change exists to fix |
| 2 | Workflow authoring tier gets no clock message | Gets the clock | No tier should be blind to the date; its absence is unexplained by any comment |
| 3 | Banners lead in the subagent path, trail in comms | Trail in every tier | After assembly the volatile slot already sits at the tail of `system_instruction`, immediately before contents, so intra-slot position moves a few hundred bytes at the very end. Recency is the stronger argument and comms already depends on it. |

A fourth divergence — comms formats recalled memories via `entry_to_note` (dated), subagents use raw `mem.content` — is unified on `entry_to_note`. Dates are strictly more information, and no comment defends the raw form.

### 7. Delete the dead prefetch plumbing

`__pinned_memories__` / `__pinned_skills__` are threaded through every configurable (`agent_helpers.py:186-187, 222-223, 363-364`) and the `memories_text` / `skills_text` parameters are documented as avoiding duplicate ChromaDB lookups — but nothing writes the keys and no call site passes the parameters. Every subagent still runs its own recall. Deleting keeps this change to one reason for a snapshot to move.

## Risks / Trade-offs

- **A load-bearing comment gets refactored away, reopening a fixed regression.** Four are documented with prior incidents (HumanMessage narration, Gemini contiguity, clock placement, `vfs_session_id` fallback) → each becomes an explicit test before any production code moves, so the fence is enforced by CI rather than by the next reader noticing the comment.
- **Behaviour change #3 (banner recency) alters real prompts.** The reasoning is sound but untested against a live model → verified with a live background run via the `driving-gaia` skill (a scheduled/headless run must still execute without asking clarifying questions) before the change is considered done.
- **The harness fakes five IO edges; a section could pass under fakes and fail against real services.** → integration-tier coverage for the two sections with the most complex real behaviour (connected-integrations manifest, tracked-todos summary) keeps the fakes honest.
- **Snapshot churn hides a real regression in review.** → snapshots land and are reviewed in their own commit, before any behaviour changes; every later snapshot movement must be attributable to a named test.
- **Five call sites port at once; a partial migration leaves three implementations instead of two.** → the old functions are deleted in the same change, so a missed call site is an import error, not a silent fallback.
- **`memory_recall` reslotting shifts real cache boundaries for subagents.** That is the intended fix, but it changes cache-hit characteristics in production → the prefix-floor test states the expected new behaviour explicitly, and the wide-event `dynamic_context` fields already log stable vs volatile character counts for post-deploy comparison.

## Migration Plan

1. **Characterize.** Harness + snapshots + explicit invariant assertions for all five tiers against today's code. No production changes. Explain every snapshot; unexplained output is a defect logged here.
2. **Fix under the snapshots.** One failing-first test per defect (mis-slotting, missing clock, seed order), fixed in the existing structure. Snapshots move only where a test says so.
3. **Extract the registry.** Sections and slots move into the new module; the two dynamic-context implementations are deleted; all five call sites port. Snapshots must not move.
4. **Clean up.** Delete the dead prefetch plumbing; correct `ARCHITECTURE.md`.

Rollback: steps 1 and 2 stand alone and are independently valuable. Step 3 is a pure structural move under green snapshots and reverts as one commit.

## Open Questions

- Should the prefix-stability floor be a fixed byte count or a ratio of the static+stable block? A ratio survives prompt edits; a fixed floor catches silent prompt growth. Decide when the first real measurement exists (step 1).
- Does the workflow authoring tier want the connected-integrations manifest as a proper `dynamic_stable` section instead of hand-folded into its `HumanMessage`? The hand-folding is a documented workaround for the static-slot eviction the registry removes, so the workaround may no longer be needed — confirm once the registry exists.
