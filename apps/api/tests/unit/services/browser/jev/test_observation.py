"""The element table Jev decides over, built from Browser-Use's selector map."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.constants.browser import JEV_MAX_ELEMENTS, JevOperation
from app.constants.log_tags import LogTag
from app.services.browser.jev import observation as observation_mod
from app.services.browser.jev.live_values import LiveValues
from app.services.browser.jev.observation import JevElement, observe
from app.services.browser.jev.viewport import ViewportBox, ViewportRead

from .conftest import FakeAXNode, FakeAXProperty, FakeNode, make_state

pytestmark = pytest.mark.unit


def test_elements_are_renumbered_in_order_and_keep_their_browser_index(flights_state) -> None:
    observation = observe(flights_state)

    assert [e.index for e in observation.elements] == [1, 2, 3, 4, 5]
    assert [e.browser_index for e in observation.elements] == [17, 23, 31, 40, 41]
    assert observation.url == "https://x"
    assert observation.title == "X"


def test_a_text_field_offers_click_and_type_and_carries_its_value(flights_state) -> None:
    origin, destination = observe(flights_state).elements[:2]

    assert origin.label == "Zurich"  # the current value is what Browser-Use shows too
    assert origin.value == "Zurich"
    assert origin.operations == (JevOperation.CLICK, JevOperation.TYPE_TEXT)
    assert destination.label == "Where to?"
    assert destination.value == ""
    assert destination.role == "combobox"


def test_a_native_select_offers_select_with_its_enabled_options(flights_state) -> None:
    cabin = observe(flights_state).elements[2]

    assert cabin.operations == (JevOperation.CLICK, JevOperation.SELECT)
    assert [(o.target, o.label, o.value) for o in cabin.options] == [
        ("3:1", "Economy", "economy"),
        ("3:2", "Business", "business"),
    ]
    assert cabin.value == "Economy"
    assert cabin.state_entry()["options"] == [
        {"index": "3:1", "label": "Economy", "value": "economy"},
        {"index": "3:2", "label": "Business", "value": "business"},
    ]


def test_a_button_is_click_only_and_named_by_its_accessible_name(flights_state) -> None:
    search = observe(flights_state).elements[3]

    assert search.operations == (JevOperation.CLICK,)
    assert search.label == "Search"
    assert search.role == "button"
    assert "value" not in search.state_entry()


def test_a_checkbox_reports_its_checked_state(flights_state) -> None:
    nonstop = observe(flights_state).elements[4]

    assert nonstop.operations == (JevOperation.CLICK,)
    assert nonstop.checked is True
    assert nonstop.criterion() == {
        "element": "[5] Nonstop only",
        "current_value": "",
        "role": "checkbox",
        "checked": True,
    }


def test_targets_group_elements_per_operation(flights_state) -> None:
    observation = observe(flights_state)

    assert set(observation.targets(JevOperation.CLICK)) == {"1", "2", "3", "4", "5"}
    assert set(observation.targets(JevOperation.TYPE_TEXT)) == {"1", "2"}
    assert set(observation.targets(JevOperation.SELECT)) == {"3:1", "3:2"}
    element, option = observation.targets(JevOperation.SELECT)["3:2"]
    assert (element.index, option.label) == (3, "Business")


@pytest.mark.parametrize(
    "attributes",
    [
        {"type": "submit", "value": "Go"},
        {"type": "checkbox", "aria-label": "x"},
        {"readonly": "", "placeholder": "Date"},
        {"aria-readonly": "true", "placeholder": "Date"},
    ],
)
def test_inputs_that_cannot_take_text_do_not_offer_type_text(attributes) -> None:
    (element,) = observe(make_state({1: FakeNode("INPUT", attributes)})).elements

    assert JevOperation.TYPE_TEXT not in element.operations


def test_contenteditable_and_textarea_offer_type_text() -> None:
    state = make_state(
        {
            1: FakeNode("DIV", {"contenteditable": "true", "aria-label": "Message"}),
            2: FakeNode("TEXTAREA", {"placeholder": "Notes"}),
        }
    )

    assert all(JevOperation.TYPE_TEXT in e.operations for e in observe(state).elements)


def test_an_unlabelled_non_field_element_is_dropped() -> None:
    state = make_state({1: FakeNode("DIV"), 2: FakeNode("INPUT", {"placeholder": "q"})})

    assert [e.browser_index for e in observe(state).elements] == [2]


def test_a_disabled_ax_field_does_not_offer_type_text() -> None:
    node = FakeNode(
        "INPUT",
        {"placeholder": "q"},
        ax_node=FakeAXNode(role="textbox", properties=[FakeAXProperty("disabled", True)]),
    )

    (element,) = observe(make_state({1: node})).elements
    assert element.operations == (JevOperation.CLICK,)


def test_page_text_is_browser_uses_own_rendering_capped(monkeypatch, flights_state) -> None:
    monkeypatch.setattr("app.services.browser.jev.observation.JEV_PAGE_TEXT_MAX_CHARS", 12)

    assert observe(flights_state).text == "[17]<input>\n"[:12]


def test_fingerprint_changes_with_a_value_but_not_with_an_unrelated_title(flights_state) -> None:
    before = observe(flights_state).fingerprint
    flights_state.title = "Other"
    assert observe(flights_state).fingerprint == before

    flights_state.dom_state.selector_map[23].attributes["value"] = "London"
    assert observe(flights_state).fingerprint != before


def test_a_node_that_raises_loses_only_its_row_and_is_logged(flights_state, monkeypatch) -> None:
    from unittest.mock import MagicMock

    from app.constants.log_tags import LogTag
    from app.services.browser.jev import observation as observation_mod

    logger = MagicMock()
    monkeypatch.setattr(observation_mod, "log", logger)

    class Broken:
        node_name = "BUTTON"
        attributes = None

        def get_meaningful_text_for_llm(self):
            raise RuntimeError("shape")

    flights_state.dom_state.selector_map[99] = Broken()

    assert len(observe(flights_state).elements) == 5
    logger.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Jev could not read a DOM node; row skipped",
        error_type="RuntimeError",
        browser_index=99,
    )


def test_a_serializer_failure_yields_empty_page_text_and_is_logged(
    flights_state, monkeypatch
) -> None:
    from unittest.mock import MagicMock

    from app.constants.log_tags import LogTag
    from app.services.browser.jev import observation as observation_mod

    logger = MagicMock()
    monkeypatch.setattr(observation_mod, "log", logger)

    def boom():
        raise RuntimeError("serializer")

    flights_state.dom_state.llm_representation = boom

    assert observe(flights_state).text == ""
    logger.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Jev page text unavailable for this step", error_type="RuntimeError"
    )


def test_live_values_override_attributes_for_text_selects_and_checkboxes(flights_state) -> None:
    from app.services.browser.jev.live_values import LiveValues

    for index, node in flights_state.dom_state.selector_map.items():
        node.backend_node_id = index
    business = flights_state.dom_state.selector_map[31].children_nodes[1]
    business.backend_node_id = 310
    live = LiveValues(
        values={23: "London", 17: ""}, checked=frozenset({40}), selected_options=frozenset({310})
    )

    elements = {e.label: e for e in observe(flights_state, live).elements}

    assert elements["Where to?"].value == "London"
    assert elements["Zurich"].value == ""  # cleared live, whatever the attribute says
    assert elements["Cabin class"].value == "Business"
    assert elements["Search"].checked is True


# ---------------------------------------------------------------------------
# The gateway refuses a question with more than 255 choices
# ---------------------------------------------------------------------------


def _big_page(count: int = 300):
    """Build count buttons, all of them rows in the selector map."""
    return make_state(
        {
            i: FakeNode(
                "BUTTON", text=f"Button {i}", ax_node=FakeAXNode(role="button", name=f"Button {i}")
            )
            for i in range(count)
        }
    )


def _on_screen_from(first: int, count: int) -> dict[int, ViewportBox]:
    return {i: ViewportBox(on_screen=i >= first, cx=0.5, cy=0.5) for i in range(count)}


def test_jev_sees_exactly_what_the_page_says_is_on_screen() -> None:
    """Off-screen elements are one SCROLL away, not part of this decision."""
    observation = observe(_big_page(count=100), None, ViewportRead(boxes=_on_screen_from(40, 100)))

    assert sorted(e.index for e in observation.elements) == list(range(41, 101))


def test_an_index_missing_from_the_viewport_map_is_kept() -> None:
    """An xpath the page could not resolve is unknown, and unknown never hides a control."""
    state = make_state(
        {
            1: FakeNode("BUTTON", text="Go", ax_node=FakeAXNode(role="button", name="Go")),
            2: FakeNode("BUTTON", text="Stop", ax_node=FakeAXNode(role="button", name="Stop")),
        }
    )

    observation = observe(
        state, None, ViewportRead(boxes={2: ViewportBox(on_screen=False, cx=0.0, cy=0.0)})
    )

    assert [e.label for e in observation.elements] == ["Go"]


def test_node_geometry_is_never_consulted() -> None:
    """The snapshot's own boxes are fabricated on some engines; only the page decides."""
    node = FakeNode("BUTTON", text="Go", ax_node=FakeAXNode(role="button", name="Go"))
    node.is_visible = False
    node.absolute_position = object()

    assert len(observe(make_state({1: node})).elements) == 1


