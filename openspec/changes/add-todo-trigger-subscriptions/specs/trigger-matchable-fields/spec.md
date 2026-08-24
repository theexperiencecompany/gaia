## ADDED Requirements

### Requirement: Matchable-fields catalog per trigger
The system SHALL maintain, per supported trigger, a curated list of matchable payload fields derived from the verified Composio payload schemas (`app/models/composio_schemas/`). Each entry SHALL carry the field name, type, description, and example value. The catalog SHALL cover at minimum gmail, slack, calendar, github, linear, notion, sheets, todoist, and asana triggers.

#### Scenario: Catalog reflects verified payloads
- **WHEN** a trigger's payload schema lists a field absent from the matchable catalog
- **THEN** the catalog documents why it was excluded (unreliable delivery or unsuitable for matching)

### Requirement: Subscription tool returns the schema the model will get
The agent-facing subscription tool SHALL return (and/or embed in its schema) the full matchable-fields catalog for the selected trigger — field names, types, descriptions, examples — so the model constructs conditions from known data rather than guessing. The tool description SHALL remain semantically rich enough for ChromaDB retrieval.

#### Scenario: Model requests available fields
- **WHEN** the agent asks what a trigger will deliver before subscribing
- **THEN** it receives the complete typed matchable-fields catalog for that trigger
