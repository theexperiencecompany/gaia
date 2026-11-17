"""The analytics catalog's closed vocabularies name exactly the app's own enums' values."""

from enum import StrEnum
from typing import get_args

import pytest

from app.constants.briefing import BriefingFrequency
from app.constants.workflows import WorkflowDelivery
from shared.py.analytics.catalog.settings import BriefingFrequencyName
from shared.py.analytics.catalog.workflows import WorkflowDeliveryMode


@pytest.mark.parametrize(
    ("catalog", "registry"),
    [(WorkflowDeliveryMode, WorkflowDelivery), (BriefingFrequencyName, BriefingFrequency)],
    ids=["delivery", "frequency"],
)
def test_the_catalog_names_every_value_and_nothing_else(
    catalog: object, registry: type[StrEnum]
) -> None:
    assert set(get_args(catalog)) == {member.value for member in registry}