def test_the_options_of_one_select_are_capped_in_document_order() -> None:
    state = make_state(
        {
            1: FakeNode(
                "SELECT",
                ax_node=FakeAXNode(role="combobox", name="Year"),
                children_nodes=[
                    FakeNode("OPTION", {"value": str(i)}, text=str(i)) for i in range(300)
                ],
            )
        }
    )

    targets = observe(state).targets(JevOperation.SELECT)

    assert len(targets) == JEV_MAX_ELEMENTS
    assert list(targets)[:2] == ["1:1", "1:2"]
    assert f"1:{JEV_MAX_ELEMENTS}" in targets
    assert f"1:{JEV_MAX_ELEMENTS + 1}" not in targets


def test_the_page_text_is_the_screens_text_when_the_page_could_read_it(flights_state) -> None:
    screen = ViewportRead(boxes={}, text="History\nPython 2.0 was released in 2000")

    assert observe(flights_state, None, screen).text == "History\nPython 2.0 was released in 2000"


def test_the_page_text_falls_back_to_browser_uses_own_rendering(flights_state) -> None:
    assert observe(flights_state, None, ViewportRead()).text.startswith("[17]<input>")


def test_the_url_and_title_come_from_the_page_itself_when_it_answered(flights_state) -> None:
    """Regression: a cross-origin click whose watchdog timed out leaves state.url pre-navigation."""
    screen = ViewportRead(url="https://de.wikipedia.org/wiki/Berlin", title="Berlin - Wikipedia")

    observation = observe(flights_state, None, screen)

    assert observation.url == "https://de.wikipedia.org/wiki/Berlin"
    assert observation.title == "Berlin - Wikipedia"


