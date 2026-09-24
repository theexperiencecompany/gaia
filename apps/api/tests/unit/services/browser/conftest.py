"""Fixtures shared by the browser service tests.

flights_state lives here rather than in jev/conftest.py: pytest 9 drops a
subdirectory's conftest fixtures when a run lists jev/, then browser/, then jev/
files again, which is the order a mutation run can pass them in.
"""

import pytest

from tests.unit.services.browser.jev.conftest import (
    FakeAXNode,
    FakeAXProperty,
    FakeNode,
    make_state,
)


@pytest.fixture
def flights_state():
    """Return a tiny Google-Flights-like page: two comboboxes, a native select, a button."""
    return make_state(
        {
            17: FakeNode(
                "INPUT", {"role": "combobox", "placeholder": "Where from?", "value": "Zurich"}
            ),
            23: FakeNode("INPUT", {"role": "combobox", "placeholder": "Where to?"}),
            31: FakeNode(
                "SELECT",
                {"value": "economy"},
                ax_node=FakeAXNode(role="combobox", name="Cabin class"),
                children_nodes=[
                    FakeNode("OPTION", {"value": "economy"}, text="Economy"),
                    FakeNode("OPTION", {"value": "business"}, text="Business"),
                    FakeNode("OPTION", {"value": "first", "disabled": ""}, text="First"),
                ],
            ),
            40: FakeNode("BUTTON", text="Search", ax_node=FakeAXNode(role="button", name="Search")),
            41: FakeNode(
                "INPUT",
                {"type": "checkbox", "aria-label": "Nonstop only", "checked": ""},
                ax_node=FakeAXNode(role="checkbox", properties=[FakeAXProperty("checked", True)]),
            ),
        }
    )
