"""
Blog service module for handling blog-related operations with optimization.
"""

from fastapi import HTTPException, status

from app.db.mongodb.collections import blog_collection
from app.db.utils import serialize_document
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
        """
        Get all blog posts with pagination and populated author details.

        Args:
            page: Page number (1-based)
            limit: Number of blogs per page
            include_content: Whether to include blog content (set to False for list views for better performance)

        Returns:
            List of blog posts with author details
        """
        log.info(
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

        log.set(blog={"page": page, "limit": limit, "result_count": len(blog_posts)})
        log.info(f"Retrieved {len(blog_posts)} blogs")
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
        log.info(f"Fetching blog by slug: {slug}")

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
            log.warning(f"Blog not found: {slug}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blog post not found")

        blog = blogs[0]

        # Handle fallback for missing authors
        if not blog.get("author_details"):
            blog["author_details"] = [
                {"name": str(author_id), "role": "Author"} for author_id in blog.get("authors", [])
            ]

        log.info(f"Retrieved blog: {slug}")
        return BlogPost(**serialize_document(blog))

    @staticmethod
    async def get_blog_count() -> int:
        """Get total count of blog posts."""
        return await blog_collection.count_documents({})

    @staticmethod
    async def search_blogs(
        query: str, page: int = 1, limit: int = 20, include_content: bool = True
    ) -> list[BlogPost]:
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
        log.info(f"Searching blogs: {query}, include_content: {include_content}")

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

        log.set(blog={"search_query": query, "result_count": len(blog_posts)})
        log.info(f"Found {len(blog_posts)} blogs matching: {query}")
        return blog_posts
