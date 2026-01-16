"""
Team service with Redis caching and proper error handling.
"""

from typing import List

from app.config.loggers import common_logger as logger
from app.constants.cache import DEFAULT_CACHE_TTL, TEAM_CACHE_PREFIX
from app.db.mongodb.collections import team_collection
from app.db.redis import delete_cache, get_cache, set_cache
from app.models.team_models import TeamMember, TeamMemberCreate, TeamMemberUpdate
from bson import ObjectId
from fastapi import HTTPException, status

TEAM_LIST_CACHE_KEY = f"{TEAM_CACHE_PREFIX}:list"


class TeamService:
    """Service for team member operations with caching."""

    @staticmethod
    async def get_all_team_members() -> List[TeamMember]:
        """Get all team members with caching."""
        try:
            # Try to get from cache first
            cached_members = await get_cache(TEAM_LIST_CACHE_KEY)
            if cached_members:
                logger.debug("Retrieved team members from cache")
                return [TeamMember(**member) for member in cached_members]

            # Fetch from database
            members_data = await team_collection.find().to_list(100)
            if not members_data:
                return []

            # Convert to response models
            members = [TeamMember.from_mongo(member) for member in members_data]

            # Cache the result
            cache_data = [member.model_dump() for member in members]
            await set_cache(TEAM_LIST_CACHE_KEY, cache_data, DEFAULT_CACHE_TTL)
            logger.debug(f"Cached {len(members)} team members")

            return members

        except Exception as e:
            logger.error(f"Error fetching team members: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve team members",
            )

    @staticmethod
    async def get_team_member_by_id(member_id: str) -> TeamMember:
        """Get a specific team member by ID with caching."""
        try:
            # Validate ObjectId format
            if not ObjectId.is_valid(member_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid team member ID format",
                )

            cache_key = f"{TEAM_CACHE_PREFIX}:member:{member_id}"

            # Try cache first
            cached_member = await get_cache(cache_key)
            if cached_member:
                logger.debug(f"Retrieved team member {member_id} from cache")
                return TeamMember(**cached_member)

            # Fetch from database
            member_data = await team_collection.find_one({"_id": ObjectId(member_id)})
            if not member_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Team member not found",
                )

            member = TeamMember.from_mongo(member_data)

            # Cache the result
            await set_cache(cache_key, member.model_dump(), DEFAULT_CACHE_TTL)
            logger.debug(f"Cached team member {member_id}")

            return member

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error fetching team member {member_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve team member",
            )

    @staticmethod
    async def create_team_member(member_data: TeamMemberCreate) -> TeamMember:
        """Create a new team member and invalidate cache."""
        try:
            # Insert into database
            member_dict = member_data.model_dump()
            result = await team_collection.insert_one(member_dict)

            # Fetch the created member
            created_member_data = await team_collection.find_one(
                {"_id": result.inserted_id}
            )
            if not created_member_data:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to retrieve created team member",
                )

            created_member = TeamMember.from_mongo(created_member_data)

            # Invalidate list cache
            await delete_cache(TEAM_LIST_CACHE_KEY)
            logger.debug("Invalidated team list cache after creation")

            return created_member

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating team member: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create team member",
            )

    @staticmethod
    async def update_team_member(
        member_id: str, update_data: TeamMemberUpdate
    ) -> TeamMember:
        """Update a team member and invalidate cache."""
        try:
            # Validate ObjectId format
            if not ObjectId.is_valid(member_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid team member ID format",
                )

            # Prepare update data (exclude None values)
            update_dict = {
                k: v for k, v in update_data.model_dump().items() if v is not None
            }
            if not update_dict:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No valid fields to update",
                )

            # Update in database
            result = await team_collection.update_one(
                {"_id": ObjectId(member_id)}, {"$set": update_dict}
            )

            if result.matched_count == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Team member not found",
                )

            # Fetch updated member
            updated_member_data = await team_collection.find_one(
                {"_id": ObjectId(member_id)}
            )
            if not updated_member_data:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to retrieve updated team member",
                )

            updated_member = TeamMember.from_mongo(updated_member_data)

            # Invalidate caches
            cache_key = f"{TEAM_CACHE_PREFIX}:member:{member_id}"
            await delete_cache(cache_key)
            await delete_cache(TEAM_LIST_CACHE_KEY)
            logger.debug(f"Invalidated cache for team member {member_id}")

            return updated_member

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating team member {member_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update team member",
            )

    @staticmethod
    async def delete_team_member(member_id: str) -> None:
        """Delete a team member and invalidate cache."""
        try:
            # Validate ObjectId format
            if not ObjectId.is_valid(member_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid team member ID format",
                )

            # Delete from database
            result = await team_collection.delete_one({"_id": ObjectId(member_id)})

            if result.deleted_count == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Team member not found",
                )

            # Invalidate caches
            cache_key = f"{TEAM_CACHE_PREFIX}:member:{member_id}"
            await delete_cache(cache_key)
            await delete_cache(TEAM_LIST_CACHE_KEY)
            logger.debug(f"Invalidated cache for deleted team member {member_id}")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting team member {member_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete team member",
            )