def test_the_url_and_title_fall_back_to_the_state_when_the_page_could_not_answer(
    flights_state,
) -> None:
    observation = observe(flights_state, None, ViewportRead())

    assert (observation.url, observation.title) == ("https://x", "X")


def test_html_entities_in_the_fallback_page_text_are_decoded(flights_state) -> None:
    """Regression: a done summary carried "n&#233;e" verbatim from the serialised DOM."""
    flights_state.dom_state.llm_representation = lambda: "Grace Hopper (n&#233;e Murray)"

    assert observe(flights_state).text == "Grace Hopper (née Murray)"


def test_zero_width_and_doubled_spaces_in_the_fallback_page_text_are_normalised(
    flights_state,
) -> None:
    flights_state.dom_state.llm_representation = lambda: "January  \u200b1,  1992"

    assert observe(flights_state).text == "January 1, 1992"


# ---------------------------------------------------------------------------
# Reading one row: tags, roles, labels, flags and values
# ---------------------------------------------------------------------------


def _only(node: FakeNode, live: LiveValues | None = None) -> JevElement:
    (element,) = observe(make_state({1: node}), live).elements
    return element


def test_a_state_with_no_dom_url_or_title_is_an_empty_page_not_an_error() -> None:
    observation = observe(SimpleNamespace())

    assert (observation.url, observation.title, observation.text) == ("", "", "")
    assert observation.elements == ()


