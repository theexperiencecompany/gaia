from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider


@lazy_provider(
    name="opik",
    required_keys=[
        settings.OPIK_API_KEY,
        settings.OPIK_WORKSPACE,
    ],
    # Opik drags in litellm + nltk (~250MB of imports). It is observability-only,
    # so do NOT auto-initialize at startup — load it lazily only if explicitly used.
    auto_initialize=False,
    is_global_context=True,
    strategy=MissingKeyStrategy.WARN,
    warning_message="Opik configuration is missing required settings and will not be initialized.",
)
def init_opik():
    """
    Initialize and configure the Opik client.

    """
    # Lazy import: keeps opik/litellm/nltk out of the API startup baseline.
    from opik import configure

    configure(api_key=settings.OPIK_API_KEY, workspace=settings.OPIK_WORKSPACE)
