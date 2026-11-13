"""Registration scope a trigger needs to know which resource to watch.

A subscription's payload conditions narrow which events matter; its scope decides
which resource Composio registers the webhook against. Gmail is account-level and
needs none; a github watch needs repos, a sheets watch a spreadsheet id. This
derives the scope fields from the trigger config models and marks which are
required, so the subscription surface can show them and validate them up front.
"""

from typing import NamedTuple, get_args, get_origin

from app.models.trigger_configs import BaseTriggerConfigData, TriggerConfigData

# Required scope per trigger, verified against Composio's live config schemas:
# Composio requires team_id (Linear) and spreadsheet_id (Sheets) even though our
# handlers do not gate them, so an unscoped watch fails only at registration.
REQUIRED_SCOPE: dict[str, frozenset[str]] = {
    "github_commit_event": frozenset({"repos"}),
    "github_pr_event": frozenset({"repos"}),
    "github_star_added": frozenset({"repos"}),
    "github_issue_added": frozenset({"repos"}),
    "notion_new_page_in_db": frozenset({"database_ids"}),
    "notion_page_updated": frozenset({"page_ids"}),
    "asana_task_trigger": frozenset({"project_gid"}),
    "linear_issue_created": frozenset({"team_id"}),
    "linear_issue_updated": frozenset({"team_id"}),
    "linear_comment_added": frozenset({"team_id"}),
    "google_sheets_new_row": frozenset({"spreadsheet_ids"}),
    "google_sheets_new_sheet": frozenset({"spreadsheet_ids"}),
}

_SCOPE_TYPE_LABELS: dict[object, str] = {int: "integer", bool: "true/false", str: "text"}


class ScopeField(NamedTuple):
    """One registration knob a trigger accepts, as the model should see it."""

    name: str
    type: str
    description: str
    required: bool


def _config_classes() -> dict[str, type[BaseTriggerConfigData]]:
    """Map each trigger name to the config class that owns it, from the union."""
    classes: dict[str, type[BaseTriggerConfigData]] = {}
    for member in get_args(get_args(TriggerConfigData)[0]):
        for field_name, field in member.model_fields.items():
            if field_name == "trigger_name":
                classes[field.default] = member
                break
    return classes


TRIGGER_CONFIG_CLASSES = _config_classes()


def _scope_type_label(annotation: object) -> str:
    if get_origin(annotation) in (list, tuple, set):
        return "list of text"
    return _SCOPE_TYPE_LABELS.get(annotation, "text")


def scope_fields_for(trigger_name: str) -> tuple[ScopeField, ...]:
    """Return the scope fields a trigger accepts, and which of them are required.

    Empty for account-level triggers (Gmail) that fire on the connected account
    itself; a per-resource trigger like github_pr_event returns its repos field,
    which registration needs or it matches no resource and never fires.
    """
    config_class = TRIGGER_CONFIG_CLASSES.get(trigger_name)
    if config_class is None:
        return ()
    required = REQUIRED_SCOPE.get(trigger_name, frozenset())
    return tuple(
        ScopeField(
            name=name,
            type=_scope_type_label(field.annotation),
            # Every config field carries a description; the "" only satisfies str | None.
            description=field.description or "",  # pragma: no mutate
            required=name in required,
        )
        for name, field in config_class.model_fields.items()
        if name != "trigger_name"
    )
