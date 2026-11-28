"""Test data factories for GAIA API tests."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

from bson import ObjectId
from composio.types import Tool
import composio_client
from composio_client.types.tool_list_response import ItemDeprecated, ItemToolkit
import httpx

from app.constants.chat import ConversationSource
from app.models.connector_models import ConnectorSpec
from app.models.conversation_frame_models import EntryFrame, StateFrame
from app.models.conversation_log_models import DisplayState, Entry
from app.models.conversation_models import StoredConversation
from app.models.oauth_models import OAuthIntegration
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser
from shared.py.conversation_wire import ReplyItem, ReplyOutcome, ToolTimeline

#: The conversation a unit test projects its screen for.
CONVERSATION_ID = "c1"


def make_user_id() -> str:
    """Return a fresh GAIA user id: a real ObjectId, as UserId and every capture require."""
    return str(ObjectId())


def make_todo(title: str, *labels: str, user_id: str | None = None, **fields: Any) -> TodoDocument:
    """Build a todo titled title, its id the title unless fields name one; open unless fields say."""
    return TodoDocument.model_validate(
        {
            "id": title,
            "user_id": user_id or make_user_id(),
            "title": title,
            "labels": list(labels),
            **fields,
        }
    )


def make_authenticated_user(**overrides: Any) -> AuthenticatedUser:
    """Build the request.state.user a signed-in test caller carries.

    Built as a WorkOS session; overrides are AuthenticatedUser fields.
    """
    defaults: dict[str, Any] = {
        "user_id": make_user_id(),
        "auth_provider": "workos",
        "email": "test@example.com",
        "name": "Test User",
        "created_at": datetime.now(UTC),
        "is_active": True,
    }
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def make_loaded_conversation(
    conversation_id: str,
    user_id: str,
    entries: Sequence[Entry],
    *,
    created_at: str = "2026-01-01T10:00:00+00:00",
) -> StoredConversation:
    """Build a conversation as a load returns it: its entries in log order under a settled head."""
    return StoredConversation(
        user_id=user_id,
        conversation_id=conversation_id,
        source=ConversationSource.WEB,
        createdAt=created_at,
        entries=[
            EntryFrame(seq=seq, at=datetime(2026, 1, 1, tzinfo=UTC), entry=entry)
            for seq, entry in enumerate(entries, 1)
        ],
        state=StateFrame(head=len(entries), display=DisplayState.IDLE, work=()),
    )


def make_user(**overrides) -> dict:
    defaults = {
        "user_id": make_user_id(),
        "email": "test@example.com",
        "name": "Test User",
        "created_at": datetime.now(UTC).isoformat(),
        "is_active": True,
        "plan": "free",
        "onboarding_completed": True,
    }
    defaults.update(overrides)
    return defaults


def make_state(**overrides) -> dict:
    """Build a dict-shaped agent state for tests.

    The compiled graph state is a plain dict (TypedDict) at runtime, so a dict
    with the messages channel plus a few representative extra keys is a faithful
    stand-in and exercises middleware passthrough of non-schema keys.
    """
    defaults = {
        "query": "Hello, how are you?",
        "messages": [],
        "current_datetime": datetime.now(UTC).isoformat(),
        "memory_user_id": str(uuid4()),
        "memories": [],
        "memories_stored": False,
        "conversation_id": str(uuid4()),
    }
    defaults.update(overrides)
    return defaults


def make_composio_tool(
    slug: str = "GMAIL_FETCH_MESSAGES",
    output_parameters: dict | None = None,
) -> Tool:
    """Build the minimum Composio tool descriptor wrap_tool needs."""
    return Tool(
        slug=slug,
        name=slug,
        description="Fetch messages.",
        # `title` is load-bearing: the wrapper builds a pydantic model class from
        # each schema and uses it as the class name.
        input_parameters={"type": "object", "title": "GmailFetchMessagesRequest", "properties": {}},
        output_parameters=output_parameters
        or {"type": "object", "title": "GmailFetchMessagesResponse", "properties": {}},
        toolkit=ItemToolkit(slug="gmail", name="Gmail", logo=""),
        tags=[],
        scopes=[],
        version="latest",
        available_versions=["latest"],
        # Mixed casing is the SDK's, not a typo: `displayName` is aliased while its
        # siblings are not.
        deprecated=ItemDeprecated.model_validate(
            {
                "available_versions": ["latest"],
                "displayName": "Fetch messages",
                "is_deprecated": False,
                "toolkit": {"slug": "gmail", "name": "Gmail", "logo": ""},
                "version": "latest",
            }
        ),
        is_deprecated=False,
        no_auth=False,
    )


def make_tool_call(name: str, args: dict | None = None, call_id: str | None = None) -> dict:
    return {
        "name": name,
        "args": args or {},
        "id": call_id or f"call_{uuid4().hex[:24]}",
        "type": "tool_call",
    }


def make_config(
    user_id: str | None = None,
    thread_id: str | None = None,
    **overrides,
) -> dict:
    configurable = {
        "user_id": user_id or make_user_id(),
        "thread_id": thread_id or str(uuid4()),
    }
    configurable.update(overrides.pop("configurable", {}))
    config = {
        "configurable": configurable,
    }
    config.update(overrides)
    return config


def make_mcp_config(**overrides) -> dict:
    defaults = {
        "server_name": "test-mcp-server",
        "server_url": "http://localhost:8080",  # NOSONAR
        "transport": "sse",
        "enabled": True,
        "tools": [],
    }
    defaults.update(overrides)
    return defaults


def make_integration(provider: str, **overrides) -> dict:
    defaults = {
        "integration_id": str(uuid4()),
        "provider": provider,
        "user_id": make_user_id(),
        "status": "active",
        "credentials": {
            "access_token": f"test_token_{uuid4().hex[:8]}",
            "refresh_token": f"test_refresh_{uuid4().hex[:8]}",
        },
        "created_at": datetime.now(UTC).isoformat(),
    }
    defaults.update(overrides)
    return defaults


def make_integration_config(
    integration_id: str = "gmail",
    name: str = "Gmail",
    managed_by: str = "composio",
    associated_triggers: list | None = None,
    metadata_config: object | None = None,
):
    """Build a lightweight mock integration config object."""
    config = MagicMock()
    config.id = integration_id
    config.name = name
    config.managed_by = managed_by
    config.associated_triggers = associated_triggers or []
    config.metadata_config = metadata_config
    return config


def make_composio_not_found(body: object, message: str) -> composio_client.NotFoundError:
    """Build the 404 the Composio SDK raises, with its error body and message."""
    request = httpx.Request("POST", "https://backend.composio.dev/api/v3/tools/execute")
    return composio_client.NotFoundError(
        message, response=httpx.Response(404, request=request, json=body), body=body
    )


def make_oauth_integration(**overrides: object) -> OAuthIntegration:
    """Build an OAuthIntegration with test defaults; override any field by name."""
    overrides.setdefault("id", overrides.pop("integration_id", "platform-int"))
    params: dict[str, object] = {
        "name": "Platform Integration",
        "description": "A platform integration",
        "category": "productivity",
        "provider": "google",
        "scopes": [],
        "available": True,
        "managed_by": "internal",
        "mcp_config": None,
        "composio_config": None,
        "subagent_config": None,
        "is_featured": False,
        "display_priority": 0,
        **overrides,
    }
    return OAuthIntegration.model_validate(params)


def make_reply_item(text: str, *, reply_id: str = "r1", seq: int = 1) -> ReplyItem:
    """Build a settled reply's screen item carrying only its text, as one bubble."""
    return ReplyItem(
        id=reply_id,
        seq=seq,
        at=datetime.now(UTC),
        bubbles=(text,),
        tool_data=(),
        timeline=ToolTimeline(),
        follow_up_actions=(),
        image=None,
        pinned=False,
        quote=None,
        outcome=ReplyOutcome.ANSWERED,
        failure=None,
        failure_line=None,
        narrates=(),
        retry_target=None,
        files=(),
    )


