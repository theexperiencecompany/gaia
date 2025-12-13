import io
import json
from typing import List, Optional

import cloudinary
import cloudinary.uploader
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)

from app.api.v1.dependencies.blog_auth import verify_blog_token
from app.decorators.caching import Cacheable
from app.models.blog_models import BlogPost, BlogPostCreate, BlogPostUpdate
from app.services.blog_service import BlogService

router = APIRouter()


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
    if search:
        return await BlogService.search_blogs(
            search, page=page, limit=limit, include_content=include_content
        )
    return await BlogService.get_all_blogs(
        page=page, limit=limit, include_content=include_content
    )


@router.get("/blogs/{slug}", response_model=BlogPost)
@Cacheable(key_pattern="blog:{slug}", ttl=21600, model=BlogPost)  # 6 hours
async def get_blog(slug: str):
    """Get a specific blog post with populated author details."""
    return await BlogService.get_blog_by_slug(slug)


@router.post("/blogs", response_model=BlogPost, status_code=status.HTTP_201_CREATED)
async def create_blog(
    title: str = Form(...),
    slug: str = Form(...),
    content: str = Form(...),
    category: str = Form(...),
    date: str = Form(...),
    authors: str = Form(...),  # JSON string
    image: Optional[UploadFile] = File(None),
    _token: str = Depends(verify_blog_token),
):
    """Create a new blog post with optional image upload. Requires bearer token authentication."""

    # Parse authors from JSON string
    try:
        authors_list = json.loads(authors)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid authors format. Must be a JSON array.",
        )

    # Handle image upload if provided
    image_url = None
    if image and image.filename:
        try:
            # Validate file
            if not image.content_type or not image.content_type.startswith("image/"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="File must be an image",
                )

            # Read file content
            contents = await image.read()

            # Upload to cloudinary
            upload_result = cloudinary.uploader.upload(
                io.BytesIO(contents),
                resource_type="image",
                folder="blog/banners",
                transformation=[
                    {
                        "width": 1200,
                        "height": 630,
                        "crop": "fill",
                        "quality": "auto",
                        "format": "webp",
                    }
                ],
                overwrite=True,
                tags=["blog", "banner"],
            )

            image_url = upload_result.get("secure_url")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload image: {str(e)}",
            )

    # Create blog post data
    blog_data = BlogPostCreate(
        title=title,
        slug=slug,
        content=content,
        category=category,
        date=date,
        authors=authors_list,
        image=image_url,
    )

    return await BlogService.create_blog(blog_data)


@router.put("/blogs/{slug}", response_model=BlogPost)
async def update_blog(
    slug: str, blog: BlogPostUpdate, _token: str = Depends(verify_blog_token)
):
    """Update a blog post. Requires bearer token authentication."""
    return await BlogService.update_blog(slug, blog)


@router.delete("/blogs/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blog(slug: str, _token: str = Depends(verify_blog_token)):
    """Delete a blog post. Requires bearer token authentication."""
    await BlogService.delete_blog(slug)
    return


@router.get("/blogs/count", response_model=dict)
@Cacheable(smart_hash=True, ttl=21600)  # 6 hours
async def get_blog_count():
    """Get total count of blog posts."""
    count = await BlogService.get_blog_count()
    return {"count": count}
