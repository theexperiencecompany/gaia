"""The REST request helper as the runners place it: its source, its path, and the env it reads."""

from pathlib import Path

from app.constants.connectors import CONNECTOR_REST_HELPER
from app.services.connectors.runner import runner_path
from app.services.connectors.scripts import gaia_rest
from app.services.connectors.scripts.gaia_rest import (
    AUTH_HEADER_ENV,
    AUTH_QUERY_ENV,
    AUTH_TEMPLATE_ENV,
    BASE_URL_ENV,
    SECRET_ENV,
)

__all__ = [
    "AUTH_HEADER_ENV",
    "AUTH_QUERY_ENV",
    "AUTH_TEMPLATE_ENV",
    "BASE_URL_ENV",
    "REST_HELPER_ARGV",
    "REST_HELPER_PATH",
    "REST_HELPER_SOURCE",
    "SECRET_ENV",
]

REST_HELPER_SOURCE: str = Path(gaia_rest.__file__).read_text(encoding="utf-8")
REST_HELPER_PATH: str = runner_path(CONNECTOR_REST_HELPER)
# What a REST connector's argv starts with; an absolute path, since argv never meets a shell's ~.
REST_HELPER_ARGV: tuple[str, ...] = ("python3", REST_HELPER_PATH)
