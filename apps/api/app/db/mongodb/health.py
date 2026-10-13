"""Server-level MongoDB probes; the one door services use instead of the collections module."""

from app.db.mongodb.collections import get_async_database


async def ping_mongodb() -> None:
    """Round-trip a ping command to MongoDB; raises when the server does not answer."""
    await get_async_database().command("ping")
