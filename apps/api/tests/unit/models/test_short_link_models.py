"""LinkSettingsUpdate: an omitted field keeps its value; a link's access can never be cleared."""

from pydantic import ValidationError
import pytest

from app.models.short_link_models import LinkAccess, LinkSettingsUpdate


def test_an_explicit_null_access_is_refused() -> None:
    with pytest.raises(ValidationError) as raised:
        LinkSettingsUpdate.model_validate({"access": None})

    [error] = raised.value.errors()
    assert (error["loc"], error["msg"]) == (
        ("access",),
        "Value error, access must be a level; omit it to keep the current one",
    )


def test_an_omitted_access_is_left_unset() -> None:
    change = LinkSettingsUpdate.model_validate({"grantees": []})

    assert (change.access, change.model_fields_set) == (None, {"grantees"})


def test_a_level_is_kept_as_given() -> None:
    assert LinkSettingsUpdate.model_validate({"access": "people"}).access is LinkAccess.PEOPLE
