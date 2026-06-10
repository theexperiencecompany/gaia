"""Validation for integration publishing."""

from app.services.integrations.profanity import contains_profanity


class PublishIntegrationValidator:
    """Validates integration content before publishing."""

    MIN_NAME_LENGTH = 3
    MAX_NAME_LENGTH = 100
    MAX_DESCRIPTION_LENGTH = 500
    MIN_TOOLS = 1

    @classmethod
    async def validate_for_publish(
        cls,
        name: str,
        description: str | None,
        tools: list,
    ) -> list[str]:
        """Validate integration content for publishing. Returns error messages (empty if valid)."""
        # Order matches the pre-refactor sequence so any caller that surfaces
        # errors positionally keeps the same first / second / … messages.
        return [
            *cls._validate_name(name),
            *await cls._validate_profanity(name, description),
            *cls._validate_description(description),
            *cls._validate_tools(tools),
        ]

    @classmethod
    def _validate_name(cls, name: str) -> list[str]:
        if not name or len(name) < cls.MIN_NAME_LENGTH:
            return [f"Name must be at least {cls.MIN_NAME_LENGTH} characters"]
        if len(name) > cls.MAX_NAME_LENGTH:
            return [f"Name must be at most {cls.MAX_NAME_LENGTH} characters"]
        return []

    @classmethod
    def _validate_description(cls, description: str | None) -> list[str]:
        if description and len(description) > cls.MAX_DESCRIPTION_LENGTH:
            return [f"Description must be at most {cls.MAX_DESCRIPTION_LENGTH} characters"]
        return []

    @staticmethod
    async def _validate_profanity(name: str, description: str | None) -> list[str]:
        # One LLM call covers all user-facing fields.
        if await contains_profanity(name=name, description=description):
            return ["Content contains profanity"]
        return []

    @classmethod
    def _validate_tools(cls, tools: list) -> list[str]:
        if not tools or len(tools) < cls.MIN_TOOLS:
            return ["Integration must have at least one tool to be published"]
        return []
