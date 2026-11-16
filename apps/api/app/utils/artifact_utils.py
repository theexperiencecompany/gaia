"""Where this deployment serves and opens a conversation's files."""

from app.config.settings import settings
from app.utils.file_links import FileLinks

FILE_LINKS = FileLinks(api_host=settings.HOST, web_app=settings.FRONTEND_URL)
