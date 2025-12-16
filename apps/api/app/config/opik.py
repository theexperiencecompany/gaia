from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider
from opik import configure


@lazy_provider(
    name="opik",
    required_keys=[
        settings.OPIK_API_KEY,
        settings.OPIK_WORKSPACE,
    ],
    auto_initialize=True,
    is_global_context=True,
    strategy=MissingKeyStrategy.WARN,
    warning_message="Opik configuration is missing required settings and will not be initialized.",
)
def init_opik():
    """
    Initialize and configure the Opik client.

    """
    configure(api_key=settings.OPIK_API_KEY, workspace=settings.OPIK_WORKSPACE)
