from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from bson import ObjectId


class TeamMemberBase(BaseModel):
    name: str
    role: str
    avatar: Optional[str] = None
    linkedin: Optional[str] = None
    twitter: Optional[str] = None


class TeamMemberCreate(TeamMemberBase):
    pass


class TeamMemberUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    avatar: Optional[str] = None
    linkedin: Optional[str] = None
    twitter: Optional[str] = None


class TeamMember(TeamMemberBase):
    """Team member response model with proper ID handling."""

    model_config = ConfigDict(
        json_encoders={ObjectId: str},
        populate_by_name=True,
        arbitrary_types_allowed=True,
        from_attributes=True,
    )

    id: str = Field(description="Unique identifier for the team member")

    @classmethod
    def from_mongo(cls, data: dict) -> "TeamMember":
        """Create TeamMember instance from MongoDB document."""
        if "_id" in data:
            data["id"] = str(data["_id"])
        return cls(**data)
