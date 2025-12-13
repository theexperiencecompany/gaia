from typing import Annotated

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer

from app.config.loggers import image_logger as logger
from app.templates.docstrings.image_tool_docs import GENERATE_IMAGE
from app.decorators import with_doc, with_rate_limiting
from app.services.image_service import api_generate_image


@tool
@with_rate_limiting("generate_image")
@with_doc(GENERATE_IMAGE)
async def generate_image(
    prompt: Annotated[
        str,
        "An enhanced, detailed description for image generation. Expand from the user's request to include style, composition, lighting, mood, and other visual details for optimal results.",
    ],
    config: RunnableConfig,
) -> dict:
    try:
        writer = get_stream_writer()
        writer({"status": "generating_image"})

        image_result = await api_generate_image(message=prompt, improve_prompt=False)

        # Send image data to frontend via writer
        writer({"image_data": image_result})

        # Return simple confirmation message with clear instructions to prevent markdown image rendering
        return {
            "status": "success",
            "instructions": "Image generated successfully. The image is automatically displayed to the user through the interface. DO NOT include any markdown image syntax like ![alt](url) or attachment:// references in your response. Simply describe what you generated in natural language without trying to embed or link to the image.",
        }

    except Exception as e:
        writer = get_stream_writer()
        logger.error(f"Error generating image: {str(e)}")
        writer({"error": f"Error generating image: {str(e)}"})
        return {"status": "error", "message": f"Error generating image: {str(e)}"}
