"""Support LangChain tools for creating and managing support tickets."""

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.constants.log_tags import LogTag
from app.decorators import with_doc
from app.models.integrations.composio_hooks import RunMetadata
from app.models.support_models import (
    SupportRequestType,
)
from app.services import user_service
from app.templates.docstrings.support_tool_docs import (
    CREATE_SUPPORT_TICKET,
)
from shared.py.wide_events import log


@tool
@with_doc(CREATE_SUPPORT_TICKET)
async def create_support_ticket(
    config: RunnableConfig,
    ticket_type: Annotated[
        SupportRequestType,
        "Type of support request: 'support' for technical issues/help, 'feature' for enhancement requests",
    ],
    title: Annotated[str, "Brief, descriptive title of the issue or request (1-200 characters)"],
    description: Annotated[
        str,
        "Detailed explanation of the issue, steps to reproduce, or feature details (10-5000 characters)",
    ],
) -> str:
    """
    Create a support ticket draft for the user to review and submit.

    This tool prepares support ticket data and streams it to the frontend for user review.
    The user can edit the details and submit when ready.

    Args:
        config: Runtime configuration containing user metadata
        ticket_type: Type of support request ("support" or "feature")
        title: Brief title of the issue or request
        description: Detailed description of the issue or request

    Returns:
        String confirmation that the support ticket draft has been prepared
    """
    try:
        log.set(tool={"name": "create_support_ticket", "action": "create"})
        log.info(f"{LogTag.TOOL} Preparing support ticket draft")

        user_id = RunMetadata.model_validate(config.get("metadata", {})).user_id

        if not user_id:
            return "User authentication required to create support ticket."

        user = await user_service.get_user_by_id(user_id)

        if not user:
            return "User not found. Please ensure you are logged in."

        user_email = user.email
        user_name = user.name if user.name is not None else "User"

        if not user_email:
            return "User email is required to create a support ticket."

        request_type = SupportRequestType(ticket_type.lower())

        # Prepare support ticket data for streaming
        support_ticket_data = {
            "type": request_type.value,
            "title": title.strip(),
            "description": description.strip(),
            "user_name": user_name,
            "user_email": user_email,
        }

        # Stream the support ticket data to frontend
        writer = get_stream_writer()
        writer({"progress": "Creating support ticket..."})
        writer({"support_ticket_data": [support_ticket_data]})

        log.info(f"{LogTag.TOOL} Support ticket draft prepared", user_id=user_id)

        # Return confirmation message
        ticket_type_display = (
            "feature request" if request_type == SupportRequestType.FEATURE else "support ticket"
        )
        return (
            f"Drafted a {ticket_type_display} for you. Check it over and hit "
            "Submit Ticket when it looks right."
        )

    except Exception as e:
        log.error(f"{LogTag.TOOL} Error preparing support ticket", error_type=e.__class__.__name__)
        return f"Could not prepare your support ticket: {e!s}"


# Export tools list for registry
tools = [
    create_support_ticket,
]
