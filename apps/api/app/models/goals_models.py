from pydantic import BaseModel
from typing import Optional


class GoalCreate(BaseModel):
    title: str
    description: Optional[str] = ""


class GoalResponse(BaseModel):
    id: str
    title: str
    progress: int
    description: str
    roadmap: Optional[dict]
    user_id: str
    created_at: str
    todo_project_id: Optional[str] = None
    todo_id: Optional[str] = None


class RoadmapUnavailableResponse(BaseModel):
    message: str
    id: str
    title: str


class UpdateNodeRequest(BaseModel):
    is_complete: bool
