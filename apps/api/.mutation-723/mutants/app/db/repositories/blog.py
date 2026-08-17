"""Repository for the ``blog`` collection — global, read-through with author join.

Posts are stored keyed by Mongo's ``_id``; every read populates ``author_details``
by joining the ``team`` collection (``$lookup`` on the ``authors`` id list). The
list/search projections omit ``content`` for lighter payloads, so it is
normalised (along with the author fallback) when mapping to :class:`BlogPost`.
"""

from collections.abc import Mapping, Sequence
import re

from app.db.repositories.base import MongoRepository
from app.models.blog_models import (
    AuthorDetails,
    BlogAggregateRow,
    BlogDocument,
    BlogPost,
    BlogUpdate,
)

# Join each post's ``authors`` id list to the ``team`` collection. Team ids are
# matched both as stringified ``_id`` and as raw ``_id`` so legacy string author
# ids and ObjectId author ids both resolve.
_AUTHOR_LOOKUP: dict[str, object] = {
    "$lookup": {
        "from": "team",
        "let": {"author_ids": "$authors"},
        "pipeline": [
            {
                "$match": {
                    "$expr": {
                        "$or": [
                            {"$in": [{"$toString": "$_id"}, "$$author_ids"]},
                            {"$in": ["$_id", "$$author_ids"]},
                        ]
                    }
                }
            },
            {
                "$project": {
                    "id": {"$toString": "$_id"},
                    "name": 1,
                    "role": 1,
                    "avatar": 1,
                    "linkedin": 1,
                    "twitter": 1,
                }
            },
        ],
        "as": "author_details",
    }
}


def _list_projection(include_content: bool) -> dict[str, object]:
    projection: dict[str, object] = {
        "id": {"$toString": "$_id"},
        "slug": 1,
        "title": 1,
        "date": 1,
        "authors": 1,
        "category": 1,
        "image": 1,
    }
    if include_content:
        projection["content"] = 1
    return projection


def _to_blog_post(row: BlogAggregateRow, *, include_content: bool) -> BlogPost:
    # Fall back to bare author ids when the team lookup found no member.
    author_details = row.author_details or [
        AuthorDetails(name=author_id, role="Author") for author_id in row.authors
    ]
    return BlogPost(
        id=row.id,
        slug=row.slug,
        title=row.title,
        date=row.date,
        authors=row.authors,
        category=row.category,
        image=row.image,
        content=row.content if include_content and row.content is not None else "",
        author_details=author_details,
    )


class BlogsRepository(MongoRepository[BlogDocument, BlogUpdate]):
    collection_name = "blog"
    document_model = BlogDocument
    update_model = BlogUpdate
    uses_object_id = True
    cache_policy = None

    async def _aggregate_posts(
        self, pipeline: Sequence[Mapping[str, object]], *, include_content: bool
    ) -> list[BlogPost]:
        rows = await self._aggregate(pipeline, BlogAggregateRow)
        return [_to_blog_post(row, include_content=include_content) for row in rows]

    async def list_page(
        self, *, skip: int, limit: int, include_content: bool = True
    ) -> list[BlogPost]:
        pipeline: list[Mapping[str, object]] = [
            {"$sort": {"date": -1}},
            {"$skip": skip},
            {"$limit": limit},
            {"$project": _list_projection(include_content)},
            _AUTHOR_LOOKUP,
        ]
        return await self._aggregate_posts(pipeline, include_content=include_content)

    async def get_by_slug(self, slug: str) -> BlogPost | None:
        pipeline: list[Mapping[str, object]] = [
            {"$match": {"slug": slug}},
            _AUTHOR_LOOKUP,
            {"$addFields": {"id": {"$toString": "$_id"}}},
        ]
        posts = await self._aggregate_posts(pipeline, include_content=True)
        return posts[0] if posts else None

    async def search(
        self, query: str, *, skip: int, limit: int, include_content: bool = True
    ) -> list[BlogPost]:
        """Case-insensitive substring match over title, category and body.

        Deliberately regex-only. MongoDB cannot plan a ``$text`` clause nested in
        an ``$or`` beside other predicates unless every sibling branch is indexed,
        and on 7.x it additionally refuses to attach ``textScore`` metadata to such
        a query at all — so the previous ``$text``-in-``$or`` shape sorted by
        ``{$meta: textScore}`` failed outright rather than degrading. Substring
        matching covers what the text index was reached for (title and body) plus
        the partial matches ``$text``'s whole-word stemming never caught.

        Ordered newest-first like :meth:`list_page`, which also makes the
        ``skip``/``limit`` window deterministic.
        """
        condition = {"$regex": re.escape(query), "$options": "i"}
        pipeline: list[Mapping[str, object]] = [
            {
                "$match": {
                    "$or": [
                        {"title": condition},
                        {"category": condition},
                        {"content": condition},
                    ]
                }
            },
            {"$sort": {"date": -1}},
            {"$skip": skip},
            {"$limit": limit},
            {"$project": _list_projection(include_content)},
            _AUTHOR_LOOKUP,
        ]
        return await self._aggregate_posts(pipeline, include_content=include_content)


blog_repository = BlogsRepository()
