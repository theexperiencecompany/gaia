"""No-op ChromaDB product telemetry.

chromadb 1.0.x calls posthog's ``capture()`` with three positional arguments,
but posthog >= 3 accepts only one (``capture(event, **kwargs)``). The bundled
``Posthog`` telemetry client therefore raises ``capture() takes 1 positional
argument but 3 were given`` on every event, logged as a noisy error on each
collection start/create/query. ``anonymized_telemetry=False`` does not help: the
``TypeError`` is raised at call binding, before posthog's disabled check runs.

We don't collect product telemetry anyway, so we point chromadb's
``chroma_product_telemetry_impl`` setting at this no-op client, which skips the
posthog call entirely regardless of the installed posthog version.
"""

from chromadb.telemetry.product import ProductTelemetryClient, ProductTelemetryEvent
from overrides import override


class NoopProductTelemetry(ProductTelemetryClient):
    """Discards every telemetry event instead of shipping it to posthog."""

    @override
    def capture(self, event: ProductTelemetryEvent) -> None:
        del event


# Dotted path chromadb imports to resolve the telemetry client (see
# `chroma_product_telemetry_impl` in the ChromaDB client Settings). Derived from
# the class so it can never drift from the definition above.
NOOP_PRODUCT_TELEMETRY_IMPL = (
    f"{NoopProductTelemetry.__module__}.{NoopProductTelemetry.__qualname__}"
)
