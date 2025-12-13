"""
Blog service module for handling blog-related operations with optimization.
"""

from typing import List

from fastapi import HTTPException, status

from app.config.loggers import blogs_logger as logger
from app.db.mongodb.collections import blog_collection
from app.decorators.caching import Cacheable, CacheInvalidator
from app.db.utils import serialize_document
from app.models.blog_models import BlogPost, BlogPostCreate, BlogPostUpdate


class BlogService:
    """Service class for blog operations with caching and optimization."""

    @staticmethod
    @Cacheable(
        key_pattern="blogs:all:{page}:{limit}:{include_content}",
        ttl=3600,  # 1 hour cache
        model=List[BlogPost],  # Type-safe list caching
    )
    async def get_all_blogs(
        page: int = 1, limit: int = 20, include_content: bool = True
    ) -> List[BlogPost]:
        """
        Get all blog posts with pagination and populated author details.

        Args:
            page: Page number (1-based)
            limit: Number of blogs per page
            include_content: Whether to include blog content (set to False for list views for better performance)

        Returns:
            List of blog posts with author details
        """
        logger.info(
            f"Fetching blogs - page: {page}, limit: {limit}, include_content: {include_content}"
        )

        skip = (page - 1) * limit

        # Base projection - exclude content if not needed
        projection = {
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

        # Use aggregation pipeline for efficient author population
        pipeline = [
            {"$sort": {"date": -1}},  # Sort by date descending
            {"$skip": skip},
            {"$limit": limit},
            {"$project": projection},
            {
                "$lookup": {
                    "from": "team",
                    "let": {"author_ids": "$authors"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$or": [
                                        {
                                            "$in": [
                                                {"$toString": "$_id"},
                                                "$$author_ids",
                                            ]
                                        },
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
            },
        ]

        blogs = await blog_collection.aggregate(pipeline).to_list(limit)

        # Convert to Pydantic models
        blog_posts = []
        for blog in blogs:
            # Handle fallback for missing authors
            if not blog.get("author_details"):
                blog["author_details"] = [
                    {"name": str(author_id), "role": "Author"}
                    for author_id in blog.get("authors", [])
                ]

            # Set content to empty string if not included
            if not include_content and "content" not in blog:
                blog["content"] = ""

            blog_posts.append(BlogPost(**serialize_document(blog)))

        logger.info(f"Retrieved {len(blog_posts)} blogs")
        return blog_posts

    @staticmethod
    @Cacheable(
        key_pattern="blog:{slug}",
        ttl=3600,  # 1 hour cache
        model=BlogPost,  # Type-safe model caching
    )
    async def get_blog_by_slug(slug: str) -> BlogPost:
        """
        Get a specific blog post by slug with populated author details.

        Args:
            slug: Blog post slug

        Returns:
            Blog post with author details

        Raises:
            HTTPException: If blog post not found
        """
        logger.info(f"Fetching blog by slug: {slug}")

        # Use aggregation for efficient author population
        pipeline = [
            {"$match": {"slug": slug}},
            {
                "$lookup": {
                    "from": "team",
                    "let": {"author_ids": "$authors"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$or": [
                                        {
                                            "$in": [
                                                {"$toString": "$_id"},
                                                "$$author_ids",
                                            ]
                                        },
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
            },
            {"$addFields": {"id": {"$toString": "$_id"}}},
        ]

        blogs = await blog_collection.aggregate(pipeline).to_list(1)

        if not blogs:
            logger.warning(f"Blog not found: {slug}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Blog post not found"
            )

        blog = blogs[0]

        # Handle fallback for missing authors
        if not blog.get("author_details"):
            blog["author_details"] = [
                {"name": str(author_id), "role": "Author"}
                for author_id in blog.get("authors", [])
            ]

        logger.info(f"Retrieved blog: {slug}")
        return BlogPost(**serialize_document(blog))

    @staticmethod
    @CacheInvalidator(
        key_patterns=[
            "blogs:all:*",
        ]
    )
    async def create_blog(blog_data: BlogPostCreate) -> BlogPost:
        """
        Create a new blog post.

        Args:
            blog_data: Blog post creation data

        Returns:
            Created blog post with author details

        Raises:
            HTTPException: If slug already exists
        """
        logger.info(f"Creating blog with slug: {blog_data.slug}")

        # Check if slug already exists
        existing = await blog_collection.find_one({"slug": blog_data.slug})
        if existing:
            logger.warning(f"Blog slug already exists: {blog_data.slug}")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Blog post with this slug already exists",
            )

        # Insert blog post
        blog_dict = blog_data.model_dump()
        result = await blog_collection.insert_one(blog_dict)

        if not result.inserted_id:
            logger.error("Failed to create blog post")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create blog post",
            )

        logger.info(f"Blog created with ID: {result.inserted_id}")

        # Return the created blog with populated authors
        return await BlogService.get_blog_by_slug(blog_data.slug)

    @staticmethod
    @CacheInvalidator(
        key_patterns=[
            "blogs:all:*",
            "blog:{slug}",
        ]
    )
    async def update_blog(slug: str, update_data: BlogPostUpdate) -> BlogPost:
        """
        Update a blog post.

        Args:
            slug: Blog post slug
            update_data: Update data

        Returns:
            Updated blog post with author details

        Raises:
            HTTPException: If blog post not found
        """
        logger.info(f"Updating blog: {slug}")

        # Build update dictionary (exclude None values)
        update_dict = {
            k: v for k, v in update_data.model_dump().items() if v is not None
        }

        if not update_dict:
            logger.info("No fields to update")
            return await BlogService.get_blog_by_slug(slug)

        # Update blog post
        result = await blog_collection.update_one({"slug": slug}, {"$set": update_dict})

        if result.matched_count == 0:
            logger.warning(f"Blog not found for update: {slug}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Blog post not found"
            )

        logger.info(f"Blog updated: {slug}")

        # Return the updated blog with populated authors
        return await BlogService.get_blog_by_slug(slug)

    @staticmethod
    @CacheInvalidator(
        key_patterns=[
            "blogs:all:*",
            "blog:{slug}",
        ]
    )
    async def delete_blog(slug: str) -> None:
        """
        Delete a blog post.

        Args:
            slug: Blog post slug

        Raises:
            HTTPException: If blog post not found
        """
        logger.info(f"Deleting blog: {slug}")

        result = await blog_collection.delete_one({"slug": slug})

        if result.deleted_count == 0:
            logger.warning(f"Blog not found for deletion: {slug}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Blog post not found"
            )

        logger.info(f"Blog deleted: {slug}")

    @staticmethod
    async def get_blog_count() -> int:
        """Get total count of blog posts."""
        return await blog_collection.count_documents({})

    @staticmethod
    async def search_blogs(
        query: str, page: int = 1, limit: int = 20, include_content: bool = True
    ) -> List[BlogPost]:
        """
        Search blogs by title, content, or tags.

        Args:
            query: Search query
            page: Page number
            limit: Results per page
            include_content: Whether to include blog content (set to False for list views for better performance)

        Returns:
            List of matching blog posts
        """
        logger.info(f"Searching blogs: {query}, include_content: {include_content}")

        skip = (page - 1) * limit

        # Base projection - exclude content if not needed
        projection = {
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

        # Use text search with aggregation
        pipeline = [
            {
                "$match": {
                    "$or": [
                        {"$text": {"$search": query}},
                        {"title": {"$regex": query, "$options": "i"}},
                        {"category": {"$regex": query, "$options": "i"}},
                    ]
                }
            },
            {"$sort": {"score": {"$meta": "textScore"}}},
            {"$skip": skip},
            {"$limit": limit},
            {"$project": projection},
            {
                "$lookup": {
                    "from": "team",
                    "let": {"author_ids": "$authors"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$or": [
                                        {
                                            "$in": [
                                                {"$toString": "$_id"},
                                                "$$author_ids",
                                            ]
                                        },
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
            },
        ]

        blogs = await blog_collection.aggregate(pipeline).to_list(limit)

        # Convert to Pydantic models
        blog_posts = []
        for blog in blogs:
            if not blog.get("author_details"):
                blog["author_details"] = [
                    {"name": str(author_id), "role": "Author"}
                    for author_id in blog.get("authors", [])
                ]

            # Set content to empty string if not included
            if not include_content and "content" not in blog:
                blog["content"] = ""

            blog_posts.append(BlogPost(**serialize_document(blog)))

        logger.info(f"Found {len(blog_posts)} blogs matching: {query}")
        return blog_posts
