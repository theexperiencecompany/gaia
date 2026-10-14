"""The request path as logs may record it, with secret path parameters named.

Kept free of settings: the exception handlers import it, and the embedding
sidecar boots them without API secrets.
"""

from fastapi import Request


def log_route_template_as_path(request: Request) -> None:
    """Route dependency: log this request's path with its path parameters named.

    For routes whose path carries a secret (a heygaia.link slug is a working
    capability), so /api/v1/l/{slug} reaches the logs instead of the live link.
    """
    by_value = {value: f"{{{name}}}" for name, value in request.path_params.items()}
    request.state.loggable_path = "/".join(
        by_value.get(segment, segment) for segment in request.url.path.split("/")
    )


def loggable_request_path(request: Request) -> str:
    """Return the request path as logs may record it.

    Parameters named where a route marked its path secret (log_route_template_as_path),
    the URL path otherwise.
    """
    path: str = getattr(request.state, "loggable_path", request.url.path)
    return path