def test_a_node_with_no_attributes_or_tag_is_still_listed_under_its_label() -> None:
    class BareNode:
        def get_meaningful_text_for_llm(self) -> str:
            return "Continue"

    state = SimpleNamespace(dom_state=SimpleNamespace(selector_map={1: BareNode()}))

    (element,) = observe(state).elements

    assert (element.label, element.role, element.operations) == (
        "Continue",
        "",
        (JevOperation.CLICK,),
    )


def test_a_listing_row_is_skipped_for_the_link_inside_it() -> None:
    """Regression: Jev clicked a Hacker News story row forty times to no effect."""
    state = make_state(
        {
            1: FakeNode("TR", text="1. Show HN: a thing"),
            2: FakeNode("TD", text="Show HN: a thing"),
            3: FakeNode("A", {"href": "/item?id=1"}, text="Show HN: a thing"),
        }
    )

    assert [(e.browser_index, e.role) for e in observe(state).elements] == [(3, "link")]


def test_a_table_cell_that_acts_on_its_own_is_listed() -> None:
    state = make_state(
        {
            1: FakeNode("TD", {"onclick": "sort()"}, text="Price"),
            2: FakeNode("TR", {"tabindex": "0"}, text="Row one"),
        }
    )

    assert [e.label for e in observe(state).elements] == ["Price", "Row one"]


@pytest.mark.parametrize(
    ("tag", "role", "operations"),
    [
        ("INPUT", "textbox", (JevOperation.CLICK, JevOperation.TYPE_TEXT)),
        ("TEXTAREA", "textbox", (JevOperation.CLICK, JevOperation.TYPE_TEXT)),
        ("SELECT", "combobox", (JevOperation.CLICK,)),
    ],
)
def test_an_unlabelled_field_is_listed_under_its_role(tag, role, operations) -> None:
    element = _only(FakeNode(tag))

    assert (element.label, element.role, element.operations) == (role, role, operations)


@pytest.mark.parametrize(
    ("node", "role"),
    [
        (FakeNode("DIV", text="Overview", ax_node=FakeAXNode(role="tab")), "tab"),
        (FakeNode("DIV", {"role": "switch"}, text="Dark mode"), "switch"),
        (FakeNode("INPUT", {"type": "search", "placeholder": "Search"}), "searchbox"),
        (FakeNode("INPUT", {"type": "radio", "aria-label": "Aisle"}), "radio"),
        (FakeNode("A", text="Next page"), "link"),
        (FakeNode("INPUT", {"type": "email", "placeholder": "you@x"}), "textbox"),
        (FakeNode("SPAN", text="Details"), "span"),
    ],
)
def test_a_role_comes_from_the_accessibility_tree_then_the_page_then_the_tag(node, role) -> None:
    assert _only(node).role == role


def test_the_accessibility_role_wins_over_the_role_attribute() -> None:
    node = FakeNode("DIV", {"role": "button"}, text="Menu", ax_node=FakeAXNode(role="menuitem"))

    assert _only(node).role == "menuitem"


def test_an_input_named_only_by_its_name_attribute_is_labelled_by_it() -> None:
    assert _only(FakeNode("INPUT", {"name": "q"})).label == "q"


