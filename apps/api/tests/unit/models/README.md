# Unit Tests — Models

Tests for Pydantic schema validation rules across the API's request/response models. These tests confirm that valid payloads are accepted, required fields are enforced, field-level validators reject bad values, and serialisation produces the expected shape.

No database or network access is required — these are pure data-structure tests.
