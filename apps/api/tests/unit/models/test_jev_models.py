"""JEV Decisions wire models (app/models/jev_models.py): the refusals every JEV caller relies on."""

import pytest

from app.models.jev_models import JevDecisionsResponse


def _body(
    answer: dict[str, object], usage: dict[str, object] | None = None
) -> JevDecisionsResponse:
    return JevDecisionsResponse.model_validate({"answers": {"q": answer}, "usage": usage})


class TestChoice:
    def test_an_allowed_choice_is_returned(self) -> None:
        body = _body({"type": "choice", "choice": "yes", "confidence": 0.9})
        assert body.choice("q", ("yes", "no")).confidence == 0.9

    def test_an_unknown_choice_is_refused_without_a_label_by_default(self) -> None:
        with pytest.raises(ValueError) as caught:
            _body({"type": "choice", "choice": "maybe"}).choice("q", ("yes",))
        assert str(caught.value) == "unknown JEV choice: 'maybe'"

    def test_the_label_names_which_question_refused(self) -> None:
        with pytest.raises(ValueError) as caught:
            _body({"type": "choice", "choice": "maybe"}).choice("q", ("yes",), label="reply ")
        assert str(caught.value) == "unknown JEV reply choice: 'maybe'"

    def test_a_non_choice_answer_is_refused_in_at_most_300_characters(self) -> None:
        body = _body({"type": "score", "choice": "x" * 400})
        with pytest.raises(ValueError) as caught:
            body.choice("q", ("yes",))
        assert str(caught.value).startswith("non-choice JEV answer: ")
        assert len(str(caught.value)) == 300

    def test_a_missing_question_is_refused_by_name(self) -> None:
        with pytest.raises(ValueError, match="^JEV answer missing for question 'other'$"):
            _body({"type": "choice", "choice": "yes"}).choice("other", ("yes",))


class TestTokens:
    def test_reported_usage_is_returned(self) -> None:
        body = _body({"choice": "yes"}, {"input_tokens": 12, "output_tokens": 3})
        assert body.tokens() == (12, 3)

    @pytest.mark.parametrize("usage", [None, {}, {"input_tokens": None, "output_tokens": None}])
    def test_absent_usage_reads_as_zero(self, usage: dict[str, object] | None) -> None:
        assert _body({"choice": "yes"}, usage).tokens() == (0, 0)
