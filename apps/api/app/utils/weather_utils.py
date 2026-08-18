import asyncio
from collections import defaultdict
import datetime

import httpx

from app.config.settings import settings
from app.constants.cache import ONE_HOUR_TTL
from app.constants.log_tags import LogTag
from app.db.redis import get_cache, set_cache
from app.utils.json_helpers import dict_bag, float_bag, int_bag, list_bag, text_bag
from shared.py.wide_events import log

http_async_client = httpx.AsyncClient()


async def prepare_weather_data(
    lat: float, lon: float, location_info: dict[str, object], api_key: str
) -> dict[str, object]:
    """
    Fetch and prepare weather data for a location.

    Args:
        lat (float): Latitude coordinate
        lon (float): Longitude coordinate
        location_info (Dict[str, Any]): Location information including city, country and region
        api_key (str): OpenWeatherMap API key

    Returns:
        Dict[str, Any]: Formatted weather data
    """
    # Extract location details
    city = location_info.get("city")
    country = location_info.get("country")
    region = location_info.get("region")

    # Fetch current weather and forecast data in parallel
    current_weather, forecast_data = await fetch_weather_data(lat, lon, api_key)

    # Process forecast data to create a daily summary
    daily_forecasts = process_forecast_data(forecast_data)

    # Ensure required fields exist in 'sys' object to avoid validation errors
    if "sys" in current_weather:
        # Make sure the country field is present in the sys object
        sys_data = current_weather["sys"]
        if not isinstance(sys_data, dict):
            raise TypeError(f"OpenWeatherMap 'sys' is {type(sys_data).__name__}, not an object")
        if "country" not in sys_data:
            # If we have country information from geolocation, use it
            if country:
                sys_data["country"] = country
            else:
                # Otherwise set it to an empty string to meet model requirements
                sys_data["country"] = ""
    else:
        # Create a minimal sys object if it doesn't exist
        current_weather["sys"] = {
            "country": country or "",
            "sunrise": int(datetime.datetime.now(datetime.UTC).timestamp()),
            "sunset": int(datetime.datetime.now(datetime.UTC).timestamp() + 43200),  # +12 hours
        }

    # Create combined weather object with current weather and forecast
    weather = {
        **current_weather,  # Include all current weather data
        "forecast": daily_forecasts,  # Add the forecast data
        "location": {
            "city": city,
            "country": country,
            "region": region,
        },
    }

    # Make sure the 'name' field (city name) is set
    if not weather.get("name") and city:
        weather["name"] = city

    return weather


async def fetch_weather_data(
    lat: float, lon: float, api_key: str
) -> tuple[dict[str, object], dict[str, object]]:
    """
    Fetch weather and forecast data in parallel using asyncio.

    Args:
        lat (float): Latitude coordinate
        lon (float): Longitude coordinate
        api_key (str): OpenWeatherMap API key

    Returns:
        Tuple[Dict, Dict]: A tuple containing (current_weather, forecast_data)
    """
    weather_url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric"
    forecast_url = f"http://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units=metric"

    weather_task = http_async_client.get(weather_url)
    forecast_task = http_async_client.get(forecast_url)

    # Wait for both requests to complete
    weather_response, forecast_response = await asyncio.gather(weather_task, forecast_task)

    # Process the responses
    weather_response.raise_for_status()
    forecast_response.raise_for_status()

    return weather_response.json(), forecast_response.json()


async def get_location_data(
    ip_address: str | None = None, location_name: str | None = None
) -> dict[str, object]:
    """
    Get location data either from a location name (via geocoding) or an IP address.

    Args:
        ip_address (str, optional): The user's IP address
        location_name (str, optional): Name of a specific location

    Returns:
        Dict[str, Any]: Location data including coordinates and metadata
    """
    cache_key = None
    if location_name:
        # Create a cache key for this location
        cache_key = f"weather:location:{location_name.lower().replace(' ', '_')}"

        location_data = await geocode_location(location_name)
        lat = location_data["lat"]
        lon = location_data["lon"]

        # Location details for the response
        city = location_data.get("city")
        country = location_data.get("country")
        region = location_data.get("region")

        # If city is None but we have a display name, try to extract city from it
        if not city and location_data.get("display_name"):
            parts = text_bag(location_data, "display_name").split(", ")
            city = parts[0] if parts else location_name
    else:
        # Create a cache key for the IP address
        cache_key = f"weather:ip:{ip_address}"

        # Use IP-based geolocation
        geo_response = await http_async_client.get(f"http://ip-api.com/json/{ip_address}")
        geo_response.raise_for_status()
        geolocation = geo_response.json()

        if geolocation.get("status") != "success":
            raise Exception("Failed to get location from IP address")

        lat = geolocation.get("lat")
        lon = geolocation.get("lon")
        city = geolocation.get("city")
        country = geolocation.get("country")
        region = geolocation.get("regionName")

    return {
        "lat": lat,
        "lon": lon,
        "city": city,
        "country": country,
        "region": region,
        "cache_key": cache_key,
    }


