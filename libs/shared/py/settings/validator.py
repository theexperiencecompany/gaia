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
        Create a SettingsGroup representing a related set of configuration keys and their metadata.
        
        Parameters:
            name (str): Human-readable name of the group.
            keys (List[str]): Configuration keys that belong to this group.
            description (str): Short description of what the group enables.
            affected_features (str): Description of features affected when the group is missing.
            required_in_prod (bool): Whether this group is required in production (default True).
            all_required (bool): If True, all keys must be present; if False, at least one key must be present (default True).
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
        """
        Initialize validator state for settings validation.
        
        Attributes:
            groups (List[SettingsGroup]): Registered settings groups to validate.
            missing_groups (List[Tuple[SettingsGroup, List[str]]]): Collected groups that have missing keys and the list of those keys.
            show_warnings (bool): Whether validation results should be logged.
            is_production (bool): Whether the validator is running in production mode (affects logging severity and scope).
        """
        self.groups: List[SettingsGroup] = []
        self.missing_groups: List[Tuple[SettingsGroup, List[str]]] = []
        self.show_warnings: bool = True
        self.is_production: bool = True

    def register_group(self, group: SettingsGroup) -> None:
        """
        Register a SettingsGroup to be validated during settings checks.
        
        Parameters:
            group (SettingsGroup): The settings group to register.
        """
        self.groups.append(group)

    def configure(self, show_warnings: bool, is_production: bool) -> None:
        """
        Configure validator behavior and reset previously recorded validation state.
        
        Parameters:
            show_warnings (bool): If True, validation failures will be logged; otherwise logging is suppressed.
            is_production (bool): If True, validation messages are treated as production severity (affects log prefixing and whether groups required only in production are enforced).
        
        Side effects:
            Resets the internal list of recorded missing groups.
        """
        self.show_warnings = show_warnings
        self.is_production = is_production
        self.missing_groups = []

    def validate_settings(
        self, settings_obj: Any
    ) -> List[Tuple[SettingsGroup, List[str]]]:
        """
        Identify registered settings groups that lack required configuration values.
        
        Parameters:
            settings_obj (Any): An object whose attributes correspond to configuration keys to validate.
        
        Returns:
            List[Tuple[SettingsGroup, List[str]]]: A list of tuples for each group considered missing and the group's missing keys. A group is included if:
                - group.all_required is True and one or more of its keys are missing or None, or
                - group.all_required is False and all of its keys are missing or None.
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
        """
        Log warnings for any registered settings groups that have missing configuration.
        
        Only emits messages when warnings are enabled and there are missing groups. In production mode, skips groups that are not required in production; for groups that are logged the message is prefixed with "CRITICAL" when required in production and "WARNING" otherwise. Each message lists the group's name, the missing keys, and, if present, the affected features.
        """
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