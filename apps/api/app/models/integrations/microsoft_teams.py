"""Microsoft Graph v1.0 payloads the Teams tool reads.

References: https://learn.microsoft.com/en-us/graph/api/resources/user,
https://learn.microsoft.com/en-us/graph/api/resources/team,
https://learn.microsoft.com/en-us/graph/api/resources/chat,
https://learn.microsoft.com/en-us/graph/api/resources/chatmessageinfo
"""

from pydantic import BaseModel, ConfigDict, Field


class GraphUser(BaseModel):
    """``GET /me`` under ``$select=id,displayName,mail,userPrincipalName``."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    displayName: str | None = None
    mail: str | None = None
    userPrincipalName: str | None = None


class GraphTeam(BaseModel):
    """One ``value`` item of ``GET /me/joinedTeams``."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    displayName: str | None = None
    description: str | None = None


class GraphTeamsPage(BaseModel):
    """``GET /me/joinedTeams`` — an OData collection."""

    model_config = ConfigDict(extra="ignore")

    value: list[GraphTeam] = Field(default_factory=list)


class GraphItemBody(BaseModel):
    """Graph ``itemBody``."""

    model_config = ConfigDict(extra="ignore")

    content: str = ""


class GraphChatMessagePreview(BaseModel):
    """Graph ``chatMessageInfo`` — the ``lastMessagePreview`` of a chat.

    ``isRead`` is not in Graph's documented ``chatMessageInfo`` schema; the tool
    has always treated a missing value as read, so the default keeps that.
    """

    model_config = ConfigDict(extra="ignore")

    body: GraphItemBody = Field(default_factory=GraphItemBody)
    isRead: bool = True


class GraphChat(BaseModel):
    """One ``value`` item of ``GET /me/chats?$expand=lastMessagePreview``.

    ``topic`` is only set for group chats; ``lastMessagePreview`` is absent for a
    chat with no messages.
    """

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    topic: str | None = None
    chatType: str | None = None
    lastMessagePreview: GraphChatMessagePreview | None = None


class GraphChatsPage(BaseModel):
    """``GET /me/chats`` — an OData collection."""

    model_config = ConfigDict(extra="ignore")

    value: list[GraphChat] = Field(default_factory=list)
