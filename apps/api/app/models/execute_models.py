"""What the execute dispatch returns besides a tool's own output: its errors and the account a call ran as."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.models.agent_config import ComposioAccountSelection


class DispatchErrorKind(StrEnum):
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_ARGS = "invalid_args"
    # An internal tool reached a surface (the sandbox route) that only runs
    # integration tools — internal tools need graph runtime and stay in-graph.
    INTERNAL_TOOL = "internal_tool"
    # A registered tool outside the calling agent's tool space (a subagent
    # reaching for another integration's tools).
    OUT_OF_SCOPE = "out_of_scope"
    # `account` names no connected account of the tool's integration, or names
    # one on a tool that has no accounts to choose between.
    UNKNOWN_ACCOUNT = "unknown_account"
    # The chosen account's grant died while another account still works.
    ACCOUNT_EXPIRED = "account_expired"
    # The tool did not return within the host's bound. Its own outcome is
    # unknown, so this is the one failure a retry can duplicate.
    TIMEOUT = "timeout"


class DispatchError(BaseModel):
    kind: DispatchErrorKind
    detail: str
    hint: str


class AccountChoice(BaseModel):
    """The connected account one Composio call acts as, and what analytics says about it."""

    model_config = ConfigDict(frozen=True)

    selection: ComposioAccountSelection
    display_name: str
    is_primary: bool
    account_count: int
