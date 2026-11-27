from typing import Annotated

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool

from app.decorators import with_doc, with_rate_limiting
from app.models.agent_models import current_stream_writer
from app.models.integrations.weather import WeatherReport
from app.models.tool_card_registry import tool_card
from app.templates.docstrings.weather_tool_docs import GET_WEATHER
from app.utils.weather_utils import user_weather


@tool
@with_rate_limiting("weather_checks")
@with_doc(GET_WEATHER)
async def get_weather(
    config: RunnableConfig,  # noqa: ARG001 -- framework contract
    location: Annotated[str, "Name of the location (e.g. Mumbai,IN)"],
) -> str:
    writer = current_stream_writer()
    writer({"progress": f"Fetching weather information for {location}..."})

    weather = await user_weather(location)
    if not isinstance(weather, WeatherReport):
        # A failure or "not configured" sentence: no card, so nothing invites a made-up forecast.
        return weather
    card = tool_card("weather_data", weather)
    writer({**card, "location": location})
    weather_data = card["weather_data"]

    # Return the weather data with instructions for helpful insights
    return f"Weather data for {location}: {weather_data}\n\nThe raw weather card is visible to the user. Focus on providing helpful insights and suggestions based on these conditions (e.g., what to wear, activities to consider/avoid, health precautions, travel tips). Don't just repeat the numbers - tell them what this weather means for their day."
