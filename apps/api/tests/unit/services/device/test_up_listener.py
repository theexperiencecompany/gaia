"""The shared up-listener hands each device up-frame to the inbox of the session it names."""

import json

from app.services.device import up_listener


async def test_a_frame_reaches_the_inbox_of_the_session_it_names() -> None:
    inbox = up_listener.register_up_session("s1")
    try:
        await up_listener._dispatch(json.dumps({"t": "mcp.opened", "sid": "s1", "pod": "p1"}))

        assert inbox.get_nowait() == {"t": "mcp.opened", "sid": "s1", "pod": "p1"}
    finally:
        up_listener.unregister_up_session("s1")


async def test_a_frame_that_is_not_json_reaches_no_inbox() -> None:
    inbox = up_listener.register_up_session("s1")
    try:
        await up_listener._dispatch('{"t": "mcp.opened", "sid": "s1"')

        assert inbox.empty()
    finally:
        up_listener.unregister_up_session("s1")
