import asyncio
from collections import defaultdict
import time

import httpx

from app.config.settings import settings
from app.constants.cache import ONE_HOUR_TTL
from app.constants.log_tags import LogTag
from app.db.redis import get_cache, set_cache
from app.models.integrations.weather import (
    DailyForecast,
    GeocodedLocation,
    IpApiGeolocation,
    NominatimPlace,
    OpenWeatherCondition,
    OpenWeatherCurrent,
    OpenWeatherForecast,
    OpenWeatherForecastItem,
    OpenWeatherSys,
    ResolvedLocation,
    WeatherLocation,
    WeatherReport,
)
from shared.py.wide_events import log

http_async_client = httpx.AsyncClient()


async def prepare_weather_data(
    lat: float, lon: float, location_info: ResolvedLocation, api_key: str
) -> WeatherReport:
    """Fetch and prepare weather data for a location."""
    city = location_info.city
    country = location_info.country
    region = location_info.region

    current_weather, forecast_data = await fetch_weather_data(lat, lon, api_key)

    daily_forecasts = process_forecast_data(forecast_data)

    # Create combined weather object with current weather and forecast.
    # ``exclude_unset`` keeps the response's own keys exactly (no ``name``/``sys``
    # placeholder for a key OpenWeatherMap never sent).
    weather = WeatherReport(
        **current_weather.model_dump(exclude_unset=True),
        forecast=daily_forecasts,
        location=WeatherLocation(city=city, country=country, region=region),
    )

    # Ensure required fields exist in 'sys' object to avoid validation errors
    if weather.sys is not None:
        if weather.sys.country is None:
            # Geolocation's country if we have one, else "" to meet model requirements
            weather.sys.country = country if country else ""
    else:
        # Create a minimal sys object if it doesn't exist
        weather.sys = OpenWeatherSys(
            country=country if country else "",
            sunrise=int(time.time()),
            sunset=int(time.time() + 43200),  # +12 hours
        )

    # Make sure the 'name' field (city name) is set
    if not weather.name and city:
        weather.name = city

    return weather


async def fetch_weather_data(
    lat: float, lon: float, api_key: str
) -> tuple[OpenWeatherCurrent, OpenWeatherForecast]:
    """Fetch weather and forecast data in parallel; returns (current_weather, forecast_data)."""
    weather_url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric"
    forecast_url = f"http://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units=metric"

    weather_task = http_async_client.get(weather_url)
    forecast_task = http_async_client.get(forecast_url)

    # Wait for both requests to complete
    weather_response, forecast_response = await asyncio.gather(weather_task, forecast_task)

    # Process the responses
    weather_response.raise_for_status()
    forecast_response.raise_for_status()

    return (
        OpenWeatherCurrent.model_validate(weather_response.json()),
        OpenWeatherForecast.model_validate(forecast_response.json()),
    )


async def get_location_data(
    ip_address: str | None = None, location_name: str | None = None
) -> ResolvedLocation:
    """Get location data either from a location name (via geocoding) or an IP address."""
    if location_name:
        # Create a cache key for this location
        cache_key = f"weather:location:{location_name.lower().replace(' ', '_')}"

        location_data = await geocode_location(location_name)
        lat = location_data.lat
        lon = location_data.lon

        # Location details for the response
        city = location_data.city
        country = location_data.country
        region = location_data.region

        # If city is None but we have a display name, try to extract city from it
        if not city and location_data.display_name:
            parts = location_data.display_name.split(", ")
            city = parts[0] if parts else location_name
    else:
        # Create a cache key for the IP address
        cache_key = f"weather:ip:{ip_address}"

        # Use IP-based geolocation
        geo_response = await http_async_client.get(f"http://ip-api.com/json/{ip_address}")
        geo_response.raise_for_status()
        geolocation = IpApiGeolocation.model_validate(geo_response.json())

        if geolocation.status != "success" or geolocation.lat is None or geolocation.lon is None:
            raise Exception("Failed to get location from IP address")

        lat = geolocation.lat
        lon = geolocation.lon
        city = geolocation.city
        country = geolocation.country
        region = geolocation.regionName

    return ResolvedLocation(
        lat=lat,
        lon=lon,
        city=city,
        country=country,
        region=region,
        cache_key=cache_key,
    )


