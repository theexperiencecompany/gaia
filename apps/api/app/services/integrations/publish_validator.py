"""Validation for integration publishing."""

from typing import List


# Blocked keywords for spam prevention
BLOCKED_KEYWORDS = [
    "free money",
    "hack",
    "crack",
    "keygen",
    "warez",
    "xxx",
    "porn",
    "casino",
    "gambling",
]


class PublishIntegrationValidator:
    """Validates integration content before publishing."""

    MIN_NAME_LENGTH = 3
    MAX_NAME_LENGTH = 100
    MAX_DESCRIPTION_LENGTH = 500
    MIN_TOOLS = 1

    @classmethod
    def validate_for_publish(
        cls,
        name: str,
        description: str | None,
        tools: list,
    ) -> List[str]:
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

        # Check for blocked keywords
        name_lower = name.lower()
        desc_lower = (description or "").lower()
        for keyword in BLOCKED_KEYWORDS:
            if keyword in name_lower or keyword in desc_lower:
                errors.append("Content contains blocked keywords")
                break

        # Description length
        if description and len(description) > cls.MAX_DESCRIPTION_LENGTH:
            errors.append(
                f"Description must be at most {cls.MAX_DESCRIPTION_LENGTH} characters"
            )

        # Tools requirement
        if not tools or len(tools) < cls.MIN_TOOLS:
            errors.append("Integration must have at least one tool to be published")

        return errors
