from pydantic import BaseModel, Field


class DocumentPageModel(BaseModel):
    page_number: int = Field(
        ...,
        gt=0,
    )
    content: str = Field(...)
    # Other metadata fields can be added here


class DocumentSummaryModel(BaseModel):
    data: DocumentPageModel
    summary: str = Field(
        ...,
        max_length=100000,
    )
