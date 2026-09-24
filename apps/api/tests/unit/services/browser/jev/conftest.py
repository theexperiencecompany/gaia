"""Shared fakes: a Browser-Use-shaped DOM node and state summary, no browser needed."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace


@dataclass
class FakeAXProperty:
    name: str
    value: object


@dataclass
class FakeAXNode:
    role: str | None = None
    name: str | None = None
    properties: list[FakeAXProperty] = field(default_factory=list)


@dataclass
class FakeNode:
    """The slice of EnhancedDOMTreeNode the observation reads."""

    node_name: str
    attributes: dict[str, str] = field(default_factory=dict)
    text: str = ""
    ax_node: FakeAXNode | None = None
    children_nodes: list[FakeNode] = field(default_factory=list)
    is_visible: bool | None = None

    def get_meaningful_text_for_llm(self) -> str:
        for attr in ("value", "aria-label", "title", "placeholder", "alt"):
            if self.attributes.get(attr):
                return self.attributes[attr]
        return self.get_all_children_text()

    def get_all_children_text(self) -> str:
        return " ".join(
            [self.text, *(c.get_all_children_text() for c in self.children_nodes)]
        ).strip()


def make_state(
    selector_map: dict[int, FakeNode],
    *,
    url: str = "https://x",
    title: str = "X",
):
    text = "\n".join(
        f"[{i}]<{n.node_name.lower()}>{n.get_all_children_text()}" for i, n in selector_map.items()
    )
    dom_state = SimpleNamespace(selector_map=selector_map, llm_representation=lambda: text)
    return SimpleNamespace(dom_state=dom_state, url=url, title=title)
