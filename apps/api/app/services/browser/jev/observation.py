"""Browser-Use's observed page as Jev's indexed element table.

jev-ultrafast builds its table from its own DOM snapshot; here the source is the
BrowserStateSummary Browser-Use already took for the step, so the policy
adds no browser round-trip. Elements are renumbered 1..N for the model and
mapped back to Browser-Use's own indices when a decision executes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import html
import json
from typing import TYPE_CHECKING, TypedDict, cast

from pydantic import BaseModel, ConfigDict, Field

from app.constants.browser import (
    JEV_ELEMENT_LABEL_MAX_CHARS,
    JEV_MAX_ELEMENTS,
    JEV_PAGE_TEXT_MAX_CHARS,
    JevOperation,
)
from app.constants.log_tags import LogTag
from app.services.browser.jev.live_values import LiveValues
from app.services.browser.jev.prompts import ELEMENTS_NOT_ALL_LISTED
from app.services.browser.jev.viewport import ViewportRead, normalize_page_text
from shared.py.wide_events import log

if TYPE_CHECKING:
    from browser_use.browser.views import BrowserStateSummary
    from browser_use.dom.views import EnhancedDOMTreeNode

# Labelling attributes in the order a person would recognise a control by.
_LABEL_ATTRIBUTES = ("aria-label", "placeholder", "title", "alt", "name", "id")
# <input type=...> values that are not free-text fields.
_NON_TEXT_INPUT_TYPES = frozenset(
    {"button", "submit", "reset", "checkbox", "radio", "file", "hidden", "image", "range", "color"}
)
_TEXT_ROLES = frozenset({"textbox", "searchbox", "combobox"})
#: Table structure that only ever wraps the control a click is meant for.
_TABLE_STRUCTURE = frozenset({"table", "tbody", "thead", "tfoot", "tr", "td", "th"})
#: Attributes that make a wrapper a control in its own right.
_ACTS_ON_ITS_OWN = ("href", "onclick", "role", "tabindex", "contenteditable")


def _acts_on_its_own(attributes: dict[str, str]) -> bool:
    return any(name in attributes for name in _ACTS_ON_ITS_OWN)


_ROLE_BY_TAG = {"a": "link", "button": "button", "select": "combobox", "textarea": "textbox"}
_ROLE_BY_INPUT_TYPE = {"checkbox": "checkbox", "radio": "radio", "search": "searchbox"}


class _DomAttributes(BaseModel):
    """The DOM attributes this module reads, as the page reported them."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    type: str | None = None
    role: str | None = None
    value: str | None = None
    contenteditable: str | None = None
    aria_checked: str | None = Field(default=None, alias="aria-checked")
    aria_expanded: str | None = Field(default=None, alias="aria-expanded")
    aria_selected: str | None = Field(default=None, alias="aria-selected")
    aria_readonly: str | None = Field(default=None, alias="aria-readonly")


class _AxProperties(TypedDict, total=False):
    """The AX property bag, read only for the flags and text this module names."""

    readonly: object
    disabled: object
    valuetext: object


@dataclass(frozen=True)
class JevSelectOption:
    target: str  # "<element index>:<option number>", the SELECT target key
    label: str
    value: str


@dataclass(frozen=True)
class JevElement:
    """One observed control, as Jev sees it and as Browser-Use addresses it."""

    index: int  # 1..N, the model-facing index
    browser_index: int  # Browser-Use's selector_map key
    label: str
    role: str
    operations: tuple[JevOperation, ...]
    value: str | None = None
    #: On screen according to the page itself (see viewport.py); an element the
    #: page could not resolve is unknown, and unknown never hides a control.
    in_viewport: bool = True
    checked: bool | None = None
    expanded: bool | None = None
    selected: bool | None = None
    options: tuple[JevSelectOption, ...] = ()
    #: A password field: what is typed into it is never repeated back.
    secret: bool = False

    def _flags(self) -> dict[str, object]:
        return {
            key: flag
            for key, flag in (
                ("checked", self.checked),
                ("expanded", self.expanded),
                ("selected", self.selected),
            )
            if flag is not None
        }

    def state_entry(self) -> dict[str, object]:
        """Return the row in state.elements, the table every question shares."""
        entry: dict[str, object] = {
            "index": str(self.index),
            "label": self.label,
            "role": self.role,
            "operations": [op.value for op in self.operations],
            **self._flags(),
        }
        if self.value is not None or self.options:
            entry["value"] = self.value or ""
        if self.options:
            entry["options"] = [
                {"index": o.target, "label": o.label, "value": o.value} for o in self.options
            ]
        return entry

    def criterion(self, label: str | None = None) -> dict[str, object]:
        """Return the description of this element as one option of a target question."""
        return {
            "element": f"[{self.index}] {label or self.label}",
            "current_value": self.value or "",
            "role": self.role,
            **self._flags(),
        }


