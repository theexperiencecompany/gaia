"""adjust_attention: what the user says in conversation becomes the settings the Rails read."""

from datetime import UTC, datetime, time, timedelta
from unittest.mock import AsyncMock, patch

from app.agents.tools.attention_tool import adjust_attention
from app.models.attention_settings_models import AttentionSettings
from app.models.quiet_hours_models import DEFAULT_QUIET_HOURS

USER = "6812f0b3c9a14e2b7d5a91cc"
MODULE = "app.agents.tools.attention_tool"
NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
CONFIG = {"configurable": {"user_id": USER}}


async def _adjust(current: AttentionSettings, **args: object) -> tuple[str, AsyncMock]:
    save = AsyncMock()
    with (
        patch(f"{MODULE}.get_attention_settings", AsyncMock(return_value=current)),
        patch(f"{MODULE}.set_attention_settings", save),
        patch(f"{MODULE}.clock.now", return_value=NOW),
        patch(f"{MODULE}.get_quiet_hours", AsyncMock(return_value=DEFAULT_QUIET_HOURS)),
    ):
        reply = await adjust_attention.ainvoke(args, config=CONFIG)
    return reply, save


async def test_stop_messaging_me_unless_urgent_sets_the_budget_to_zero() -> None:
    _, save = await _adjust(AttentionSettings(), max_unsolicited_per_day=0)

    assert save.await_args.args[1].max_unsolicited_per_day == 0


async def test_do_not_disturb_runs_for_the_hours_asked_and_zero_ends_it() -> None:
    _, save = await _adjust(AttentionSettings(), do_not_disturb_hours=2)
    assert save.await_args.args[1].dnd_until == NOW + timedelta(hours=2)

    ending = AttentionSettings(dnd_until=NOW + timedelta(hours=1))
    _, save = await _adjust(ending, do_not_disturb_hours=0)
    assert save.await_args.args[1].dnd_until is None


async def test_rules_are_added_without_duplicates_and_removed_by_their_words() -> None:
    current = AttentionSettings(rules=["always tell me about mom", "no work on weekends"])

    _, save = await _adjust(
        current,
        add_rules=["always tell me about mom", "keep me posted on the visa"],
        remove_rules=["no work on weekends"],
    )

    assert save.await_args.args[1].rules == [
        "always tell me about mom",
        "keep me posted on the visa",
    ]


async def test_check_in_times_replace_the_old_ones() -> None:
    _, save = await _adjust(AttentionSettings(), checkin_times=["09:00", "20:30"])

    assert save.await_args.args[1].checkin_times == [time(9, 0), time(20, 30)]


async def test_a_check_in_time_that_is_not_a_time_changes_nothing_and_says_why() -> None:
    reply, save = await _adjust(AttentionSettings(), checkin_times=["nine"])

    save.assert_not_awaited()
    assert reply.startswith("Not changed")
