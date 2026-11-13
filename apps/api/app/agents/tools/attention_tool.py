"""The comms tool that changes how much GAIA tells the user unprompted: quiet hours, DND, budget, check-ins, rules."""

from datetime import timedelta

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.tools.core.mutations import define_mutation_tool
from app.models.attention_settings_models import AttentionSettings
from app.models.quiet_hours_models import QuietHours
from app.services.attention_settings_service import get_attention_settings, set_attention_settings
from app.services.user_service import get_quiet_hours, set_quiet_hours
from app.utils import clock


class AdjustAttentionArgs(BaseModel):
    """What the user asked to change; whatever is left out stays as it is."""

    model_config = ConfigDict(extra="forbid")

    max_unsolicited_per_day: int | None = Field(
        default=None,
        description="How many updates GAIA may send unprompted per day; 0 means only at check-ins and when asked.",
    )
    quiet_hours_enabled: bool | None = Field(
        default=None,
        description="False lets GAIA message at night; True turns quiet hours back on.",
    )
    quiet_hours_start: int | None = Field(
        default=None, description="Local hour (0-23) quiet hours start."
    )
    quiet_hours_end: int | None = Field(
        default=None, description="Local hour (0-23) quiet hours end."
    )
    do_not_disturb_hours: float | None = Field(
        default=None,
        description="Hours from now with nothing but security notices and the user's own timings; 0 ends it.",
    )
    checkin_times: list[str] | None = Field(
        default=None, description="Replaces the daily check-in times, each as local 'HH:MM'."
    )
    add_rules: list[str] | None = Field(
        default=None,
        description=(
            "The user's own words about what to tell them, kept as they said it "
            "('nothing about work on weekends unless urgent', 'always tell me about mom', "
            "'keep me posted on the visa')."
        ),
    )
    remove_rules: list[str] | None = Field(
        default=None, description="Rules to drop, exactly as listed before."
    )


def _apply_rules(current: list[str], add: list[str] | None, remove: list[str] | None) -> list[str]:
    kept = [rule for rule in current if rule not in (remove or [])]
    return [*kept, *(rule for rule in (add or []) if rule not in kept)]


def _attention_changes(args: AdjustAttentionArgs, current: AttentionSettings) -> dict[str, object]:
    changes: dict[str, object] = {}
    if args.max_unsolicited_per_day is not None:
        changes["max_unsolicited_per_day"] = args.max_unsolicited_per_day
    if args.do_not_disturb_hours is not None:
        changes["dnd_until"] = (
            clock.now() + timedelta(hours=args.do_not_disturb_hours)
            if args.do_not_disturb_hours > 0
            else None
        )
    if args.checkin_times is not None:
        changes["checkin_times"] = args.checkin_times
    if args.add_rules or args.remove_rules:
        changes["rules"] = _apply_rules(current.rules, args.add_rules, args.remove_rules)
    return changes


async def _adjust_attention(user_id: str, **fields: object) -> str:
    args = AdjustAttentionArgs.model_validate(fields)
    current = await get_attention_settings(user_id)
    hours = await get_quiet_hours(user_id)
    changes = _attention_changes(args, current)
    quiet_changes = {
        "enabled": args.quiet_hours_enabled,
        "start_hour": args.quiet_hours_start,
        "end_hour": args.quiet_hours_end,
    }
    try:
        updated = AttentionSettings.model_validate({**current.model_dump(mode="json"), **changes})
        quiet = QuietHours.model_validate(
            {
                **hours.model_dump(mode="json"),
                **{key: value for key, value in quiet_changes.items() if value is not None},
            }
        )
    except ValidationError as e:
        return f"Not changed: {e}"
    if changes:
        await set_attention_settings(user_id, updated)
    if quiet != hours:
        await set_quiet_hours(user_id, quiet)
    return "Updated. The user can see and change this in settings."


adjust_attention = define_mutation_tool(
    name="adjust_attention",
    area="attention",
    description=(
        "Change how much GAIA tells the user on its own, when they ask for it in conversation: "
        "'don't message me at night', 'stop messaging me unless it's urgent', 'you can text me at "
        "night', 'leave me alone for 2 hours', 'check in with me at 9', or a standing preference "
        "about what to tell them. Confirm the change in one line."
    ),
    args_model=AdjustAttentionArgs,
    apply=_adjust_attention,
)
