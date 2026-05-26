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
        """
        Validate integration content for publishing.

        Args:
            name: Integration name
            description: Integration description
            tools: List of tools

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # Name validation
        if not name or len(name) < cls.MIN_NAME_LENGTH:
            errors.append(f"Name must be at least {cls.MIN_NAME_LENGTH} characters")
        elif len(name) > cls.MAX_NAME_LENGTH:
            errors.append(f"Name must be at most {cls.MAX_NAME_LENGTH} characters")

        # One LLM call covers all user-facing fields.
        if await contains_profanity(name=name, description=description):
            errors.append("Content contains profanity")

        # Description length
        if description and len(description) > cls.MAX_DESCRIPTION_LENGTH:
            errors.append(f"Description must be at most {cls.MAX_DESCRIPTION_LENGTH} characters")

        # Tools requirement
        if not tools or len(tools) < cls.MIN_TOOLS:
            errors.append("Integration must have at least one tool to be published")

        return errors