_CONNECTOR_PRESETS: dict[str, dict[str, Any]] = {
    "cli": {
        "kind": "cli",
        "provider_domain": "github.com",
        "capability": "Read your GitHub repositories and issues",
        "command": "gh",
        "credential": {"env": ["GH_TOKEN"], "token_url": "https://github.com/settings/tokens"},
        "risk": {
            "read_commands": ["api", "repo list", "issue list"],
            "write_flags": ["-X", "--method", "-f"],
        },
        "allowed_hosts": ["api.github.com", "github.com"],
        "verify": {"args": ["api", "user"], "identity": {"json_path": "login"}},
    },
    "rest": {
        "kind": "rest",
        "provider_domain": "resend.com",
        "capability": "Send email and manage domains with Resend",
        "rest": {"base_url": "https://api.resend.com"},
        "allowed_hosts": ["api.resend.com"],
        "verify": {"args": ["GET", "/domains"]},
    },
    "sdk": {
        "kind": "sdk",
        "provider_domain": "openai.com",
        "capability": "Call OpenAI models",
        "sdk_runtime": "python",
        "install": [{"manager": "pip", "name": "openai", "version": "1.109.1"}],
        "credential": {"env": ["OPENAI_API_KEY"]},
        "allowed_hosts": ["api.openai.com"],
        "verify": {"args": ["-c", "import openai; print(len(openai.OpenAI().models.list().data))"]},
    },
}


def make_connector_spec(kind: str = "cli", **overrides: Any) -> ConnectorSpec:
    """Build a valid connector spec per preset: gh (cli), Resend (rest), openai (sdk)."""
    return ConnectorSpec.model_validate({**_CONNECTOR_PRESETS[kind], **overrides})
