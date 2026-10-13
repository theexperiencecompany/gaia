"""Single-purpose file-share grant payload (stateless, HMAC-signed).

No database row backs a grant: the token itself carries the file reference and
expiry, authenticated with itsdangerous (same pattern as the unsubscribe
tokens). Serve-counting is deliberately absent — this matches S3-presigned-URL
semantics (unguessable + expiring bearer), not a use-counter. True single-use
would need server-side state on the read path; if that is ever demanded, the
registry's before-hooks are sync-only, so it wants async-hook support first.
"""

from typing import Literal

from pydantic import BaseModel, Field


class ShareGrantPayload(BaseModel):
    """The signed file reference a share URL carries."""

    user_id: str
    workspace_rel_path: str
    filename: str
    mimetype: str
    max_bytes: int = Field(gt=0)
    expires_at: float
    nonce: str
    purpose: Literal["composio_fetch"] = "composio_fetch"
    tool: str | None = None
    toolkit: str | None = None
