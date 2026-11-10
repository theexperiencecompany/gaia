"""Reading a tool argument the model JSON-encoded."""

import pytest

from app.agents.tools.playbook_tools import write_playbook
from app.utils.json_args import decode_json_container


@pytest.mark.parametrize(
    ("text", "decoded"),
    [('{"timeframe": "14d"}', {"timeframe": "14d"}), ('[{"id": "a"}]', [{"id": "a"}])],
    ids=["object", "list"],
)
def test_json_text_of_an_object_or_list_reads_as_that_value(text: str, decoded: object) -> None:
    assert decode_json_container(text) == decoded


@pytest.mark.parametrize(
    "value",
    ["1", '"just text"', "null", "not json", "{broken", 7, None, {"a": 1}, ["a"]],
    ids=["number", "string", "null", "prose", "broken", "int", "none", "dict", "list"],
)
def test_anything_else_is_left_for_the_args_own_check(value: object) -> None:
    assert decode_json_container(value) == value


def test_write_playbooks_schema_still_asks_for_a_list_of_steps() -> None:
    assert write_playbook.args["steps"]["type"] == "array"
