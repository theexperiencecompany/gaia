from pydantic import BaseModel


class GoalCreate(BaseModel):
    title: str
    description: str | None = ""


class GoalResponse(BaseModel):
    id: str
    title: str
    progress: int
    description: str
    roadmap: dict | None
    user_id: str
    created_at: str
    todo_project_id: str | None = None
    todo_id: str | None = None


class RoadmapUnavailableResponse(BaseModel):
    message: str
    id: str
    title: str


class UpdateNodeRequest(BaseModel):
    is_complete: bool
