"""Dev postmark seeding against real Mongo: the rows the Postmarks page and brief page read."""

from collections.abc import AsyncIterator

from bson import ObjectId
import pytest

from app.constants.briefing import POSTAL_FAMILY
from app.db.repositories.briefings import briefing_repository
from app.models.user_models import UserDocument
from app.services.briefing.editions.stamps import hosted_stamp_weights
from app.services.briefing.postmarks import collected_postmarks
from app.services.dev_postmarks_seed import seed_dev_postmarks
from app.utils.errors import AppError

SEEDED = 12


@pytest.fixture
async def dev_user(mongo_db) -> AsyncIterator[UserDocument]:
    user = UserDocument.model_validate({"id": str(ObjectId()), "email": "dev@gaia.local"})
    yield user
    await mongo_db["briefings"].delete_many({"user_id": user.id})


async def test_reseeding_yields_one_delivered_postal_brief_per_distinct_city(dev_user) -> None:
    await seed_dev_postmarks(dev_user, SEEDED)
    await seed_dev_postmarks(dev_user, SEEDED)

    briefs = await briefing_repository.list_stamped(dev_user.id)
    assert len(briefs) == SEEDED
    assert len({b.payload.stamp_city for b in briefs}) == SEEDED
    assert len({b.date for b in briefs}) == SEEDED
    assert all(b.payload.template_family == POSTAL_FAMILY for b in briefs)
    assert all(b.delivered_channels for b in briefs)

    postmarks = await collected_postmarks(dev_user.id)
    assert len(postmarks.postmarks) == SEEDED
    first = postmarks.postmarks[0]
    opened = await briefing_repository.get(first.briefing_id, user_id=dev_user.id)
    assert opened is not None and opened.payload.stamp_city == first.city_slug


async def test_asking_for_more_postmarks_than_cities_writes_nothing(dev_user) -> None:
    with pytest.raises(AppError) as exc:
        await seed_dev_postmarks(dev_user, len(hosted_stamp_weights()) + 1)

    assert exc.value.status_code == 400
    assert await briefing_repository.list_stamped(dev_user.id) == []
