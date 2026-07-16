## ADDED Requirements

### Requirement: The system computes the integrations a workflow requires

The system SHALL deterministically compute the set of integrations a workflow requires from (a) its steps' categories — mapping each category to its integration via the tool registry, counting only categories that require a connected integration — and (b) its trigger, when the trigger is an integration trigger. Categories backed only by core capabilities SHALL contribute no required integration. Only integrations present and available in the supported catalog SHALL be considered.

#### Scenario: Integration-backed step category contributes a required integration

- **WHEN** a workflow has a step whose category maps to an integration-backed tool category (e.g. `gmail`)
- **THEN** that integration is included in the workflow's required integrations

#### Scenario: Core-only step category contributes nothing

- **WHEN** a workflow has a step whose category is backed only by core capabilities (e.g. `search`)
- **THEN** no integration is added to the workflow's required integrations on account of that step

#### Scenario: Integration trigger contributes a required integration

- **WHEN** a workflow's trigger is an integration trigger for a given integration
- **THEN** that integration is included in the workflow's required integrations

### Requirement: Missing integrations are computed on read against the connected set

The system SHALL compute a workflow's `missing_integrations` as its required integrations minus the integrations the user currently has connected, evaluated at read time so it reflects the user's current connection state. Each missing integration entry SHALL carry enough display information (id/slug, name, icon) for the UI to render it. Workflow read responses SHALL include `missing_integrations`.

#### Scenario: Unconnected required integration is reported as missing

- **WHEN** a workflow requires `gmail` and the user has not connected Gmail
- **THEN** the workflow read response lists Gmail in `missing_integrations` with its display name and icon

#### Scenario: Missing list clears after connecting

- **WHEN** a workflow previously reported `gmail` as missing
- **AND** the user connects Gmail
- **THEN** a subsequent read of that workflow reports an empty `missing_integrations`

### Requirement: Workflows with missing integrations are created deactivated

When a workflow is created (via onboarding or manual creation) and its computed missing integrations are non-empty, the system SHALL persist it as deactivated and SHALL NOT schedule it for execution.

#### Scenario: Onboarding workflow needing an unconnected integration is created disabled

- **WHEN** an onboarding workflow is generated with steps that require an integration the user has not connected
- **THEN** the workflow is persisted with `activated` false
- **AND** it is not scheduled to run

#### Scenario: Manual workflow needing an unconnected integration is created disabled

- **WHEN** a user manually creates a workflow whose steps require an integration they have not connected
- **THEN** the workflow is persisted with `activated` false and is not scheduled

### Requirement: Activation is rejected while integrations are missing

The activation path SHALL refuse to activate a workflow whose missing integrations are non-empty, failing loud with an error that names the integrations the user must connect, and the workflow SHALL remain deactivated. Once all required integrations are connected, activation SHALL succeed.

#### Scenario: Activation blocked when an integration is missing

- **WHEN** a user attempts to activate a workflow that has missing integrations
- **THEN** activation is rejected with an error naming the missing integrations
- **AND** the workflow remains deactivated

#### Scenario: Activation succeeds after connecting required integrations

- **WHEN** a user connects all of a workflow's missing integrations and then activates it
- **THEN** activation succeeds and the workflow becomes activated

### Requirement: Workflow cards show a disabled-with-warning state when integrations are missing

In the UI, any workflow card whose `missing_integrations` is non-empty — including onboarding suggestion cards — SHALL display a yellow warning indicator, SHALL disable the run and activate controls, and SHALL communicate via tooltip which integrations the user must connect to enable the workflow.

#### Scenario: Card warns and disables controls

- **WHEN** a workflow card is rendered for a workflow with non-empty `missing_integrations`
- **THEN** the card shows a yellow warning indicator
- **AND** the run and activate controls are disabled
- **AND** a tooltip names the integrations that must be connected to enable the workflow

#### Scenario: Card returns to normal after integrations are connected

- **WHEN** the workflow's `missing_integrations` becomes empty after the user connects the required integrations
- **THEN** the card no longer shows the warning and the run and activate controls are enabled