def test_an_input_named_only_by_its_id_is_labelled_by_it() -> None:
    assert _only(FakeNode("INPUT", {"id": "flight-number"})).label == "flight-number"


def test_an_accessibility_node_without_properties_still_yields_the_row() -> None:
    ax = SimpleNamespace(role="button", name="Book")

    assert _only(FakeNode("BUTTON", ax_node=ax)).label == "Book"


def test_an_accessibility_property_without_a_value_still_yields_the_row() -> None:
    ax = FakeAXNode(role="checkbox", name="Agree", properties=[SimpleNamespace(name="checked")])

    element = _only(FakeNode("INPUT", {"type": "checkbox"}, ax_node=ax))

    assert (element.label, element.checked) == ("Agree", False)


def test_a_field_the_accessibility_tree_marks_read_only_does_not_offer_type_text() -> None:
    ax = FakeAXNode(role="textbox", name="Date", properties=[FakeAXProperty("readonly", True)])

    assert _only(FakeNode("INPUT", ax_node=ax)).operations == (JevOperation.CLICK,)


def test_a_textarea_takes_text_whatever_role_the_page_gives_it() -> None:
    node = FakeNode("TEXTAREA", {"placeholder": "Notes"}, ax_node=FakeAXNode(role="document"))

    assert JevOperation.TYPE_TEXT in _only(node).operations


def test_a_contenteditable_region_with_a_non_text_role_takes_text() -> None:
    node = FakeNode(
        "DIV",
        {"contenteditable": "true"},
        text="Draft",
        ax_node=FakeAXNode(role="group"),
    )

    assert JevOperation.TYPE_TEXT in _only(node).operations


def test_a_role_that_edits_text_takes_text_on_a_non_input_element() -> None:
    node = FakeNode("DIV", {"role": "searchbox", "aria-label": "Search mail"})

    assert JevOperation.TYPE_TEXT in _only(node).operations


def test_a_select_with_a_combobox_role_offers_select_not_type_text() -> None:
    node = FakeNode(
        "SELECT",
        ax_node=FakeAXNode(role="combobox", name="Cabin"),
        children_nodes=[FakeNode("OPTION", text="Economy")],
    )

    assert _only(node).operations == (JevOperation.CLICK, JevOperation.SELECT)


def test_a_plain_button_is_click_only() -> None:
    assert _only(FakeNode("BUTTON", text="Bold")).operations == (JevOperation.CLICK,)


# -- checked / expanded / selected ------------------------------------------------


@pytest.mark.parametrize(
    ("attributes", "properties", "checked"),
    [
        ({"checked": ""}, [], True),
        ({}, [], False),
        ({"aria-checked": "true"}, [], True),
        ({"aria-checked": "false", "checked": ""}, [], False),
        ({"aria-checked": "mixed", "checked": ""}, [], True),
        ({}, [FakeAXProperty("checked", "true")], True),
        ({"checked": ""}, [FakeAXProperty("checked", "false")], False),
        ({"aria-checked": "false"}, [FakeAXProperty("checked", True)], True),
        ({"aria-checked": "true"}, [FakeAXProperty("checked", "mixed")], True),
    ],
)
def test_checked_is_read_from_the_accessibility_tree_then_aria_then_the_attribute(
    attributes, properties, checked
) -> None:
    ax = FakeAXNode(role="checkbox", name="Nonstop", properties=properties)

    assert (
        _only(FakeNode("INPUT", {"type": "checkbox", **attributes}, ax_node=ax)).checked is checked
    )


@pytest.mark.parametrize(
    ("attributes", "properties", "expanded"),
    [
        ({}, [], None),
        ({"aria-expanded": "true"}, [], True),
        ({"aria-expanded": "false"}, [], False),
        ({"aria-expanded": "false"}, [FakeAXProperty("expanded", True)], True),
    ],
)
def test_expanded_is_known_only_when_the_page_says_so(attributes, properties, expanded) -> None:
    ax = FakeAXNode(role="button", name="Filters", properties=properties)

    element = _only(FakeNode("BUTTON", attributes, ax_node=ax))

    assert element.expanded is expanded
    assert ("expanded" in element.state_entry()) is (expanded is not None)


