"""Unit tests for app.services.onboarding.writing_style_service.

The sent folder is read through ``search_messages`` and the style is learned
by one structured LLM call; both seams are faked, everything between them
(sample filtering, thresholds, the profile shape) runs for real.
"""

from unittest.mock import AsyncMock, patch

from app.agents.prompts.onboarding_prompts import WRITING_STYLE_PROMPT
from app.constants.email import SENT_EMAIL_QUERY
from app.models.mail_models import GmailMessagesResponse
from app.models.onboarding_models import (
    WritingStyleExampleBlocks,
    WritingStyleOutput,
    WritingStyleProfile,
)
from app.services.onboarding.writing_style_service import learn_writing_style

MODULE = "app.services.onboarding.writing_style_service"
USER = "507f1f77bcf86cd799439011"


def _sent(bodies: list[str], subjects: list[str] | None = None) -> GmailMessagesResponse:
    subjects = subjects or ["Re: plan"] * len(bodies)
    return GmailMessagesResponse.model_validate(
        {
            "messages": [
                {"id": f"m{i}", "subject": subject, "body": body}
                for i, (body, subject) in enumerate(zip(bodies, subjects))
            ]
        }
    )


def _llm_output() -> WritingStyleOutput:
    return WritingStyleOutput(
        summary="Terse and warm.",
        example=WritingStyleExampleBlocks(greeting="Hi,", body=["Sounds good."], signoff="Best"),
    )


LONG_BODY = "Thanks for the update, I will review it tomorrow morning."


class TestLearnWritingStyle:
    async def test_sent_folder_is_read_and_the_learned_profile_is_returned(self) -> None:
        search = AsyncMock(return_value=_sent([LONG_BODY] * 5))
        llm = AsyncMock(return_value=_llm_output())
        with patch(f"{MODULE}.search_messages", search), patch(f"{MODULE}.ainvoke_structured", llm):
            profile = await learn_writing_style(USER, profession="founder")

        search.assert_awaited_once_with(user_id=USER, query=SENT_EMAIL_QUERY, max_results=50)
        assert profile == WritingStyleProfile(
            summary="Terse and warm.",
            example=WritingStyleExampleBlocks(
                greeting="Hi,", body=["Sounds good."], signoff="Best"
            ),
        )

    async def test_prompt_carries_the_profession_and_the_usable_sent_bodies(self) -> None:
        # Short bodies and auto-replies are not the user's voice: neither reaches
        # the model, and the samples that do are joined with the separator.
        bodies = [LONG_BODY + f" ({i})" for i in range(5)] + ["ok", LONG_BODY + " (auto)"]
        subjects = ["Re: plan"] * 6 + ["Out of Office: away"]
        llm = AsyncMock(return_value=_llm_output())
        with (
            patch(f"{MODULE}.search_messages", AsyncMock(return_value=_sent(bodies, subjects))),
            patch(f"{MODULE}.ainvoke_structured", llm),
        ):
            await learn_writing_style(USER, profession="lawyer")

        assert llm.await_args.args == (
            WritingStyleOutput,
            WRITING_STYLE_PROMPT.format(
                profession="lawyer",
                email_samples="\n---\n".join(LONG_BODY + f" ({i})" for i in range(5)),
            ),
        )
        assert llm.await_args.kwargs == {
            "label": "onboarding_writing_style",
            "config": {"configurable": {"user_id": USER}},
        }

    async def test_status_callback_reports_the_sent_count(self) -> None:
        statuses: list[str] = []

        async def on_status(text: str) -> None:
            statuses.append(text)

        with (
            patch(f"{MODULE}.search_messages", AsyncMock(return_value=_sent([LONG_BODY] * 5))),
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=_llm_output())),
        ):
            await learn_writing_style(USER, on_status=on_status)

        assert statuses == [
            "Reading your sent folder",
            "Found 5 sent emails",
            "Analyzing tone and phrasing",
        ]

    async def test_one_sent_email_is_singular_in_the_status(self) -> None:
        statuses: list[str] = []

        async def on_status(text: str) -> None:
            statuses.append(text)

        with patch(f"{MODULE}.search_messages", AsyncMock(return_value=_sent([LONG_BODY]))):
            await learn_writing_style(USER, on_status=on_status)

        assert statuses[1] == "Found 1 sent email"

    async def test_too_few_sent_emails_skips_the_model(self) -> None:
        llm = AsyncMock()
        with (
            patch(f"{MODULE}.search_messages", AsyncMock(return_value=_sent([LONG_BODY] * 4))),
            patch(f"{MODULE}.ainvoke_structured", llm),
        ):
            assert await learn_writing_style(USER) is None

        llm.assert_not_awaited()

    async def test_too_few_usable_samples_skips_the_model(self) -> None:
        # Five emails arrive but only four have a body worth learning from.
        llm = AsyncMock()
        sent = _sent([LONG_BODY] * 4 + ["ty"])
        with (
            patch(f"{MODULE}.search_messages", AsyncMock(return_value=sent)),
            patch(f"{MODULE}.ainvoke_structured", llm),
        ):
            assert await learn_writing_style(USER) is None

        llm.assert_not_awaited()

    async def test_at_most_thirty_samples_reach_the_model(self) -> None:
        bodies = [LONG_BODY + f" ({i})" for i in range(40)]
        llm = AsyncMock(return_value=_llm_output())
        with (
            patch(f"{MODULE}.search_messages", AsyncMock(return_value=_sent(bodies))),
            patch(f"{MODULE}.ainvoke_structured", llm),
        ):
            await learn_writing_style(USER)

        prompt: str = llm.await_args.args[1]
        assert "(29)" in prompt
        assert "(30)" not in prompt

    async def test_a_failing_sent_folder_read_yields_none(self) -> None:
        with patch(f"{MODULE}.search_messages", AsyncMock(side_effect=RuntimeError("gmail"))):
            assert await learn_writing_style(USER) is None

    async def test_a_failing_model_call_yields_none(self) -> None:
        with (
            patch(f"{MODULE}.search_messages", AsyncMock(return_value=_sent([LONG_BODY] * 5))),
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(side_effect=RuntimeError("llm"))),
        ):
            assert await learn_writing_style(USER) is None
