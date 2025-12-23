"""
Settings validator for GAIA applications.

Validates presence of env-backed settings, grouped by feature.
Makes missing config obvious with actionable logs.
"""

from typing import Any, List, Tuple

from shared.py.logging import get_contextual_logger

logger = get_contextual_logger("config")


class SettingsGroup:
    """Represents a group of related settings."""

    def __init__(
        self,
        name: str,
        keys: List[str],
        description: str,
        affected_features: str,
        required_in_prod: bool = True,
        all_required: bool = True,
    ):
        """
        Initialize a settings group.

        Args:
            name: The name of the settings group
            keys: List of configuration keys in this group
            description: Description of what this group enables
            affected_features: Description of features affected if missing
            required_in_prod: Whether required in production
            all_required: Whether all keys are required (True) or any one is sufficient (False)
        """
        self.name = name
        self.keys = keys
        self.description = description
        self.affected_features = affected_features
        self.required_in_prod = required_in_prod
        self.all_required = all_required


class SettingsValidator:
    """Validates settings against registered groups."""

    def __init__(self) -> None:
        self.groups: List[SettingsGroup] = []
        self.missing_groups: List[Tuple[SettingsGroup, List[str]]] = []
        self.show_warnings: bool = True
        self.is_production: bool = True

    def register_group(self, group: SettingsGroup) -> None:
        """Register a settings group for validation."""
        self.groups.append(group)

    def configure(self, show_warnings: bool, is_production: bool) -> None:
        """Configure the validator."""
        self.show_warnings = show_warnings
        self.is_production = is_production
        self.missing_groups = []

    def validate_settings(
        self, settings_obj: Any
    ) -> List[Tuple[SettingsGroup, List[str]]]:
        """
        Validate settings against registered groups.

        Returns:
            List of tuples with missing groups and their missing keys
        """
        self.missing_groups = []

        for group in self.groups:
            missing_keys = []

            for key in group.keys:
                if not hasattr(settings_obj, key) or getattr(settings_obj, key) is None:
                    missing_keys.append(key)

            if group.all_required and missing_keys:
                self.missing_groups.append((group, missing_keys))
            elif not group.all_required and len(missing_keys) == len(group.keys):
                self.missing_groups.append((group, missing_keys))

        return self.missing_groups

    def log_validation_results(self) -> None:
        """Log validation results with warnings for missing configuration."""
        if not self.show_warnings or not self.missing_groups:
            return

        for group, missing_keys in self.missing_groups:
            if self.is_production and not group.required_in_prod:
                continue

            prefix = (
                "CRITICAL"
                if self.is_production and group.required_in_prod
                else "WARNING"
            )

            warning_msg = (
                f"{prefix}: Missing configuration for {group.name} - "
                f"Missing keys: {', '.join(missing_keys)}"
            )

            if group.affected_features:
                warning_msg += f"\n  → Affected: {group.affected_features}"

            logger.warning(warning_msg)


__all__ = [
    "SettingsGroup",
    "SettingsValidator",
]