async def user_weather(location_name: str | None = None) -> WeatherReport | str:
    """Fetch weather data for a specified location."""
    log.set(operation="user_weather", location_name=location_name)
    try:
        api_key = settings.OPENWEATHER_API_KEY
        if not api_key:
            raise Exception("OpenWeatherMap API key is not configured")

        try:
            location_data = await get_location_data(location_name=location_name)
            cache_key = location_data.cache_key

            cached_weather = await get_cache(cache_key, WeatherReport)
            if cached_weather:
                log.debug(
                    f"{LogTag.TOOL} Using cached weather data for location",
                    cached_weather=cached_weather,
                )
                return cached_weather

            weather = await prepare_weather_data(
                location_data.lat, location_data.lon, location_data, api_key
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


def process_forecast_data(forecast_data: OpenWeatherForecast) -> list[DailyForecast]:
    """Process raw forecast data from OpenWeatherMap API into daily summaries."""

    daily_data: defaultdict[str, list[OpenWeatherForecastItem]] = defaultdict(list)

    for item in forecast_data.items:
        # Convert timestamp to date string (YYYY-MM-DD)
        dt_txt = item.dt_txt
        if dt_txt:
            date = dt_txt.split(" ")[0]  # Extract date part
            daily_data[date].append(item)

    # Create a summary for each day
    daily_forecasts: list[DailyForecast] = []

    for date, items in daily_data.items():
        if not items:
            continue

        # Calculate min and max temperatures for the day
        temps = [item.main.temp for item in items]
        min_temp = min(temps)
        max_temp = max(temps)

        # Get the most common weather condition for the day
        weather_conditions = [item.weather[0].main for item in items]
        weather_descriptions = [item.weather[0].description for item in items]

        # Use the most frequent condition (simple approach)
        # Deferred import: stdlib import kept local to the daily aggregation loop
        from collections import Counter  # noqa: PLC0415 -- stdlib import kept local to

        condition_counter = Counter(weather_conditions)
        description_counter = Counter(weather_descriptions)
        most_common_condition = condition_counter.most_common(1)[0][0]
        most_common_description = description_counter.most_common(1)[0][0]

        # Find a matching weather icon from one of the items with this condition
        icon = next(
            (
                item.weather[0].icon
                for item in items
                if item.weather[0].main == most_common_condition
            ),
            items[0].weather[0].icon,
        )

        # Extract timestamp from first item of the day for frontend date formatting
        timestamp = items[0].dt

        # Calculate average humidity
        humidity = sum(item.main.humidity for item in items) / len(items)

        # Create the daily summary
        daily_summary = DailyForecast(
            date=date,
            timestamp=timestamp,
            temp_min=min_temp,
            temp_max=max_temp,
            humidity=round(humidity),
            weather=OpenWeatherCondition(
                main=most_common_condition,
                description=most_common_description,
                icon=icon,
            ),
        )

        daily_forecasts.append(daily_summary)

    daily_forecasts.sort(key=lambda x: x.date)

    return daily_forecasts


async def geocode_location(location_name: str) -> GeocodedLocation:
    """Geocode a location name to latitude and longitude using OpenStreetMap Nominatim API."""
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

        location_data = NominatimPlace.model_validate(results[0])

        return GeocodedLocation(
            lat=location_data.lat,
            lon=location_data.lon,
            display_name=location_data.display_name,
            city=location_data.address.city,
            country=location_data.address.country,
            region=location_data.address.state,
        )

    except Exception as e:
        log.error(
            f"{LogTag.TOOL} Error geocoding location",
            location_name=location_name,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise Exception(f"Failed to geocode location: {e!s}") from e
