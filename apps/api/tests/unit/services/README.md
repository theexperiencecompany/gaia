# Unit Tests — Services

Tests for the business logic layer (`app/services/`). Each service sits between the API layer and the database; these tests verify the logic that transforms, validates, and orchestrates data without touching a real database.

Database clients are replaced with mocks so tests focus on what data the service constructs and which database operations it calls, not on database behaviour itself. Error paths (failed inserts, missing records, malformed responses) are also covered by configuring mocks to raise or return edge-case values.

Services covered include conversations, chat, memory, mail, user management, and workflow execution/validation.
