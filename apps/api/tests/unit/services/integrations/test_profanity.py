"""contains_profanity: one LLM moderation verdict, the offline wordlist whenever it can't answer."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.llm.exceptions import LLMNotConfiguredError
from app.services.integrations import profanity
from app.services.integrations.profanity import contains_profanity

pytestmark = pytest.mark.unit

_MOD = "app.services.integrations.profanity"


def _moderator(*, is_offensive: bool | None = None, raises: BaseException | None = None):
    """Patch the model seam with one that answers is_offensive, or raises."""
    model = MagicMock()
    invoke = AsyncMock()
    if raises is not None:
        invoke.side_effect = raises
    else:
        invoke.return_value = profanity._ModerationResult(is_offensive=bool(is_offensive))
    return (
        patch(f"{_MOD}.resolve_model", return_value=model),
        patch(f"{_MOD}.ainvoke_llm", invoke),
        invoke,
    )


class TestTheModelsVerdictDecides:
    async def test_text_the_model_flags_is_offensive_though_no_listed_word_appears(self) -> None:
        model_patch, invoke_patch, _ = _moderator(is_offensive=True)
        with model_patch, invoke_patch:
            assert await contains_profanity(name="Totally Polite Tool") is True

    async def test_text_the_model_clears_passes_even_if_the_wordlist_would_flag_it(self) -> None:
        model_patch, invoke_patch, _ = _moderator(is_offensive=False)
        with model_patch, invoke_patch:
            assert await contains_profanity(name="Scunthorpe shit tracker") is False

    async def test_every_field_goes_to_the_model_as_json_data_in_one_call(self) -> None:
        model_patch, invoke_patch, invoke = _moderator(is_offensive=False)
        with model_patch, invoke_patch:
            await contains_profanity(name="My Tool", description="Does things", blank="  ")

        invoke.assert_awaited_once()
        prompt = invoke.await_args.args[1][0].content
        assert json.dumps({"name": "My Tool", "description": "Does things"}) in prompt


class TestTheWordlistAnswersWhenTheModelCannot:
    async def test_no_non_blank_field_is_clean_without_asking_the_model(self) -> None:
        model_patch, invoke_patch, invoke = _moderator(is_offensive=True)
        with model_patch, invoke_patch:
            assert await contains_profanity(name="", description="   ", icon=None) is False
        invoke.assert_not_awaited()

    @pytest.mark.parametrize(("text", "expected"), [("sh1t happens", True), ("A document", False)])
    async def test_an_unconfigured_model_falls_back_to_the_wordlist(
        self, text: str, expected: bool
    ) -> None:
        with patch(f"{_MOD}.resolve_model", side_effect=LLMNotConfiguredError("no key")):
            assert await contains_profanity(description=text) is expected

    @pytest.mark.parametrize("failure", [TimeoutError(), RuntimeError("provider down")])
    async def test_a_model_that_times_out_or_fails_falls_back_to_the_wordlist(
        self, failure: BaseException
    ) -> None:
        model_patch, invoke_patch, _ = _moderator(raises=failure)
        with model_patch, invoke_patch:
            assert await contains_profanity(name="f.u.c.k") is True
            assert await contains_profanity(name="Falcon") is False
