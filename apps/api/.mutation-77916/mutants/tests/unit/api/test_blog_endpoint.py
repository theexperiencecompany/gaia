"""Endpoint tests for /api/v1/blogs.

Covers the MAX_PAGE_NUMBER page bound (the schemathesis-driven overflow
guard) and the happy-path list with the service and the Cacheable redis
seam faked — the blog list endpoint is @Cacheable, and the hermetic CI
lane has no Redis.
"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.constants.general import MAX_PAGE_NUMBER

BLOG_SERVICE = "app.api.v1.endpoints.blog"


class TestGetBlogs:
    """GET /api/v1/blogs"""

    async def test_page_over_max_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(f"/api/v1/blogs?page={MAX_PAGE_NUMBER + 1}")

        assert resp.status_code == 422

    async def test_list_returns_blogs(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{BLOG_SERVICE}.BlogService.get_all_blogs",
                new_callable=AsyncMock,
                return_value=[],
            ) as get_all,
            patch(
                "app.decorators.caching.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("app.decorators.caching.set_cache", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/v1/blogs?page=1&limit=20")

        assert resp.status_code == 200
        assert resp.json() == []
        get_all.assert_awaited_once_with(page=1, limit=20, include_content=False)
