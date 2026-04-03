"""Unit tests for blog service operations."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.models.blog_models import BlogPost, BlogPostCreate, BlogPostUpdate
from app.services.blog_service import BlogService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_blog_collection():
    with patch("app.services.blog_service.blog_collection") as mock_col:
        yield mock_col


@pytest.fixture
def mock_cacheable():
    """Bypass the @Cacheable decorator so we test the raw function logic."""
    with (
        patch("app.services.blog_service.Cacheable", lambda **kw: lambda fn: fn),
        patch("app.services.blog_service.CacheInvalidator", lambda **kw: lambda fn: fn),
    ):
        # We need to reimport the module to pick up the patched decorators.
        # Instead, we patch the cache helpers that @Cacheable wraps.
        yield


@pytest.fixture
def mock_redis_cache():
    """Patch low-level redis helpers used by @Cacheable / @CacheInvalidator."""
    with (
        patch(
            "app.decorators.caching.get_cache",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("app.decorators.caching.set_cache", new_callable=AsyncMock),
        patch("app.decorators.caching.delete_cache", new_callable=AsyncMock),
    ):
        yield


@pytest.fixture
def sample_blog_aggregate_result():
    return {
        "_id": MagicMock(),
        "id": "blog123",
        "slug": "test-blog",
        "title": "Test Blog Post",
        "date": "2025-01-15",
        "authors": ["author1"],
        "category": "Tech",
        "content": "Blog content here.",
        "image": "https://example.com/blog.jpg",
        "author_details": [
            {"id": "author1", "name": "Alice", "role": "Writer"},
        ],
    }


@pytest.fixture
def sample_blog_no_author_details():
    return {
        "_id": MagicMock(),
        "id": "blog456",
        "slug": "no-author-blog",
        "title": "No Author Blog",
        "date": "2025-02-01",
        "authors": ["unknown_id"],
        "category": "General",
        "content": "Content without author.",
        "image": None,
        "author_details": [],
    }


# ---------------------------------------------------------------------------
# get_all_blogs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAllBlogs:
    async def test_returns_blog_posts(
        self, mock_blog_collection, mock_redis_cache, sample_blog_aggregate_result
    ):
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[sample_blog_aggregate_result])
        mock_blog_collection.aggregate.return_value = cursor

        result = await BlogService.get_all_blogs(page=1, limit=20)

        assert len(result) == 1
        assert isinstance(result[0], BlogPost)
        assert result[0].title == "Test Blog Post"

    async def test_pagination_calculates_skip(
        self, mock_blog_collection, mock_redis_cache
    ):
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[])
        mock_blog_collection.aggregate.return_value = cursor

        await BlogService.get_all_blogs(page=3, limit=10)

        pipeline = mock_blog_collection.aggregate.call_args[0][0]
        skip_stage = next(s for s in pipeline if "$skip" in s)
        assert skip_stage["$skip"] == 20  # (3-1) * 10

    async def test_excludes_content_when_flag_false(
        self, mock_blog_collection, mock_redis_cache
    ):
        blog_without_content = {
            "_id": MagicMock(),
            "id": "blogX",
            "slug": "no-content",
            "title": "Title",
            "date": "2025-01-01",
            "authors": [],
            "category": "Misc",
            "image": None,
            "author_details": [],
        }
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[blog_without_content])
        mock_blog_collection.aggregate.return_value = cursor

        result = await BlogService.get_all_blogs(include_content=False)

        assert len(result) == 1
        assert result[0].content == ""

    async def test_returns_empty_list(self, mock_blog_collection, mock_redis_cache):
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[])
        mock_blog_collection.aggregate.return_value = cursor

        result = await BlogService.get_all_blogs()

        assert result == []

    async def test_fallback_author_details(
        self, mock_blog_collection, mock_redis_cache, sample_blog_no_author_details
    ):
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[sample_blog_no_author_details])
        mock_blog_collection.aggregate.return_value = cursor

        result = await BlogService.get_all_blogs()

        assert len(result) == 1
        assert result[0].author_details is not None
        assert result[0].author_details[0].name == "unknown_id"
        assert result[0].author_details[0].role == "Author"


# ---------------------------------------------------------------------------
# get_blog_by_slug
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetBlogBySlug:
    async def test_returns_blog_by_slug(
        self, mock_blog_collection, mock_redis_cache, sample_blog_aggregate_result
    ):
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[sample_blog_aggregate_result])
        mock_blog_collection.aggregate.return_value = cursor

        result = await BlogService.get_blog_by_slug("test-blog")

        assert isinstance(result, BlogPost)
        assert result.slug == "test-blog"

    async def test_raises_404_when_not_found(
        self, mock_blog_collection, mock_redis_cache
    ):
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[])
        mock_blog_collection.aggregate.return_value = cursor

        with pytest.raises(HTTPException) as exc_info:
            await BlogService.get_blog_by_slug("nonexistent")

        assert exc_info.value.status_code == 404

    async def test_fallback_author_when_no_details(
        self, mock_blog_collection, mock_redis_cache, sample_blog_no_author_details
    ):
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[sample_blog_no_author_details])
        mock_blog_collection.aggregate.return_value = cursor

        result = await BlogService.get_blog_by_slug("no-author-blog")

        assert result.author_details[0].role == "Author"


# ---------------------------------------------------------------------------
# create_blog
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateBlog:
    async def test_creates_blog_post(
        self, mock_blog_collection, mock_redis_cache, sample_blog_aggregate_result
    ):
        # Slug doesn't exist yet
        mock_blog_collection.find_one = AsyncMock(return_value=None)
        insert_result = MagicMock(inserted_id="new_id")
        mock_blog_collection.insert_one = AsyncMock(return_value=insert_result)

        # Mock get_blog_by_slug called after creation
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[sample_blog_aggregate_result])
        mock_blog_collection.aggregate.return_value = cursor

        blog_data = BlogPostCreate(
            slug="test-blog",
            title="Test Blog Post",
            date="2025-01-15",
            authors=["author1"],
            category="Tech",
            content="Blog content here.",
        )

        result = await BlogService.create_blog(blog_data)

        assert isinstance(result, BlogPost)
        mock_blog_collection.insert_one.assert_called_once()

    async def test_raises_409_when_slug_exists(
        self, mock_blog_collection, mock_redis_cache
    ):
        mock_blog_collection.find_one = AsyncMock(
            return_value={"slug": "existing-slug"}
        )

        blog_data = BlogPostCreate(
            slug="existing-slug",
            title="Dup",
            date="2025-01-01",
            authors=[],
            category="X",
            content="Y",
        )

        with pytest.raises(HTTPException) as exc_info:
            await BlogService.create_blog(blog_data)

        assert exc_info.value.status_code == 409
        assert "slug already exists" in exc_info.value.detail

    async def test_raises_500_when_insert_fails(
        self, mock_blog_collection, mock_redis_cache
    ):
        mock_blog_collection.find_one = AsyncMock(return_value=None)
        insert_result = MagicMock(inserted_id=None)
        mock_blog_collection.insert_one = AsyncMock(return_value=insert_result)

        blog_data = BlogPostCreate(
            slug="fail-blog",
            title="Fail",
            date="2025-01-01",
            authors=[],
            category="X",
            content="Y",
        )

        with pytest.raises(HTTPException) as exc_info:
            await BlogService.create_blog(blog_data)

        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# update_blog
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateBlog:
    async def test_updates_blog_post(
        self, mock_blog_collection, mock_redis_cache, sample_blog_aggregate_result
    ):
        update_result = MagicMock(matched_count=1)
        mock_blog_collection.update_one = AsyncMock(return_value=update_result)

        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[sample_blog_aggregate_result])
        mock_blog_collection.aggregate.return_value = cursor

        update_data = BlogPostUpdate(title="Updated Title")
        result = await BlogService.update_blog("test-blog", update_data)

        assert isinstance(result, BlogPost)
        mock_blog_collection.update_one.assert_called_once()

    async def test_returns_existing_blog_when_no_fields(
        self, mock_blog_collection, mock_redis_cache, sample_blog_aggregate_result
    ):
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[sample_blog_aggregate_result])
        mock_blog_collection.aggregate.return_value = cursor

        update_data = BlogPostUpdate()  # All None
        result = await BlogService.update_blog("test-blog", update_data)

        assert isinstance(result, BlogPost)
        mock_blog_collection.update_one.assert_not_called()

    async def test_raises_404_when_slug_not_found(
        self, mock_blog_collection, mock_redis_cache
    ):
        update_result = MagicMock(matched_count=0)
        mock_blog_collection.update_one = AsyncMock(return_value=update_result)

        update_data = BlogPostUpdate(title="New Title")

        with pytest.raises(HTTPException) as exc_info:
            await BlogService.update_blog("nonexistent", update_data)

        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# delete_blog
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteBlog:
    async def test_deletes_blog_post(self, mock_blog_collection, mock_redis_cache):
        delete_result = MagicMock(deleted_count=1)
        mock_blog_collection.delete_one = AsyncMock(return_value=delete_result)

        await BlogService.delete_blog("test-blog")

        mock_blog_collection.delete_one.assert_called_once_with({"slug": "test-blog"})

    async def test_raises_404_when_slug_not_found(
        self, mock_blog_collection, mock_redis_cache
    ):
        delete_result = MagicMock(deleted_count=0)
        mock_blog_collection.delete_one = AsyncMock(return_value=delete_result)

        with pytest.raises(HTTPException) as exc_info:
            await BlogService.delete_blog("no-such-blog")

        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# get_blog_count
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetBlogCount:
    async def test_returns_document_count(self, mock_blog_collection):
        mock_blog_collection.count_documents = AsyncMock(return_value=42)

        result = await BlogService.get_blog_count()

        assert result == 42
        mock_blog_collection.count_documents.assert_called_once_with({})

    async def test_returns_zero_when_empty(self, mock_blog_collection):
        mock_blog_collection.count_documents = AsyncMock(return_value=0)

        result = await BlogService.get_blog_count()

        assert result == 0


# ---------------------------------------------------------------------------
# search_blogs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchBlogs:
    async def test_searches_by_query(
        self, mock_blog_collection, mock_redis_cache, sample_blog_aggregate_result
    ):
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[sample_blog_aggregate_result])
        mock_blog_collection.aggregate.return_value = cursor

        result = await BlogService.search_blogs("Tech")

        assert len(result) == 1
        assert result[0].category == "Tech"

    async def test_search_pagination(self, mock_blog_collection, mock_redis_cache):
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[])
        mock_blog_collection.aggregate.return_value = cursor

        await BlogService.search_blogs("test", page=2, limit=5)

        pipeline = mock_blog_collection.aggregate.call_args[0][0]
        skip_stage = next(s for s in pipeline if "$skip" in s)
        assert skip_stage["$skip"] == 5  # (2-1) * 5

    async def test_search_returns_empty(self, mock_blog_collection, mock_redis_cache):
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[])
        mock_blog_collection.aggregate.return_value = cursor

        result = await BlogService.search_blogs("nonexistent")

        assert result == []

    async def test_search_excludes_content_when_flag_false(
        self, mock_blog_collection, mock_redis_cache
    ):
        blog_no_content = {
            "_id": MagicMock(),
            "id": "blogSearch1",
            "slug": "search-no-content",
            "title": "Search Result",
            "date": "2025-01-01",
            "authors": [],
            "category": "Test",
            "image": None,
            "author_details": [],
        }
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[blog_no_content])
        mock_blog_collection.aggregate.return_value = cursor

        result = await BlogService.search_blogs("Search", include_content=False)

        assert len(result) == 1
        assert result[0].content == ""

    async def test_search_fallback_author_details(
        self, mock_blog_collection, mock_redis_cache, sample_blog_no_author_details
    ):
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[sample_blog_no_author_details])
        mock_blog_collection.aggregate.return_value = cursor

        result = await BlogService.search_blogs("General")

        assert result[0].author_details[0].name == "unknown_id"
