"""Unit tests for the blog service.

The service is thin orchestration over ``blog_repository`` (pagination + a 404):
these tests mock that repository seam. The aggregation, author-join and content
normalisation live in the repository and are covered by its real-DB contract
suite; the regex-injection guard is asserted here against the repository's own
pipeline builder because it is security-critical.
"""

import re
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import pytest

from app.db.repositories.blog import blog_repository
from app.models.blog_models import AuthorDetails, BlogPost
from app.services.blog_service import BlogService
from tests.unit.services.regex_helpers import collect_regex_values


def _blog_post(**overrides: object) -> BlogPost:
    data: dict[str, object] = {
        "id": "blog123",
        "slug": "test-blog",
        "title": "Test Blog Post",
        "date": "2025-01-15",
        "authors": ["author1"],
        "category": "Tech",
        "content": "Blog content here.",
        "image": None,
        "author_details": [AuthorDetails(id="author1", name="Alice", role="Writer")],
    }
    data.update(overrides)
    return BlogPost.model_validate(data)


@pytest.fixture
def mock_blog_repo():
    repo = AsyncMock()
    with patch("app.services.blog_service.blog_repository", repo):
        yield repo


@pytest.fixture
def mock_redis_cache():
    """Bypass the @Cacheable layer so the wrapped function body runs."""
    with (
        patch("app.decorators.caching.get_cache", new_callable=AsyncMock, return_value=None),
        patch("app.decorators.caching.set_cache", new_callable=AsyncMock),
        patch("app.decorators.caching.delete_cache", new_callable=AsyncMock),
    ):
        yield


@pytest.mark.unit
class TestGetAllBlogs:
    async def test_returns_blog_posts(self, mock_blog_repo, mock_redis_cache):
        mock_blog_repo.list_page = AsyncMock(return_value=[_blog_post()])

        result = await BlogService.get_all_blogs(page=1, limit=20)

        assert len(result) == 1
        assert result[0].title == "Test Blog Post"

    async def test_pagination_calculates_skip(self, mock_blog_repo, mock_redis_cache):
        mock_blog_repo.list_page = AsyncMock(return_value=[])

        await BlogService.get_all_blogs(page=3, limit=10)

        call = mock_blog_repo.list_page.await_args
        assert call.kwargs["skip"] == 20  # (3-1) * 10
        assert call.kwargs["limit"] == 10

    async def test_include_content_flag_passthrough(self, mock_blog_repo, mock_redis_cache):
        mock_blog_repo.list_page = AsyncMock(return_value=[])

        await BlogService.get_all_blogs(include_content=False)

        assert mock_blog_repo.list_page.await_args.kwargs["include_content"] is False

    async def test_returns_empty_list(self, mock_blog_repo, mock_redis_cache):
        mock_blog_repo.list_page = AsyncMock(return_value=[])

        assert await BlogService.get_all_blogs() == []


@pytest.mark.unit
class TestGetBlogBySlug:
    async def test_returns_blog_by_slug(self, mock_blog_repo, mock_redis_cache):
        mock_blog_repo.get_by_slug = AsyncMock(return_value=_blog_post(slug="test-blog"))

        result = await BlogService.get_blog_by_slug("test-blog")

        assert isinstance(result, BlogPost)
        assert result.slug == "test-blog"

    async def test_raises_404_when_not_found(self, mock_blog_repo, mock_redis_cache):
        mock_blog_repo.get_by_slug = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await BlogService.get_blog_by_slug("nonexistent")

        assert exc_info.value.status_code == 404


@pytest.mark.unit
class TestGetBlogCount:
    async def test_returns_repository_count(self, mock_blog_repo):
        mock_blog_repo.count = AsyncMock(return_value=42)

        assert await BlogService.get_blog_count() == 42


@pytest.mark.unit
class TestSearchBlogs:
    async def test_searches_by_query(self, mock_blog_repo):
        mock_blog_repo.search = AsyncMock(return_value=[_blog_post(category="Tech")])

        result = await BlogService.search_blogs("Tech")

        assert len(result) == 1
        assert result[0].category == "Tech"
        assert mock_blog_repo.search.await_args.args[0] == "Tech"

    async def test_search_pagination(self, mock_blog_repo):
        mock_blog_repo.search = AsyncMock(return_value=[])

        await BlogService.search_blogs("test", page=2, limit=5)

        call = mock_blog_repo.search.await_args
        assert call.kwargs["skip"] == 5  # (2-1) * 5
        assert call.kwargs["limit"] == 5

    async def test_search_returns_empty(self, mock_blog_repo):
        mock_blog_repo.search = AsyncMock(return_value=[])

        assert await BlogService.search_blogs("nonexistent") == []


@pytest.mark.unit
class TestSearchBlogsRegexEscaping:
    async def test_search_query_is_regex_escaped(self):
        """The repository must feed a literal (escaped) query into every $regex
        stage; a raw metacharacter query would otherwise run as an arbitrary
        pattern. Asserted against the repository's own pipeline builder."""
        raw_query = "a.*(b|c)+[x]$"
        escaped = re.escape(raw_query)
        assert escaped != raw_query

        with patch.object(
            blog_repository, "_aggregate", new_callable=AsyncMock, return_value=[]
        ) as mock_aggregate:
            await blog_repository.search(raw_query, skip=0, limit=10)

        pipeline = mock_aggregate.await_args.args[0]
        regex_values = collect_regex_values(pipeline)

        assert regex_values, "expected the title/category $regex stages to be exercised"
        for value in regex_values:
            assert value == escaped
            assert value != raw_query
