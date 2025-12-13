from typing import Annotated
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from app.templates.docstrings.weather_tool_docs import GET_WEATHER
from app.decorators import with_doc, with_rate_limiting
from app.utils.weather_utils import user_weather


@tool
@with_rate_limiting("weather_checks")
@with_doc(GET_WEATHER)
async def get_weather(
    config: RunnableConfig,
    location: Annotated[str, "Name of the location (e.g. Surat,IN)"],
) -> dict | str:
    writer = get_stream_writer()
    writer({"progress": f"Fetching weather information for {location}..."})

    # Get the raw weather data
    weather_data = await user_weather(location)

    # Send weather data to frontend via writer
    writer({"weather_data": weather_data, "location": location})

    # Return simple confirmation message
    return "Weather data sent to frontend. Do not write anything else. Just send the weather data."
