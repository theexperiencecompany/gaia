"""Repository for the ``search_urls`` collection — scraped URL-metadata cache.

Global, keyed by the business ``url``. A read-through cache: a URL is looked up
by its address, and a miss is scraped elsewhere and stored once. The incidental
Mongo ``_id`` never surfaces above this boundary.
"""

from app.db.repositories.base import MongoRepository
from app.models.search_models import SearchUrlDocument, SearchUrlUpdate


class SearchUrlsRepository(MongoRepository[SearchUrlDocument, SearchUrlUpdate]):
    collection_name = "search_urls"
    document_model = SearchUrlDocument
    update_model = SearchUrlUpdate
    uses_object_id = True
    identity_field = "url"
    cache_policy = None

    async def get_by_url(self, url: str) -> SearchUrlDocument | None:
        return await self._find_one({"url": url})


search_url_repository = SearchUrlsRepository()
