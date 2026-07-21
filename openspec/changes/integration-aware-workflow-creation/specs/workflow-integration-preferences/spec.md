## ADDED Requirements

### Requirement: Core capabilities are always available to step generation

Workflow step generation SHALL always expose core, non-integration capabilities (those whose tool category does not require a connected integration — e.g. web search, deep research, memory, todos, reminders) to the model, regardless of the preferred integration set. A preferred set SHALL only add to and bias the palette of integration-backed capabilities; it SHALL NOT remove core capabilities.

#### Scenario: Core search remains available when not in the preferred set

- **WHEN** step generation runs with a preferred set of `["notion"]` (which does not include search)
- **THEN** built-in web search and deep research are still available to the generated steps

### Requirement: Generation biases toward the preferred integration set

Step generation SHALL accept a caller-supplied preferred integration set and SHALL bias generated steps toward those integrations where they genuinely fit the goal. The preferred set is a preference, not a mandate: the model is not required to use every preferred integration.

#### Scenario: Preferred integration is used where it fits

- **WHEN** the workflow goal involves saving notes and the preferred set includes `notion`
- **THEN** the generated steps use Notion for the note-saving action

#### Scenario: Preferred integration is omitted where it does not fit

- **WHEN** a preferred integration has no relevance to the workflow goal
- **THEN** the generated steps do not force a step that uses that integration

### Requirement: Integrations that are neither preferred nor explicitly named are never suggested

When the user's request does not explicitly name an integration, step generation SHALL NOT introduce steps that depend on an integration outside the preferred set. Generic intents SHALL be satisfied with core capabilities rather than an unconnected, unnamed integration.

#### Scenario: Generic research never proposes an unconnected provider

- **WHEN** the user's prompt says to "research" a topic without naming any integration
- **AND** a research provider integration (e.g. Perplexity) is not connected and not in the preferred set
- **THEN** the generated steps use built-in web search / deep research
- **AND** no step depends on the unconnected research provider

### Requirement: Explicitly named supported integrations are included even if unconnected

When the user's request explicitly names an integration that the system supports, step generation SHALL include that integration in the steps even if the user has not connected it. If the named integration is not in the supported catalog, generation SHALL NOT invent a step for it.

#### Scenario: Named but unconnected supported integration is included

- **WHEN** the user's prompt explicitly asks to post a message to Slack
- **AND** Slack is in the supported catalog but the user has not connected it
- **THEN** the generated steps include a Slack step
- **AND** (per the gating capability) the resulting workflow is created deactivated with a missing-integration warning

#### Scenario: Named unsupported integration is not invented

- **WHEN** the user's prompt names an integration that is not in the supported catalog
- **THEN** the generated steps do not contain a step for that unsupported integration

### Requirement: Onboarding and manual creation share one generation path

Onboarding workflow creation and manual workflow creation SHALL use the same step-generation entrypoint and prompt, differing only in how the preferred integration set is supplied. For non-system (manually created) workflows, when the request supplies no explicit integration selection, the system SHALL default the preferred set to the user's currently connected integrations. When an explicit selection is supplied, that selection SHALL be used as the preferred set.

#### Scenario: Manual creation defaults to connected integrations

- **WHEN** a user manually creates a workflow and supplies no explicit integration selection
- **THEN** step generation runs with the user's currently connected integrations as the preferred set

#### Scenario: Manual creation honors an explicit selection

- **WHEN** a user manually creates a workflow and explicitly selects a subset of integrations
- **THEN** step generation runs with that selected subset as the preferred set