@dataclass(frozen=True)
class JevObservation:
    """One step's page, as the policy sends it to Jev."""

    url: str
    title: str
    text: str
    elements: tuple[JevElement, ...]
    #: Controls on this screen that did not fit in the table Jev is shown.
    unlisted: int = 0
    #: True when the end of the page is on screen, so nothing is further down.
    at_bottom: bool | None = None
    fingerprint: str = field(default="")

    def page_state(self) -> dict[str, object]:
        state: dict[str, object] = {"url": self.url, "title": self.title, "text": self.text}
        if self.at_bottom is not None:
            # Twenty scrolls past the end of a list once spent the whole step budget.
            state["at_page_bottom"] = self.at_bottom
        if self.unlisted:
            # A silent cut hid the control Jev needed with no way to know it existed.
            state["elements_listed"] = len(self.elements)
            state["elements_on_screen"] = len(self.elements) + self.unlisted
            state["elements_note"] = ELEMENTS_NOT_ALL_LISTED
        return state

    def targets(
        self, operation: JevOperation
    ) -> dict[str, tuple[JevElement, JevSelectOption | None]]:
        """Return the target choices for one operation: element index, or index:option for SELECT.

        Drawn from elements, already ranked and capped, so every index offered
        here is a row Jev can read; one select's options are capped too.
        """
        choices: dict[str, tuple[JevElement, JevSelectOption | None]] = {}
        dropped = 0
        for element in self.elements:
            if operation not in element.operations:
                continue
            if operation is JevOperation.SELECT:
                candidates = [(option.target, option) for option in element.options]
            else:
                candidates = [(str(element.index), None)]
            for key, option in candidates:
                if len(choices) < JEV_MAX_ELEMENTS:
                    choices[key] = (element, option)
                else:
                    dropped += 1
        if dropped:
            log.warning(
                f"{LogTag.BROWSER} Jev targets capped",
                browser={"operation": operation.value, "dropped": dropped, "url": self.url},
            )
        return choices

    def element(self, index: int) -> JevElement | None:
        return next((e for e in self.elements if e.index == index), None)


def observe(
    state: BrowserStateSummary,
    live: LiveValues | None = None,
    screen: ViewportRead | None = None,
) -> JevObservation:
    """Build the element table from the selector map Browser-Use just serialised.

    live overlays current field values (see live_values.py); screen is what the
    page itself shows (see viewport.py) -- which rows, an index it omits
    counting as on screen, and the text on the screen rather than the document.
    """
    selector_map = getattr(getattr(state, "dom_state", None), "selector_map", None) or {}
    live = live or LiveValues()
    screen = screen or ViewportRead()
    boxes = screen.boxes
    elements: list[JevElement] = []
    for browser_index in sorted(selector_map):
        node = selector_map[browser_index]
        box = boxes.get(browser_index)
        on_screen = box.on_screen if box is not None else True
        element = _element(len(elements) + 1, browser_index, node, live, on_screen)
        if element is not None:
            elements.append(element)
    text = screen.text if screen.text is not None else _page_text(state)
    # The page's own answer over the state summary's: a cross-origin click whose
    # watchdog timed out leaves that url pre-navigation while the title is not.
    url = screen.url or getattr(state, "url", "") or ""
    listed, unlisted = _on_screen(elements, url)
    observation = JevObservation(
        url=url,
        title=screen.title or getattr(state, "title", "") or "",
        text=text,
        elements=listed,
        unlisted=unlisted,
        at_bottom=screen.at_bottom,
    )
    return JevObservation(
        **{k: v for k, v in observation.__dict__.items() if k != "fingerprint"},
        fingerprint=_fingerprint(observation),
    )


