"""Strip what a request carries in its URL and headers out of every Sentry event and trace.

A link's slug is the capability to open it, a content URL's ?t= token reads the file,
and the edge forwards the viewer's IP in its own header; none of them may leave the
process. The request URL becomes its route template, the query string and those headers
are dropped, and any copy of their values elsewhere in the event (a stack frame's
locals, a span) is filtered, since send_default_pii does not know about them.
"""

from typing import cast
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict
from sentry_sdk.tracing import TransactionSource
from sentry_sdk.types import Event

from app.constants.http import CONTENT_EDGE_HEADER, INTERNAL_CALLER_HEADER, VIEWER_IP_HEADER

#: Headers no event carries: the web server's and the content edge's tokens, and the viewer's IP.
_DROPPED_HEADERS = frozenset(
    name.lower() for name in (INTERNAL_CALLER_HEADER, CONTENT_EDGE_HEADER, VIEWER_IP_HEADER)
)
#: Path parameters that are capabilities: whoever holds one opens the link or its content.
_CAPABILITY_PATH_PARAMS = frozenset({"slug", "content_id"})
#: Shorter query values are flags and counts; filtering them everywhere would mangle the event.
_MIN_QUERY_SECRET_CHARS = 8
#: Span data carrying an outgoing call's query string (presigned URLs sign in it).
_SPAN_QUERY_KEY = "http.query"
FILTERED = "[Filtered]"
#: A transaction named by its raw URL (no route matched) is renamed to this.
UNROUTED = "<unrouted>"


class _Request(BaseModel):
    """A captured request; fields this module does not rewrite pass through untouched."""

    model_config = ConfigDict(extra="allow")

    url: str | None = None
    query_string: str | None = None
    headers: dict[str, object] = {}


class _Span(BaseModel):
    """A trace span; only its data is rewritten, the rest passes through untouched."""

    model_config = ConfigDict(extra="allow")

    data: dict[str, object] | None = None


class _TransactionInfo(BaseModel):
    source: str | None = None


class _Routed(BaseModel):
    """The parts of an event that say which request it came from and which route served it."""

    request: _Request | None = None
    transaction: str | None = None
    transaction_info: _TransactionInfo = _TransactionInfo()
    #: The span dicts, or the AnnotatedValue Sentry leaves in their place when it trimmed them.
    spans: object = None

    def route(self) -> str | None:
        """Return the matched route template, or None when the name is a raw URL."""
        if self.transaction_info.source == TransactionSource.ROUTE:
            return self.transaction
        return None


def _path_capabilities(path: str, route: str) -> set[str]:
    """Return the values the path holds for the route's capability parameters."""
    return {
        value
        for template, value in zip(route.split("/"), path.split("/"), strict=False)
        if template.startswith("{")
        and template.strip("{}").split(":")[0] in _CAPABILITY_PATH_PARAMS
    }


def _request_secrets(request: _Request, route: str | None) -> set[str]:
    url = urlsplit(request.url or "")
    secrets = {
        value
        for _, value in parse_qsl(request.query_string or url.query)
        if len(value) >= _MIN_QUERY_SECRET_CHARS
    }
    if request.query_string:
        secrets.add(request.query_string)
    if route is not None:
        secrets |= _path_capabilities(url.path, route)
    secrets |= {
        str(value) for name, value in request.headers.items() if name.lower() in _DROPPED_HEADERS
    }
    return {secret for secret in secrets if secret}


def _scrubbed_request(request: _Request, route: str | None) -> dict[str, object]:
    url = urlsplit(request.url or "")
    request.url = f"{url.scheme}://{url.netloc}{route or ''}" if url.netloc else None
    request.query_string = None
    request.headers = {
        name: value
        for name, value in request.headers.items()
        if name.lower() not in _DROPPED_HEADERS
    }
    return request.model_dump(exclude_none=True)


def _filtered(value: object, secrets: frozenset[str]) -> object:
    """Return value with every copy of a secret replaced, however deep it sits."""
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, FILTERED)
        return value
    if isinstance(value, dict):
        return {key: _filtered(item, secrets) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_filtered(item, secrets) for item in value]
    return value


def _without_query(span: object) -> dict[str, object]:
    parsed = _Span.model_validate(span)
    if parsed.data is not None:
        parsed.data.pop(_SPAN_QUERY_KEY, None)
    return parsed.model_dump(exclude_unset=True)


def scrub_request(event: Event) -> Event:
    """Return the event with its request reduced to its route and every value it carried filtered."""
    routed = _Routed.model_validate(event)
    route = routed.route()
    scrubbed: dict[str, object] = dict(event)
    if routed.transaction is not None and route is None:
        scrubbed["transaction"] = UNROUTED
    if isinstance(routed.spans, list):
        scrubbed["spans"] = [_without_query(span) for span in routed.spans]
    if routed.request is None:
        return cast(Event, scrubbed)
    secrets = frozenset(_request_secrets(routed.request, route))
    scrubbed["request"] = _scrubbed_request(routed.request, route)
    return cast(Event, _filtered(scrubbed, secrets))
