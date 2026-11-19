"""Repository for the link_reports collection: who reported which heygaia.link, once each."""

from pymongo.errors import DuplicateKeyError

from app.db.repositories.base import MongoRepository
from app.models.short_link_models import LinkReport, LinkReportUpdate

#: One report per reporter per link; a second from the same viewer changes nothing.
REPORTER_UNIQUE_INDEX = "slug_reporter_unique"


class LinkReportsRepository(MongoRepository[LinkReport, LinkReportUpdate]):
    collection_name = "link_reports"
    document_model = LinkReport
    update_model = LinkReportUpdate
    uses_object_id = True
    cache_policy = None

    async def add(self, report: LinkReport) -> bool:
        """Record a report; False when this reporter already reported this link."""
        try:
            await self.create(report)
        except DuplicateKeyError:
            return False
        return True

    async def signed_in_reporters(self, slug: str) -> int:
        return await self._count({"slug": slug, "signed_in": True})


link_report_repository = LinkReportsRepository()
