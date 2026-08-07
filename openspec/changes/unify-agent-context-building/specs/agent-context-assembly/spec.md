## ADDED Requirements

### Requirement: Single assembly entry point for every agent tier

The system SHALL assemble the initial context of every agent tier — comms, executor, provider subagent, spawned subagent, and workflow authoring — through one context-assembly module. No tier SHALL construct its own dynamic-context message.

#### Scenario: Every tier resolves through the registry

- **WHEN** any of the five tiers seeds a run
- **THEN** its dynamic-context message is produced by the shared assembly module
- **AND** no other module in `app/` exposes a function that builds a dynamic-context system message

#### Scenario: A missed call site fails loudly

- **WHEN** the previous implementations (`build_dynamic_context_messages`, `create_agent_context_message`) are removed
- **THEN** any remaining caller fails at import time
- **AND** no fallback path silently produces a differently-shaped context

### Requirement: Per-tier section applicability is declarative

Each context section SHALL declare the set of tiers it applies to, and tier differences SHALL be expressed as data rather than as branching in tier-specific code paths.

#### Scenario: Provider-only sections are absent from other tiers

- **WHEN** the executor tier assembles its context
- **THEN** the provider-metadata and custom-instructions sections are absent
- **AND** when a provider subagent assembles its context those sections are present

#### Scenario: Comms-only sections are absent from worker tiers

- **WHEN** a provider subagent assembles its context
- **THEN** the GAIA-knowledge, tracked-todos-summary, and user-preferences sections are absent

#### Scenario: Adding a section to a tier is a single declaration

- **WHEN** an existing section is enabled for an additional tier
- **THEN** the change is confined to that section's tier set
- **AND** no tier-specific assembly code is modified

### Requirement: Canonical prompt-slot ordering

The assembled message array SHALL place messages in the canonical slot order `[static, dynamic_stable, todo_context, background_executor, executor_status, memory_recall, …conversation…, time]`, and slot order SHALL be defined in exactly one place.

#### Scenario: Slots are ordered canonically after assembly

- **WHEN** a state containing messages for every slot, in arbitrary order, is run through the pre-model hook chain
- **THEN** the resulting array's slots appear in canonical order

#### Scenario: Only the latest message per slot survives

- **WHEN** a thread accumulates several messages carrying the same slot marker across turns
- **THEN** exactly one message per slot remains in the array passed to the model
- **AND** the survivor is the most recently emitted one

#### Scenario: Legacy checkpointed markers still resolve

- **WHEN** a message carries only the legacy `memory_message` marker, or carries its marker in `model_extra` rather than `additional_kwargs`
- **THEN** it resolves to the stable dynamic slot

### Requirement: The system block is leading and contiguous

Every system message intended for the model SHALL appear at the front of the array in one unbroken run, because the Google provider adapter promotes system messages to `system_instruction` only while they are leading and contiguous and silently discards any that follow a non-system message.

#### Scenario: No system message trails a non-system message

- **WHEN** any tier's context is assembled and run through the hook chain, on a first turn or on a multi-turn thread
- **THEN** no `SystemMessage` appears after the first non-system message in the array

### Requirement: Volatile content is separated from the cacheable prefix

Content that varies per turn or per query — memory recall, core memory, GAIA knowledge, skills, tracked todos, and run banners — SHALL be carried in the `memory_recall` slot. Content that changes only when the user edits preferences or connects an integration SHALL be carried in the `dynamic_stable` slot.

#### Scenario: Subagent volatile content is not in the stable slot

- **WHEN** a provider subagent assembles a context containing recalled memories, skills, or a run banner
- **THEN** that content is carried in the `memory_recall` slot
- **AND** the `dynamic_stable` slot contains no per-query content

#### Scenario: Stable content is not displaced by a query change

- **WHEN** the same user assembles context for two different queries
- **THEN** the `dynamic_stable` message content is byte-identical across both

### Requirement: The clock is a trailing HumanMessage

Current time SHALL be carried in a `HumanMessage` positioned at the tail of the array, and SHALL NOT appear in any system message. Every tier SHALL receive a clock message.

#### Scenario: Clock is last and is not a system message

- **WHEN** any tier's context is assembled and run through the hook chain
- **THEN** the final message in the array is the time-context `HumanMessage`
- **AND** no system message contains a current timestamp

#### Scenario: The workflow authoring tier receives a clock

- **WHEN** the workflow authoring subagent assembles its context
- **THEN** the array contains exactly one time-context `HumanMessage`

#### Scenario: Only the latest clock survives a multi-turn thread

- **WHEN** a checkpointed thread contains time-context messages from earlier turns
- **THEN** exactly one time-context message reaches the model
- **AND** it carries the current time

### Requirement: The static prompt is user-independent

The static per-tier system prompt SHALL be byte-identical across users on the same tier and channel, and SHALL contain no user name, identifier, timezone, memory, or other per-user content.

#### Scenario: Two users share a byte-identical static prompt

- **WHEN** two different users assemble context for the same tier and channel
- **THEN** their static system messages are byte-identical

#### Scenario: User identity is carried outside the static prompt

- **WHEN** a user with a known name and timezone assembles context
- **THEN** that name and timezone appear in the `dynamic_stable` message and not in the static prompt

### Requirement: Request prefix stability across turns

For a given user and tier, the assembled request prefix SHALL remain stable across turns that change only the clock and the user's message, so the provider's implicit prompt cache can match.

#### Scenario: A minute tick does not shift the prefix

- **WHEN** the same user and tier assemble context twice with only the clock advanced
- **THEN** the two arrays share a common prefix at or above the declared floor
- **AND** the only differing content is the trailing time message and the conversation turns

#### Scenario: A new query does not shift the stable prefix

- **WHEN** the same user assembles context for two different queries whose recalled memories differ
- **THEN** the static and `dynamic_stable` messages are byte-identical across both
- **AND** the differing content is confined to the `memory_recall` slot

### Requirement: Assembled context is observable without a compiled graph

The system SHALL allow the effective message array — the seed after all pre-model hooks have run — to be produced in-process for a given tier, without compiling a LangGraph graph, connecting to a checkpointer, or invoking a language model.

#### Scenario: Effective array is produced in-process

- **WHEN** a tier's context is assembled and run through that tier's pre-model hook chain with injected fakes for the clock and external data sources
- **THEN** the resulting array is returned directly for assertion
- **AND** no database, cache, vector store, or model endpoint is contacted

#### Scenario: Assembly is deterministic under fixed inputs

- **WHEN** the same tier is assembled twice with identical injected inputs and a fixed clock
- **THEN** the two arrays are byte-identical

### Requirement: Uniform seed message order

Every tier SHALL emit its seed array in one canonical order, so that hook reordering is a normalization of already-correct input rather than a correction of divergent input.

#### Scenario: Seed order matches the canonical order before hooks run

- **WHEN** any tier produces its seed array
- **THEN** the array is already in canonical slot order
- **AND** running it through the hook chain leaves the slot order unchanged
