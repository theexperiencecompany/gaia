"""OpenWeatherMap, Nominatim and ip-api payloads, and the weather card GAIA builds from them."""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field


class OpenWeatherCondition(BaseModel):
    """One entry of an OpenWeatherMap weather list; also the daily summary's condition."""

    model_config = ConfigDict(extra="ignore")

    main: str
    description: str
    icon: str


class OpenWeatherSys(BaseModel):
    """The sys block of a current-weather response.

    extra="allow": the whole current-weather response is forwarded verbatim
    to the frontend weather card, so undeclared keys must survive.
    """

    model_config = ConfigDict(extra="allow")

    # Absent for some places (open sea); prepare_weather_data fills it in.
    country: str | None = None
    sunrise: int | None = None
    sunset: int | None = None


class OpenWeatherCurrent(BaseModel):
    """An OpenWeatherMap current-weather response.

    extra="allow": forwarded verbatim to the frontend weather card (coord,
    main, wind, timezone, ...), which reads far more than GAIA does.
    """

    model_config = ConfigDict(extra="allow")

    name: str | None = None
    sys: OpenWeatherSys | None = None


class OpenWeatherForecastMain(BaseModel):
    """The main block of a forecast list item."""

    model_config = ConfigDict(extra="ignore")

    temp: float
    humidity: int


class OpenWeatherForecastItem(BaseModel):
    """One 3-hour slot of an OpenWeatherMap 5-day forecast."""

    model_config = ConfigDict(extra="ignore")

    dt: int
    dt_txt: str | None = None
    main: OpenWeatherForecastMain
    weather: list[OpenWeatherCondition]


class OpenWeatherForecast(BaseModel):
    """An OpenWeatherMap 5-day forecast response."""

    model_config = ConfigDict(extra="ignore")

    items: list[OpenWeatherForecastItem] = Field(default_factory=list, alias="list")


class DailyForecast(BaseModel):
    """One day of the forecast, summarised from its 3-hour slots."""

    date: str
    timestamp: int
    temp_min: float
    temp_max: float
    humidity: int
    weather: OpenWeatherCondition


class WeatherLocation(BaseModel):
    """The resolved place a weather card is for."""

    city: str | None
    country: str | None
    region: str | None


class WeatherReport(OpenWeatherCurrent):
    """The weather card payload: the current weather plus GAIA's forecast and location."""

    forecast: list[DailyForecast]
    location: WeatherLocation


class NominatimAddress(BaseModel):
    """The address block of a Nominatim search result."""

    model_config = ConfigDict(extra="ignore")

    city: str | None = None
    country: str | None = None
    state: str | None = None


class NominatimPlace(BaseModel):
    """One Nominatim /search result. Coordinates arrive as strings."""

    model_config = ConfigDict(extra="ignore")

    lat: float
    lon: float
    display_name: str | None = None
    address: NominatimAddress = Field(default_factory=NominatimAddress)


class IpApiGeolocation(BaseModel):
    """An ip-api.com /json response; every field but status is absent on failure."""

    model_config = ConfigDict(extra="ignore")

    status: str
    lat: float | None = None
    lon: float | None = None
    city: str | None = None
    country: str | None = None
    regionName: str | None = None


@dataclass(slots=True, frozen=True)
class GeocodedLocation:
    """What geocode_location resolves a place name to."""

    lat: float
    lon: float
    display_name: str | None
    city: str | None
    country: str | None
    region: str | None


@dataclass(slots=True, frozen=True)
class ResolvedLocation:
    """The coordinates, place details and cache key get_location_data resolved."""

    lat: float
    lon: float
    city: str | None
    country: str | None
    region: str | None
    cache_key: str
