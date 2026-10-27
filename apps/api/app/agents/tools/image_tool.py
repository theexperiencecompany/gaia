from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.tools.core.mutations import user_id_from_config
from app.constants.log_tags import LogTag
from app.decorators import with_doc, with_rate_limiting
from app.models.agent_models import current_stream_writer
from app.services.image_service import api_generate_image
from app.templates.docstrings.image_tool_docs import GENERATE_IMAGE
from shared.py.wide_events import log


@tool
@with_rate_limiting("generate_image")
@with_doc(GENERATE_IMAGE)
async def generate_image(
    prompt: Annotated[
        str,
        "An enhanced, detailed description for image generation. Expand from the user's request to include style, composition, lighting, mood, and other visual details for optimal results.",
    ],
    config: RunnableConfig,
) -> dict[str, str]:
    try:
        log.set(tool={"name": "generate_image", "action": "generate"})
        user_id = user_id_from_config(config)
        if user_id is None:
            raise ValueError("generate_image needs the run's user id to store the image")
        writer = current_stream_writer()
        writer({"status": "generating_image"})

        image_result = await api_generate_image(
            message=prompt, user_id=user_id, improve_prompt=False
        )

        # Send image data to frontend via writer
        writer({"image_data": image_result.model_dump()})

        # Return simple confirmation message with clear instructions to prevent markdown image rendering
        return {
            "status": "success",
            "instructions": "Image generated successfully. The image is automatically displayed to the user through the interface. DO NOT include any markdown image syntax like ![alt](url) or attachment:// references in your response. Simply describe what you generated in natural language without trying to embed or link to the image.",
        }

    except Exception as e:
        writer = current_stream_writer()
        log.error(f"{LogTag.TOOL} Error generating image", error_type=type(e).__name__)
        writer({"error": f"Error generating image: {e!s}"})
        return {"status": "error", "message": f"Error generating image: {e!s}"}
