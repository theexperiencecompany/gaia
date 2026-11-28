"""OpenWeatherMap, Nominatim and ip-api payloads, and the weather card GAIA builds from them."""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ResponseModel


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


class OpenWeatherCoord(BaseModel):
    """Where a current-weather response is for."""

    model_config = ConfigDict(extra="allow")

    lon: float
    lat: float


class OpenWeatherCurrentCondition(BaseModel):
    """One entry of a current-weather response's weather list; the card picks its theme by id."""

    model_config = ConfigDict(extra="allow")

    id: int
    main: str
    description: str
    icon: str


class OpenWeatherMain(BaseModel):
    """The main block of a current-weather response."""

    model_config = ConfigDict(extra="allow")

    temp: float | None = None
    feels_like: float | None = None
    temp_min: float | None = None
    temp_max: float | None = None
    pressure: int | None = None
    humidity: int | None = None
    sea_level: int | None = None
    grnd_level: int | None = None


class OpenWeatherWind(BaseModel):
    """The wind block of a current-weather response."""

    model_config = ConfigDict(extra="allow")

    speed: float
    deg: int | None = None
    gust: float | None = None


class OpenWeatherClouds(BaseModel):
    """The cloud cover of a current-weather response, in percent."""

    model_config = ConfigDict(extra="allow")

    all: int


class OpenWeatherCurrent(BaseModel):
    """An OpenWeatherMap current-weather response.

    extra="allow": forwarded verbatim to the frontend weather card, so keys it
    does not declare (base, rain, snow, ...) survive.
    """

    model_config = ConfigDict(extra="allow")

    coord: OpenWeatherCoord | None = None
    weather: list[OpenWeatherCurrentCondition] | None = None
    main: OpenWeatherMain | None = None
    visibility: int | None = None
    wind: OpenWeatherWind | None = None
    clouds: OpenWeatherClouds | None = None
    dt: int | None = None
    timezone: int | None = None
    id: int | None = None
    name: str | None = None
    cod: int | None = None
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


class WeatherReport(OpenWeatherCurrent, ResponseModel):
    """The weather_data card's payload: the current weather plus GAIA's forecast and location."""

    model_config = ConfigDict(extra="allow", json_schema_serialization_defaults_required=True)

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
