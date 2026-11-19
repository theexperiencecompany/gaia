"""The URL a heygaia.link slug is shared at."""

from app.config.settings import settings


def build_url(slug: str) -> str:
    return f"{settings.SHORTLINK_BASE_URL}/{slug}"
