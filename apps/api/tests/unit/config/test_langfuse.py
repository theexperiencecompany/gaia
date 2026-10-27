"""The Langfuse export budget, which is the whole of this module's tuning."""

from app.config.langfuse import LANGFUSE_EXPORT_TIMEOUT_SECONDS, LANGFUSE_FLUSH_AT


def test_the_export_budget_fits_the_collector() -> None:
    """Five seconds was shared by serialization and six retries; 512 spans overflowed the ingress."""
    assert LANGFUSE_EXPORT_TIMEOUT_SECONDS == 10
    assert LANGFUSE_FLUSH_AT == 128