@pytest.mark.parametrize(
    ("attributes", "properties", "selected"),
    [
        ({}, [], None),
        ({"aria-selected": "true"}, [], True),
        ({"aria-selected": "false"}, [], False),
        ({"aria-selected": "true"}, [FakeAXProperty("selected", "false")], False),
    ],
)
def test_selected_is_known_only_when_the_page_says_so(attributes, properties, selected) -> None:
    ax = FakeAXNode(role="tab", name="Reviews", properties=properties)

    element = _only(FakeNode("DIV", attributes, ax_node=ax))

    assert element.selected is selected
    assert element.criterion().get("selected") is selected


# -- select options -------------------------------------------------------------


def _select(*options: FakeNode, attributes: dict[str, str] | None = None) -> FakeNode:
    return FakeNode(
        "SELECT",
        attributes or {},
        ax_node=FakeAXNode(role="combobox", name="Cabin"),
        children_nodes=list(options),
    )


def test_a_disabled_option_in_the_middle_does_not_hide_the_ones_after_it() -> None:
    cabin = _only(
        _select(
            FakeNode("OPTION", {"value": "y"}, text="Economy"),
            FakeNode("OPTION", {"value": "f", "disabled": ""}, text="First"),
            FakeNode("OPTION", {"value": "c"}, text="Business"),
        )
    )

    assert [(o.target, o.label) for o in cabin.options] == [("1:1", "Economy"), ("1:2", "Business")]


def test_options_inside_an_optgroup_are_listed() -> None:
    cabin = _only(
        _select(
            FakeNode(
                "OPTGROUP",
                children_nodes=[
                    FakeNode("OPTION", {"value": "y"}, text="Economy"),
                    FakeNode("OPTION", {"value": "c"}, text="Business"),
                ],
            )
        )
    )

    assert [o.label for o in cabin.options] == ["Economy", "Business"]


def test_an_options_label_is_its_text_with_whitespace_collapsed() -> None:
    cabin = _only(_select(FakeNode("OPTION", {"value": "pe"}, text="  Premium \n  economy ")))

    assert (cabin.options[0].label, cabin.options[0].value) == ("Premium economy", "pe")


def test_an_option_without_a_value_attribute_submits_its_label() -> None:
    cabin = _only(_select(FakeNode("OPTION", text="Economy")))

    assert cabin.options[0].value == "Economy"


def test_an_option_without_text_is_labelled_by_its_value() -> None:
    cabin = _only(_select(FakeNode("OPTION", {"value": "any"})))

    assert cabin.options[0].label == "any"


def test_the_option_with_the_selected_attribute_is_the_selects_value() -> None:
    cabin = _only(
        _select(
            FakeNode("OPTION", {"value": "y"}, text="Economy"),
            FakeNode("OPTION", {"value": "c", "selected": ""}, text="Business"),
        )
    )

    assert cabin.value == "Business"


def test_a_live_selection_wins_over_a_later_selected_attribute() -> None:
    economy = FakeNode("OPTION", {"value": "y"}, text="Economy")
    economy.backend_node_id = 501
    business = FakeNode("OPTION", {"value": "c", "selected": ""}, text="Business")

    cabin = _only(_select(economy, business), LiveValues(selected_options=frozenset({501})))

    assert cabin.value == "Economy"


def test_a_select_with_nothing_selected_shows_its_first_option() -> None:
    cabin = _only(
        _select(
            FakeNode("OPTION", {"value": "y"}, text="Economy"),
            FakeNode("OPTION", {"value": "c"}, text="Business"),
        )
    )

    assert cabin.value == "Economy"


