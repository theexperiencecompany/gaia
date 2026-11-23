"""Count every request GAIA's own web server made that the API refused, the signal its alert reads.

A request carrying a valid INTERNAL_API_TOKEN is the web app rendering a page for a visitor,
so a 401 or 403 on it means a page is calling a route that does not admit the web server.
Both series are created at zero when the API starts, so the first refusal is an increase.
"""

from enum import StrEnum
from http import HTTPStatus

from prometheus_client import Counter

from app.services.storage.metrics import _register_once


class InternalCallerRefusal(StrEnum):
    """Why the web server's request was refused."""

    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"


_REFUSALS: dict[int, InternalCallerRefusal] = {
    HTTPStatus.UNAUTHORIZED: InternalCallerRefusal.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN: InternalCallerRefusal.FORBIDDEN,
}

INTERNAL_CALLER_REFUSED_TOTAL = _register_once(
    "gaia_internal_caller_refused_total",
    lambda: Counter(
        name="gaia_internal_caller_refused_total",
        documentation="Requests from GAIA's web server, valid internal token, that the API refused",
        labelnames=("reason",),
    ),
)


def observe_internal_caller_response(status_code: int) -> None:
    """Count the web server's request when its status is a refusal."""
    refusal = _REFUSALS.get(status_code)
    if refusal is not None:
        INTERNAL_CALLER_REFUSED_TOTAL.labels(refusal.value).inc()


def create_internal_caller_series() -> None:
    """Create every refusal series at zero, so its first increment is visible."""
    for refusal in InternalCallerRefusal:
        INTERNAL_CALLER_REFUSED_TOTAL.labels(refusal.value)