def _on_screen(elements: list[JevElement], url: str) -> tuple[tuple[JevElement, ...], int]:
    """Keep the elements inside the viewport, in document order, and count what did not fit.

    Jev decides on what a person sees; anything below the fold is one SCROLL away.
    The cap only bites on a screen denser than one decision can carry; document
    order is top to bottom, so the ones left out are what a scroll down lists next.
    """
    visible = [e for e in elements if e.in_viewport]
    dropped = max(len(visible) - JEV_MAX_ELEMENTS, 0)
    if dropped:
        log.warning(
            f"{LogTag.BROWSER} Jev screen has more elements than one decision can carry",
            browser={"dropped": dropped, "url": url},
        )
    return tuple(visible[:JEV_MAX_ELEMENTS]), dropped


def _page_text(state: BrowserStateSummary) -> str:
    dom_state = getattr(state, "dom_state", None)
    if dom_state is None:
        return ""
    try:
        text = dom_state.llm_representation()
    except Exception as exc:  # a serialiser hiccup must not kill the step; Jev still has the table
        log.warning(
            f"{LogTag.BROWSER} Jev page text unavailable for this step",
            error_type=type(exc).__name__,
        )
        return ""
    # The serialiser emits the source HTML's entities; the screen text path,
    # which walks text nodes, never does. Jev and the user read the same string.
    return normalize_page_text(html.unescape(str(text)))[:JEV_PAGE_TEXT_MAX_CHARS]


def _fingerprint(observation: JevObservation) -> str:
    content = [
        observation.url,
        [(e.label, e.role, e.value, e.checked, e.expanded) for e in observation.elements],
    ]
    return hashlib.sha256(json.dumps(content).encode()).hexdigest()


def _element(
    index: int,
    browser_index: int,
    node: EnhancedDOMTreeNode,
    live: LiveValues,
    in_viewport: bool,
) -> JevElement | None:
    try:
        attributes = _attributes(node)
        attrs = _DomAttributes.model_validate(attributes)
        tag = _tag(node)
        if tag in _TABLE_STRUCTURE and not _acts_on_its_own(attributes):
            # Listings flag whole rows as interactive (Hacker News story rows), and
            # Jev clicked such a row forty times to no effect; the link inside it
            # is the target and is listed on its own.
            return None
        ax = getattr(node, "ax_node", None)
        properties = _ax_properties(ax)
        label = _label(node, ax, attributes)
        if not label and tag not in ("input", "select", "textarea"):
            return None
        # Both defaults are only looked up in the input-type tables, where any
        # value those tables do not list reads alike.
        declared_type = attrs.type if attrs.type is not None else "text"  # pragma: no mutate
        input_type = declared_type.lower() if tag == "input" else ""  # pragma: no mutate
        role = (
            getattr(ax, "role", None)
            or attrs.role
            or _ROLE_BY_INPUT_TYPE.get(input_type)
            or _ROLE_BY_TAG.get(tag)
            or ("textbox" if tag == "input" else tag)
        )
        options, selected = _select_options(index, node, live) if tag == "select" else ((), None)
        operations = [JevOperation.CLICK]
        if _accepts_text(tag, input_type, role, attributes, properties):
            operations.append(JevOperation.TYPE_TEXT)
        if options:
            operations.append(JevOperation.SELECT)
        node_id = getattr(node, "backend_node_id", None)
        value = _value(tag, attributes, options, properties, live.values.get(node_id), selected)
        checked = (
            True
            if node_id in live.checked
            else _flag(properties, "checked", attrs.aria_checked, "checked" in attributes)
        )
        return JevElement(
            index=index,
            browser_index=browser_index,
            label=label or role,
            role=str(role),
            operations=tuple(operations),
            value=value,
            in_viewport=in_viewport,
            checked=checked,
            expanded=_flag(properties, "expanded", attrs.aria_expanded, None),
            selected=_flag(properties, "selected", attrs.aria_selected, None),
            options=options,
            secret=input_type == "password",
        )
    except Exception as exc:  # an unfamiliar node shape loses one row, not the step
        log.warning(
            f"{LogTag.BROWSER} Jev could not read a DOM node; row skipped",
            error_type=type(exc).__name__,
            browser_index=browser_index,
        )
        return None


