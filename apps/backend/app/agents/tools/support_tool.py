"""Support LangChain tools for creating and managing support tickets."""

from typing import Annotated

from app.config.loggers import app_logger as logger
from app.decorators import with_doc
from app.templates.docstrings.support_tool_docs import (
    CREATE_SUPPORT_TICKET,
)
from app.models.support_models import (
    SupportRequestType,
)
from app.services import user_service
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer


@tool
@with_doc(CREATE_SUPPORT_TICKET)
async def create_support_ticket(
    config: RunnableConfig,
    type: Annotated[
        SupportRequestType,
        "Type of support request: 'support' for technical issues/help, 'feature' for enhancement requests",
    ],
    title: Annotated[
        str, "Brief, descriptive title of the issue or request (1-200 characters)"
    ],
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
        type: Type of support request ("support" or "feature")
        title: Brief title of the issue or request
        description: Detailed description of the issue or request

    Returns:
        String confirmation that the support ticket draft has been prepared
    """
    try:
        logger.info(
            f"Support Tool: Preparing support ticket draft with title '{title}'"
        )

        metadata = config.get("metadata", {})
        user_id = metadata.get("user_id")

        if not user_id:
            return "User authentication required to create support ticket."

        user = await user_service.get_user_by_id(user_id)

        if not user:
            return "User not found. Please ensure you are logged in."

        user_email = user.get("email")
        user_name = user.get("name", "User")

        if not user_email:
            return "User email is required to create a support ticket."

        request_type = SupportRequestType(type.lower())

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

        logger.info(f"Support ticket draft prepared for user {user_id}")

        # Return confirmation message
        ticket_type_display = (
            "feature request"
            if request_type == SupportRequestType.FEATURE
            else "support ticket"
        )
        return f"I've prepared a {ticket_type_display} draft for you to review. Please check the details and click 'Submit Ticket' when you're ready to send it to our support team."

    except Exception as e:
        logger.error(f"Error preparing support ticket: {str(e)}")
        return f"Sorry, I encountered an error while preparing your support ticket: {str(e)}"


# Export tools list for registry
tools = [
    create_support_ticket,
]