def test_a_select_value_matching_no_option_is_shown_as_it_is() -> None:
    cabin = _only(
        _select(FakeNode("OPTION", {"value": "y"}, text="Economy"), attributes={"value": "w"})
    )

    assert cabin.value == "w"


def test_a_select_with_no_options_has_an_empty_value() -> None:
    cabin = _only(_select())

    assert (cabin.value, cabin.options, cabin.operations) == ("", (), (JevOperation.CLICK,))


# -- field values -----------------------------------------------------------------


def test_a_textarea_carries_its_live_value() -> None:
    node = FakeNode("TEXTAREA", {"placeholder": "Notes"})
    node.backend_node_id = 9

    assert _only(node, LiveValues(values={9: "Window seat"})).value == "Window seat"


@pytest.mark.parametrize(
    ("input_type", "secret"), [("password", True), ("PASSWORD", True), ("text", False)]
)
def test_only_a_password_field_holds_a_secret(input_type: str, secret: bool) -> None:
    """What is typed into a secret field is masked wherever the run shows it."""
    node = FakeNode("INPUT", {"type": input_type, "aria-label": "Password"})

    assert _only(node, LiveValues()).secret is secret


def test_a_contenteditable_region_carries_its_live_value() -> None:
    node = FakeNode("DIV", {"contenteditable": "true", "aria-label": "Message"})
    node.backend_node_id = 9

    assert _only(node, LiveValues(values={9: "Hello"})).value == "Hello"


def test_a_field_without_a_value_reads_the_accessibility_value_text() -> None:
    ax = FakeAXNode(role="slider", name="Price", properties=[FakeAXProperty("valuetext", "50%")])

    assert _only(FakeNode("INPUT", {"type": "range"}, ax_node=ax)).value == "50%"


def test_a_non_field_element_carries_no_value() -> None:
    ax = FakeAXNode(role="button", name="Go", properties=[FakeAXProperty("valuetext", "x")])

    assert _only(FakeNode("BUTTON", ax_node=ax)).value is None


# ---------------------------------------------------------------------------
# A screen denser than one decision
# ---------------------------------------------------------------------------


def test_a_screen_over_the_cap_lists_the_first_rows_and_says_how_many_were_left_out(
    monkeypatch,
) -> None:
    logger = MagicMock()
    monkeypatch.setattr(observation_mod, "log", logger)
    state = _big_page(count=JEV_MAX_ELEMENTS + 3)
    state.url = "https://dense.test/"

    observation = observe(state)

    assert len(observation.elements) == JEV_MAX_ELEMENTS
    assert observation.unlisted == 3
    assert observation.page_state()["elements_on_screen"] == JEV_MAX_ELEMENTS + 3
    logger.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Jev screen has more elements than one decision can carry",
        browser={"dropped": 3, "url": "https://dense.test/"},
    )


def test_the_fingerprint_changes_with_the_url_and_with_a_flag() -> None:
    node = FakeNode("BUTTON", {"aria-expanded": "false"}, text="Filters")
    before = observe(make_state({1: node}, url="https://a.test/")).fingerprint

    moved = observe(make_state({1: node}, url="https://b.test/")).fingerprint
    node.attributes["aria-expanded"] = "true"
    opened = observe(make_state({1: node}, url="https://a.test/")).fingerprint

    assert len({before, moved, opened}) == 3


def test_an_accessibility_property_without_a_name_still_yields_the_row() -> None:
    ax = FakeAXNode(role="button", name="Book", properties=[SimpleNamespace(value=True)])

    assert _only(FakeNode("BUTTON", ax_node=ax)).label == "Book"


def test_a_bare_text_node_among_the_options_does_not_lose_the_select() -> None:
    class TextNode:
        """A text node: no tag, no attributes, no children."""

        def get_all_children_text(self) -> str:
            return ""

    text_node = TextNode()

    cabin = _only(_select(FakeNode("OPTION", {"value": "y"}, text="Economy"), text_node))

    assert [o.label for o in cabin.options] == ["Economy"]
