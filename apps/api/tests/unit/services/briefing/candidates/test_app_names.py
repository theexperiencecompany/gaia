"""An integration's display name and the id behind a display name."""

import pytest

from app.services.briefing.candidates.app_names import integration_id_named, integration_name

pytestmark = pytest.mark.unit


class TestIntegrationNames:
    def test_a_name_maps_back_to_the_id_it_came_from(self) -> None:
        assert integration_id_named(integration_name("gmail")) == "gmail"

    def test_a_name_no_integration_carries_is_none(self) -> None:
        assert integration_id_named("No Such App") is None

    def test_an_id_the_catalog_lacks_raises(self) -> None:
        with pytest.raises(KeyError, match="no integration 'nope' in the catalog"):
            integration_name("nope")
