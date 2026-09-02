## ADDED Requirements

### Requirement: Matchable-fields catalog per trigger
The system SHALL maintain, per supported trigger, a curated list of matchable payload fields derived from the verified Composio payload schemas (`app/models/composio_schemas/`). Each entry SHALL carry the field name, type, description, and example value.

The catalog SHALL cover every GAIA-facing trigger name in the `WorkflowTriggerSchema` catalog — gmail, slack, google calendar, google docs, google sheets, github, linear, notion, todoist, and asana. A trigger that is offered for workflows but absent from the catalog is unsubscribable for todos, so any omission SHALL be a documented decision rather than an oversight.

#### Scenario: Catalog reflects verified payloads
- **WHEN** a trigger's payload schema lists a field absent from the matchable catalog
- **THEN** the catalog documents why it was excluded (unreliable delivery or unsuitable for matching)

#### Scenario: Every offered trigger is covered
- **WHEN** the catalog is checked against the trigger names published by the `WorkflowTriggerSchema` catalog
- **THEN** every trigger name has either matchable fields or a recorded exclusion reason

### Requirement: Subscription tool returns the schema the model will get
The agent-facing subscription tool SHALL return the full matchable-fields catalog for the selected trigger — field names, types, descriptions, examples — so the model constructs conditions from known data rather than guessing.

The subscription tools SHALL be loaded alongside the existing tracked-todo tools rather than left to semantic retrieval, so the model can see them at the moment a reply-watching todo is being created. The field catalog SHALL be returned by the call rather than embedded in the tool description, keeping the always-loaded prompt cost bounded.

#### Scenario: Model requests available fields
- **WHEN** the agent asks what a trigger will deliver before subscribing
- **THEN** it receives the complete typed matchable-fields catalog for that trigger

#### Scenario: Tool is available without retrieval
- **WHEN** the agent is working on a tracked todo and has not searched for trigger tooling
- **THEN** the subscription tools are already in its tool set, as the other tracked-todo tools are
