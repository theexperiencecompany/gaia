"""Every route a client dials sits under the API prefix the deployed proxies forward.

Production nginx and the self-host Caddyfile forward /api/v1/* to the API (with
WebSocket upgrades); a root-mounted socket answered every live view with a 404
for weeks (GAIA-715) and nothing in the suite noticed.
"""

from fastapi import FastAPI
from fastapi.routing import APIWebSocketRoute, iter_route_contexts

from app.constants.http import API_V1_PREFIX


def _mounted_path(app: FastAPI, route: APIWebSocketRoute) -> str:
    """Return where the app serves route; the route context leaves a socket's prefixed path empty."""
    return str(app.url_path_for(route.name, **dict.fromkeys(route.param_convertors, "x")))


def test_every_websocket_is_under_the_api_prefix(app: FastAPI) -> None:
    sockets = [
        _mounted_path(app, ctx.original_route)
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.original_route, APIWebSocketRoute)
    ]
    assert sockets
    assert [path for path in sockets if not path.startswith(f"{API_V1_PREFIX}/")] == []
