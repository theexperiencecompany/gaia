"""Provider-agnostic sending and Jinja2 template rendering for platform email."""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services.email.models import EmailMessage
from app.services.email.providers import get_email_provider

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"

jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_email_template(template_name: str, **context: Any) -> str:
    return jinja_env.get_template(template_name).render(**context)


async def send_email(message: EmailMessage) -> None:
    """Send through the configured provider. Raises on failure."""
    await get_email_provider().send(message)
