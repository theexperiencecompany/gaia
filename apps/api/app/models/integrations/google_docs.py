"""Google Docs payloads the Docs tools read.

Reference: https://developers.google.com/workspace/docs/api/reference/rest/v1/documents
Nothing here is forwarded verbatim, so every model ignores the rest of the resource.
"""

from pydantic import BaseModel, ConfigDict, Field


class GoogleDocsTextRun(BaseModel):
    """``TextRun`` — ``content`` is the run's text and is always present."""

    model_config = ConfigDict(extra="ignore")

    content: str


class GoogleDocsParagraphElement(BaseModel):
    """``ParagraphElement`` — a union; only the ``textRun`` member is read."""

    model_config = ConfigDict(extra="ignore")

    textRun: GoogleDocsTextRun | None = None


class GoogleDocsParagraphStyle(BaseModel):
    """``ParagraphStyle`` — ``namedStyleType`` is the heading level marker."""

    model_config = ConfigDict(extra="ignore")

    namedStyleType: str | None = None


class GoogleDocsParagraph(BaseModel):
    """``Paragraph`` — its runs and named style."""

    model_config = ConfigDict(extra="ignore")

    paragraphStyle: GoogleDocsParagraphStyle | None = None
    elements: list[GoogleDocsParagraphElement] = Field(default_factory=list)


class GoogleDocsStructuralElement(BaseModel):
    """``StructuralElement`` — a union; only ``paragraph`` members are read.

    ``startIndex`` defaults to 0 because Google omits zero-valued integers.
    """

    model_config = ConfigDict(extra="ignore")

    startIndex: int = 0
    paragraph: GoogleDocsParagraph | None = None


class GoogleDocsBody(BaseModel):
    """``Body`` — the document's structural elements."""

    model_config = ConfigDict(extra="ignore")

    content: list[GoogleDocsStructuralElement] = Field(default_factory=list)


class GoogleDocsDocument(BaseModel):
    """``documents.get`` — only ``body`` is read."""

    model_config = ConfigDict(extra="ignore")

    body: GoogleDocsBody


class GoogleDocsHeading(BaseModel):
    """One heading extracted from a document, as the TOC tool reports it."""

    model_config = ConfigDict(extra="forbid")

    level: int
    text: str
    start_index: int


class GoogleDocsToolExecution(BaseModel):
    """Composio's ``ToolExecutionResponse`` envelope for the GOOGLEDOCS_* tools.

    ``data`` stays ``object``: Composio has answered with the document as a
    JSON-encoded string as well as a dict, and the insert result is forwarded
    verbatim, so it is narrowed only where it is read.
    """

    model_config = ConfigDict(extra="ignore")

    successful: bool
    error: str | None = None
    data: object = None
