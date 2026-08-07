## ADDED Requirements

### Requirement: Onboarding collects preferred integrations after Gmail connection

After the Gmail connection step, the onboarding wizard SHALL present an integration-selection step where the user picks the integrations they use most. The selector SHALL search and select over the **full supported integration catalog** (every available integration in the catalog, regardless of connection status), not only integrations the user has already connected. The user SHALL be required to select at least 3 integrations before continuing. When Gmail was connected in the prior step, Gmail SHALL be treated as already part of the preferred set and SHALL NOT count toward the 3-selection minimum.

#### Scenario: Selection step appears after Gmail step

- **WHEN** the user reaches the point in onboarding immediately after the Gmail connection step
- **THEN** the integration-selection step is shown before onboarding processing begins

#### Scenario: Full catalog is browsable, not just connected integrations

- **WHEN** the user opens the integration selector during onboarding
- **AND** the user has connected only Gmail
- **THEN** every available integration in the supported catalog is searchable and selectable, including ones the user has not connected

#### Scenario: Minimum of 3 selections enforced

- **WHEN** the user has selected fewer than 3 integrations
- **THEN** the control to continue past the selection step is disabled
- **AND** when the user has selected 3 or more integrations, the user can continue

#### Scenario: Connected Gmail is included without counting toward the minimum

- **WHEN** the user connected Gmail and then selects 3 additional integrations
- **THEN** the preferred set submitted to the backend contains Gmail plus the 3 selected integrations

### Requirement: Selected integrations are submitted and persisted

The onboarding completion request SHALL carry the selected integration slugs, and the system SHALL persist them on the user's onboarding record so they are available to the asynchronous onboarding-intelligence job that generates workflows.

#### Scenario: Selected slugs are stored on completion

- **WHEN** the user completes onboarding having selected integrations
- **THEN** the onboarding completion payload includes the selected integration slugs
- **AND** the slugs are stored on the user's onboarding record before the onboarding-intelligence job runs

### Requirement: Onboarding workflow generation is anchored to selected integrations

The onboarding workflow generator SHALL pass the user's selected integrations (including Gmail when connected) into both the 4-workflow planning step and each per-workflow step-generation call, as the preferred integration set. The generated workflows SHALL be built around those integrations, and each created workflow SHALL persist the selected integrations as its preferred set.

#### Scenario: Planning prompt receives the selected integrations

- **WHEN** the onboarding-intelligence job plans the 4 workflows
- **THEN** the planning prompt is given the user's selected integrations as the integrations to build the workflows around

#### Scenario: Each onboarding workflow uses the selected integrations as its preferred set

- **WHEN** an individual onboarding workflow is created
- **THEN** its step generation is invoked with the selected integrations as the preferred set
- **AND** the persisted workflow records the selected integrations as its preferred set
