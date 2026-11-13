"""Provider-agnostic sending and Jinja2 template rendering for platform email."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config.settings import settings
from app.constants.providers import CredentialProviderName
from app.services.email.models import EmailMessage
from app.services.email.providers import get_email_provider
from app.services.providers.provider_credentials_service import resolve as resolve_provider_config

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"

jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_email_template(template_name: str, **context: object) -> str:
    return jinja_env.get_template(template_name).render(**context)


async def send_email(message: EmailMessage) -> None:
    """Send through the configured provider. Raises on failure."""
    await get_email_provider().send(message)


async def email_delivery_configured() -> bool:
    """Whether GAIA can send an email that carries a working unsubscribe link: a Resend key and the unsubscribe secret.

    The key resolves store-first (Settings, then the environment), as the provider's own send does.
    """
    config = await resolve_provider_config(CredentialProviderName.RESEND)
    return bool(config and config.api_key) and bool(settings.EMAIL_UNSUBSCRIBE_SECRET)
