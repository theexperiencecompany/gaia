from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.decorators.caching import Cacheable
from app.models.blog_models import BlogPost
from app.services.blog_service import BlogService
from shared.py.wide_events import log

router = APIRouter()

_DEPRECATED_DETAIL = "Endpoint not used anymore. Blog posts are managed out-of-band."


@router.get("/blogs", response_model=List[BlogPost])
@Cacheable(smart_hash=True, ttl=21600, model=List[BlogPost])  # 6 hours
async def get_blogs(
    page: int = Query(1, ge=1, description="Page number (starting from 1)"),
    limit: int = Query(
        20, ge=1, le=100, description="Number of blogs per page (1-100)"
    ),
    search: Optional[str] = Query(
        None, description="Search query for title, content, or tags"
    ),
    include_content: bool = Query(
        False,
        description="Include blog content in response (for list views, set to false for better performance)",
    ),
):
    """Get all blog posts with pagination and populated author details."""
    log.set(operation="list_blogs")
    if search:
        results = await BlogService.search_blogs(
            search, page=page, limit=limit, include_content=include_content
        )
        log.set(result_count=len(results))
        log.set(outcome="success")
        return results
    results = await BlogService.get_all_blogs(
        page=page, limit=limit, include_content=include_content
    )
    log.set(result_count=len(results))
    log.set(outcome="success")
    return results


@router.get("/blogs/{slug}", response_model=BlogPost)
@Cacheable(key_pattern="blog:{slug}", ttl=21600, model=BlogPost)  # 6 hours
async def get_blog(slug: str):
    """Get a specific blog post with populated author details."""
    log.set(operation="get_blog", slug=slug)
    result = await BlogService.get_blog_by_slug(slug)
    log.set(outcome="success")
    return result


@router.get("/blogs/count", response_model=dict)
@Cacheable(smart_hash=True, ttl=21600)  # 6 hours
async def get_blog_count():
    """Get total count of blog posts."""
    log.set(operation="get_blog_count")
    count = await BlogService.get_blog_count()
    log.set(result_count=count)
    log.set(outcome="success")
    return {"count": count}


@router.post("/blogs", status_code=status.HTTP_410_GONE, include_in_schema=False)
async def create_blog_deprecated() -> None:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=_DEPRECATED_DETAIL)


@router.put("/blogs/{slug}", status_code=status.HTTP_410_GONE, include_in_schema=False)
async def update_blog_deprecated(slug: str) -> None:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=_DEPRECATED_DETAIL)


@router.delete(
    "/blogs/{slug}", status_code=status.HTTP_410_GONE, include_in_schema=False
)
async def delete_blog_deprecated(slug: str) -> None:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=_DEPRECATED_DETAIL)
