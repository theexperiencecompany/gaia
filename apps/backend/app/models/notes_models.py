from pydantic import BaseModel, Field


class NoteModel(BaseModel):
    content: str = Field(
        ...,
        max_length=100000,
    )

    plaintext: str = Field(
        ...,
        max_length=100000,
    )


class NoteResponse(BaseModel):
    id: str
    content: str
    plaintext: str
    auto_created: bool = False
    user_id: str | None = None
    title: str | None = None
    description: str | None = None