def _tag(node: object) -> str:
    """Return the node's lower-case tag name; empty when the engine gave none."""
    return (getattr(node, "node_name", "") or "").lower()


def _attributes(node: object) -> dict[str, str]:
    """Return the node's DOM attributes; empty when the engine gave none."""
    attributes: dict[str, str] = getattr(node, "attributes", None) or {}
    return attributes


def _ax_properties(ax: object) -> dict[str, object]:
    return {
        # A nameless property's key is one no flag lookup reads, whatever it defaults to.
        str(getattr(p, "name", "")): getattr(p, "value", None)  # pragma: no mutate — key never read
        for p in (getattr(ax, "properties", None) or [])
    }


def _label(node: EnhancedDOMTreeNode, ax: object, attributes: dict[str, str]) -> str:
    candidates = [getattr(ax, "name", None), node.get_meaningful_text_for_llm()]
    candidates += [attributes.get(attr) for attr in _LABEL_ATTRIBUTES]
    for candidate in candidates:
        text = " ".join((candidate or "").split())
        if text:
            return text[:JEV_ELEMENT_LABEL_MAX_CHARS]
    return ""


def _accepts_text(
    tag: str,
    input_type: str,
    role: str,
    attributes: dict[str, str],
    properties: dict[str, object],
) -> bool:
    attrs = _DomAttributes.model_validate(attributes)
    typed_properties: _AxProperties = cast(_AxProperties, properties)
    if "readonly" in attributes or attrs.aria_readonly == "true":
        return False
    if typed_properties.get("readonly") is True or typed_properties.get("disabled") is True:
        return False
    if tag == "textarea" or attrs.contenteditable == "true":
        return True
    if tag == "input":
        return input_type not in _NON_TEXT_INPUT_TYPES
    return role in _TEXT_ROLES and tag != "select"


def _select_options(
    index: int, node: EnhancedDOMTreeNode, live: LiveValues
) -> tuple[tuple[JevSelectOption, ...], JevSelectOption | None]:
    """Return the enabled options, and the one currently selected (live, else the selected attr)."""
    options: list[JevSelectOption] = []
    selected: JevSelectOption | None = None
    selected_live = False

    def walk(current: EnhancedDOMTreeNode) -> None:
        nonlocal selected, selected_live
        for child in getattr(current, "children_nodes", None) or []:
            raw_child_attributes = _attributes(child)
            child_attrs = _DomAttributes.model_validate(raw_child_attributes)
            if _tag(child) == "option":
                if "disabled" in raw_child_attributes:
                    continue
                label = " ".join(child.get_all_children_text().split())
                value = child_attrs.value if child_attrs.value is not None else label
                option = JevSelectOption(
                    target=f"{index}:{len(options) + 1}", label=label or value, value=value
                )
                options.append(option)
                if child.backend_node_id in live.selected_options:
                    selected, selected_live = option, True
                elif "selected" in raw_child_attributes and not selected_live:
                    selected = option
            else:
                walk(child)

    walk(node)
    return tuple(options), selected


def _value(
    tag: str,
    attributes: dict[str, str],
    options: tuple[JevSelectOption, ...],
    properties: dict[str, object],
    live_value: str | None,
    selected: JevSelectOption | None,
) -> str | None:
    attrs = _DomAttributes.model_validate(attributes)
    typed_properties: _AxProperties = cast(_AxProperties, properties)
    if tag == "select":
        if selected is not None:
            return selected.label
        current = attrs.value
        chosen = next((o.label for o in options if o.value == current), None)
        return chosen or current or (options[0].label if options else "")
    if tag in ("input", "textarea") or attrs.contenteditable == "true":
        if live_value is not None:
            return live_value
        valuetext = typed_properties.get("valuetext")
        return attrs.value or (str(valuetext) if valuetext else "")
    return None


def _flag(
    properties: dict[str, object], name: str, aria: str | None, fallback: bool | None
) -> bool | None:
    value = properties.get(name)
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value in ("true", "false"):
        return value == "true"
    if aria in ("true", "false"):
        return aria == "true"
    return fallback