async def user_weather(location_name: str | None = None) -> dict[str, object] | str:
    """
    Fetch weather data for a specified location.

    This function has been modularized to separate concerns:
    1. Get location data (either from IP or location name)
    2. Check the cache for existing weather data
    3. Fetch and format weather data if needed
    4. Return the formatted response

    Args:
        location_name (str, optional): Name of a specific location to get weather for

    Yields:
        str: JSON-formatted weather data as server-sent events
    """
    log.set(operation="user_weather", location_name=location_name)
    try:
        api_key = settings.OPENWEATHER_API_KEY
        if not api_key:
            raise Exception("OpenWeatherMap API key is not configured")

        try:
            location_data = await get_location_data(location_name=location_name)
            cache_key = text_bag(location_data, "cache_key")

            cached_weather = await get_cache(cache_key)
            if isinstance(cached_weather, dict):
                log.debug(
                    f"{LogTag.TOOL} Using cached weather data for location",
                    cached_weather=cached_weather,
                )
                return cached_weather

            weather = await prepare_weather_data(
                float_bag(location_data, "lat"),
                float_bag(location_data, "lon"),
                location_data,
                api_key,
            )

            await set_cache(cache_key, weather, ONE_HOUR_TTL)

            return weather

        except Exception as e:
            error_msg = f"Could not find location: {location_name}"
            log.error(
                f"{LogTag.TOOL} Error getting location data",
                error=str(e),
                error_type=type(e).__name__,
            )
            return error_msg

    except Exception as e:
        log.error(
            f"{LogTag.TOOL} Error fetching weather", error=str(e), error_type=type(e).__name__
        )
        return f"Failed to fetch weather: {e!s}"


def _first_weather(item: dict[str, object]) -> dict[str, object]:
    """The first weather entry of a forecast item, or {} (checked, not assumed)."""
    for w in list_bag(item, "weather"):
        if isinstance(w, dict):
            return w
    return {}


def process_forecast_data(forecast_data: dict[str, object]) -> list[dict[str, object]]:
    """
    Process raw forecast data from OpenWeatherMap API into daily summaries.

    Args:
        forecast_data (Dict): Raw forecast data from OpenWeatherMap API

    Returns:
        List[Dict]: List of daily forecast summaries
    """

    daily_data: defaultdict[str, list[dict[str, object]]] = defaultdict(list)

    for item in list_bag(forecast_data, "list"):
        if not isinstance(item, dict):
            continue
        # Convert timestamp to date string (YYYY-MM-DD)
        dt_txt = text_bag(item, "dt_txt")
        if dt_txt:
            date = dt_txt.split(" ")[0]  # Extract date part
            daily_data[date].append(item)

    # Create a summary for each day
    daily_forecasts = []

    # Every key exists because an item was appended to it, so `items` is never empty.
    for date, items in daily_data.items():
        # Calculate min and max temperatures for the day
        temps = [float_bag(dict_bag(item, "main"), "temp") for item in items]
        min_temp = min(temps)
        max_temp = max(temps)

        # Get the most common weather condition for the day
        weather_conditions = [text_bag(_first_weather(item), "main") for item in items]
        weather_descriptions = [text_bag(_first_weather(item), "description") for item in items]

        # Use the most frequent condition (simple approach)
        from collections import Counter

        condition_counter = Counter(weather_conditions)
        description_counter = Counter(weather_descriptions)
        most_common_condition = condition_counter.most_common(1)[0][0]
        most_common_description = description_counter.most_common(1)[0][0]

        # Find the icon of an item with this condition. No default: the
        # condition came from Counter over these same items' "main" fields, so
        # some item always matches and the generator always yields.
        icon = next(
            text_bag(_first_weather(item), "icon")
            for item in items
            if text_bag(_first_weather(item), "main") == most_common_condition
        )

        # Extract timestamp from first item of the day for frontend date formatting
        timestamp = int_bag(items[0], "dt")

        # Calculate average humidity
        humidity = sum(int_bag(dict_bag(item, "main"), "humidity") for item in items) / len(items)

        # Create the daily summary
        daily_summary = {
            "date": date,
            "timestamp": timestamp,
            "temp_min": min_temp,
            "temp_max": max_temp,
            "humidity": round(humidity),
            "weather": {
                "main": most_common_condition,
                "description": most_common_description,
                "icon": icon,
            },
        }

        daily_forecasts.append(daily_summary)

    # Sort by date
    daily_forecasts.sort(key=lambda x: text_bag(x, "date"))

    return daily_forecasts


async def geocode_location(location_name: str) -> dict[str, object]:
    """
    Geocode a location name to latitude and longitude using OpenStreetMap Nominatim API.

    Args:
        location_name (str): The name of the location to geocode

    Returns:
        Dict[str, Any]: Dictionary containing location data including latitude and longitude
    """
    log.set(operation="geocode_location", location_name=location_name)
    try:
        # OpenStreetMap Nominatim API follows usage policy requiring a valid user agent
        headers = {
            "User-Agent": "GAIA-Backend/1.0"  # Properly identify your application
        }

        params: dict[str, str] = {"q": location_name, "format": "json", "limit": "1"}

        nominatim_url = "https://nominatim.openstreetmap.org/search"
        response = await http_async_client.get(nominatim_url, params=params, headers=headers)
        response.raise_for_status()

        results = response.json()

        if not results:
            raise Exception(f"Location '{location_name}' not found")

        location_data = results[0]

        # Return a dictionary with the geocoded information
        return {
            "lat": float(location_data.get("lat")),
            "lon": float(location_data.get("lon")),
            "display_name": location_data.get("display_name"),
            "city": location_data.get("address", {}).get("city"),
            "country": location_data.get("address", {}).get("country"),
            "region": location_data.get("address", {}).get("state"),
        }

    except Exception as e:
        log.error(
            f"{LogTag.TOOL} Error geocoding location",
            location_name=location_name,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise Exception(f"Failed to geocode location: {e!s}")
