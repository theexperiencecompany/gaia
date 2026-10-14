"""LinkedIn REST/v2 payloads the LinkedIn tool reads and sends.

Reference: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/
"""

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.models.composio_schemas.linkedin import LinkedInUserInfo


class LinkedInRequest(BaseModel):
    """A Rest.li request body: camelCase on the wire, unset blocks left out."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    def body(self) -> dict[str, object]:
        return self.model_dump(by_alias=True, exclude_none=True)


class LinkedInMediaContent(LinkedInRequest):
    title: str
    id: str


class LinkedInImageRef(LinkedInRequest):
    id: str


class LinkedInMultiImageContent(LinkedInRequest):
    images: list[LinkedInImageRef]


class LinkedInArticleContent(LinkedInRequest):
    source: str
    title: str | None = None
    description: str | None = None
    thumbnail: str | None = None


class LinkedInPostContent(LinkedInRequest):
    """Exactly one of the three blocks is set, by media type."""

    media: LinkedInMediaContent | None = None
    multi_image: LinkedInMultiImageContent | None = None
    article: LinkedInArticleContent | None = None


class LinkedInPostDistribution(LinkedInRequest):
    feed_distribution: str = "MAIN_FEED"
    target_entities: list[str] = Field(default_factory=list)
    third_party_distribution_channels: list[str] = Field(default_factory=list)


class LinkedInPostRequest(LinkedInRequest):
    """Request body for POST /rest/posts."""

    author: str
    commentary: str
    visibility: str
    distribution: LinkedInPostDistribution = Field(default_factory=LinkedInPostDistribution)
    lifecycle_state: str = "PUBLISHED"
    is_reshare_disabled_by_author: bool = False
    content: LinkedInPostContent | None = None


class LinkedInCommentMessage(LinkedInRequest):
    text: str


class LinkedInCommentRequest(LinkedInRequest):
    """Request body for POST /rest/socialActions/{urn}/comments."""

    actor: str
    message: LinkedInCommentMessage
    parent_comment: str | None = None


class LinkedInReactionRequest(LinkedInRequest):
    """Request body for POST /rest/socialActions/{urn}/likes."""

    actor: str
    reaction_type: str


class LinkedInRestliResponse(BaseModel):
    """The proxy's full reply to a Rest.li write.

    A created resource's id travels in the ``x-restli-id`` header (lower-cased
    by the proxy client); ``data`` is the created entity for comments and an
    empty body for posts, so it stays ``object`` until narrowed.
    """

    model_config = ConfigDict(extra="ignore")

    status: int
    data: object = None
    headers: dict[str, str] = Field(default_factory=dict)


class LinkedInCreatedComment(BaseModel):
    """The comment ``POST …/comments`` echoes back."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None


class LinkedInAuditStamp(BaseModel):
    """``created`` / ``lastModified`` — epoch milliseconds plus the acting URN."""

    model_config = ConfigDict(extra="ignore")

    time: int


class LinkedInPaging(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total: int | None = None


class LinkedInComment(BaseModel):
    """One ``GET …/comments`` element; ``parentComment`` only on replies."""

    model_config = ConfigDict(extra="ignore", alias_generator=to_camel, populate_by_name=True)

    id: str
    actor: str
    message: LinkedInCommentMessage
    created: LinkedInAuditStamp
    parent_comment: str | None = None


class LinkedInCommentList(BaseModel):
    """``GET /rest/socialActions/{urn}/comments``."""

    model_config = ConfigDict(extra="ignore")

    elements: list[LinkedInComment] = Field(default_factory=list)
    paging: LinkedInPaging | None = None


class LinkedInReaction(BaseModel):
    """One ``GET …/likes`` element; the legacy Like has no ``reactionType``."""

    model_config = ConfigDict(extra="ignore", alias_generator=to_camel, populate_by_name=True)

    actor: str
    reaction_type: str = "LIKE"
    created: LinkedInAuditStamp


class LinkedInReactionList(BaseModel):
    """``GET /rest/socialActions/{urn}/likes``."""

    model_config = ConfigDict(extra="ignore")

    elements: list[LinkedInReaction] = Field(default_factory=list)
    paging: LinkedInPaging | None = None


class LinkedInProfile(LinkedInUserInfo):
    """GET /v2/userinfo: the OpenID Connect claims the context tool reports.

    Extends LinkedInUserInfo from linkedin_utils; sub is mandatory in OIDC.
    """

    model_config = ConfigDict(extra="ignore")

    sub: str
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    email: str | None = None
    picture: str | None = None


class LinkedInShareCommentary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str


class LinkedInShareContent(BaseModel):
    model_config = ConfigDict(extra="ignore", alias_generator=to_camel, populate_by_name=True)

    share_commentary: LinkedInShareCommentary | None = None


class LinkedInSpecificContent(BaseModel):
    """The ``specificContent`` union keyed by its fully qualified type name."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    share_content: LinkedInShareContent | None = Field(
        default=None, alias="com.linkedin.ugc.ShareContent"
    )


class LinkedInVisibility(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    member_network_visibility: str | None = Field(
        default=None, alias="com.linkedin.ugc.MemberNetworkVisibility"
    )


class LinkedInUgcPost(BaseModel):
    """One ``GET /v2/ugcPosts?q=authors`` element."""

    model_config = ConfigDict(extra="ignore", alias_generator=to_camel, populate_by_name=True)

    id: str
    created: LinkedInAuditStamp
    specific_content: LinkedInSpecificContent = Field(default_factory=LinkedInSpecificContent)
    visibility: LinkedInVisibility = Field(default_factory=LinkedInVisibility)

    @property
    def text(self) -> str:
        share = self.specific_content.share_content
        return share.share_commentary.text if share and share.share_commentary else ""


class LinkedInUgcPostList(BaseModel):
    model_config = ConfigDict(extra="ignore")

    elements: list[LinkedInUgcPost] = Field(default_factory=list)
