"""
Blog service module — thin orchestration over the blog repository.
"""

from fastapi import HTTPException, status

from app.db.repositories.blog import blog_repository
from app.decorators.caching import Cacheable
from app.models.blog_models import BlogPost
from shared.py.wide_events import log


class BlogService:
    """Service class for blog operations with caching and optimization."""

    @staticmethod
    @Cacheable(
        key_pattern="blogs:all:{page}:{limit}:{include_content}",
        ttl=3600,  # 1 hour cache
        model=list[BlogPost],  # Type-safe list caching
    )
    async def get_all_blogs(
        page: int = 1, limit: int = 20, include_content: bool = True
    ) -> list[BlogPost]:
        """Get all blog posts, paginated, with populated author details."""
        log.info(
            f"Fetching blogs - page: {page}, limit: {limit}, include_content: {include_content}"
        )

        blogs = await blog_repository.list_page(
            skip=(page - 1) * limit, limit=limit, include_content=include_content
        )

        log.set(blog={"page": page, "limit": limit, "result_count": len(blogs)})
        log.info(f"Retrieved {len(blogs)} blogs")
        return blogs

    @staticmethod
    @Cacheable(
        key_pattern="blog:{slug}",
        ttl=3600,  # 1 hour cache
        model=BlogPost,  # Type-safe model caching
    )
    async def get_blog_by_slug(slug: str) -> BlogPost:
        """Get a specific blog post by slug with populated author details."""
        log.info(f"Fetching blog by slug: {slug}")

        blog = await blog_repository.get_by_slug(slug)
        if blog is None:
            log.warning(f"Blog not found: {slug}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blog post not found")

        log.info(f"Retrieved blog: {slug}")
        return blog

    @staticmethod
    async def get_blog_count() -> int:
        """Get total count of blog posts."""
        return await blog_repository.count()

    @staticmethod
    async def search_blogs(
        query: str, page: int = 1, limit: int = 20, include_content: bool = True
    ) -> list[BlogPost]:
        """Search blogs by title, content, or tags."""
        log.info(f"Searching blogs: {query}, include_content: {include_content}")

        blogs = await blog_repository.search(
            query, skip=(page - 1) * limit, limit=limit, include_content=include_content
        )

        log.set(blog={"search_query": query, "result_count": len(blogs)})
        log.info(f"Found {len(blogs)} blogs matching: {query}")
        return blogs
