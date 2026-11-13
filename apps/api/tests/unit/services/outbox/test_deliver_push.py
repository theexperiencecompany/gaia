"""What a lock screen may show of an approval ask."""

from types import SimpleNamespace

import pytest

from app.services.outbox.deliver import _push_body
from app.services.outbox.judge_models import Sensitivity
from app.services.outbox.prerendered import PrerenderedKind, prerendered_text

ASK = SimpleNamespace(parts=["Send the deck to Bob? Reply yes or no."])


def _item(sensitivity: Sensitivity | None, *, judged: bool = True) -> SimpleNamespace:
    judgement = (
        None
        if sensitivity is None
        else SimpleNamespace(sensitivity=sensitivity, verdict=object() if judged else None)
    )
    return SimpleNamespace(judgement=judgement)


@pytest.mark.parametrize("sensitivity", [Sensitivity.NONE, Sensitivity.PERSONAL])
def test_an_ask_the_judge_found_ordinary_previews_its_first_bubble(
    sensitivity: Sensitivity,
) -> None:
    assert _push_body([_item(sensitivity)], ASK, "en") == ASK.parts[0]


@pytest.mark.parametrize("item", [_item(None), _item(Sensitivity.NONE, judged=False)])
def test_an_ask_nobody_judged_shows_only_that_something_needs_attention(
    item: SimpleNamespace,
) -> None:
    body = _push_body([item], ASK, "en")

    assert body == prerendered_text(PrerenderedKind.GENERIC_PREVIEW, "en")
    assert "Bob" not in body


@pytest.mark.parametrize(
    "sensitivity",
    [Sensitivity.HEALTH, Sensitivity.FINANCE, Sensitivity.CREDENTIALS, Sensitivity.SOCIAL_PRIVATE],
)
def test_a_private_ask_shows_only_that_something_needs_attention(sensitivity: Sensitivity) -> None:
    body = _push_body([_item(sensitivity)], ASK, "en")

    assert body == prerendered_text(PrerenderedKind.GENERIC_PREVIEW, "en")
    assert "Bob" not in body
