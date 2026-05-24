from typing import Union

from pydantic import BaseModel


class WeatherLocation(BaseModel):
    city: str | None = None
    country: str | None = None
    region: str | None = None


class WeatherMain(BaseModel):
    temp: float
    feels_like: float
    temp_min: float
    temp_max: float
    pressure: int
    humidity: int


class WeatherWind(BaseModel):
    speed: float
    deg: int


class WeatherClouds(BaseModel):
    all: int


class WeatherSys(BaseModel):
    country: str | None = None
    sunrise: int
    sunset: int


class WeatherCondition(BaseModel):
    id: int
    main: str
    description: str
    icon: str


class ForecastDayWeather(BaseModel):
    main: str
    description: str
    icon: str


class ForecastDay(BaseModel):
    date: str
    timestamp: int
    temp_min: float
    temp_max: float
    humidity: int
    weather: ForecastDayWeather


class WeatherData(BaseModel):
    id: int | None = None
    name: str | None = None
    cod: Union[int, str] | None = None
    coord: dict[str, float] | None = None
    weather: list[WeatherCondition] | None = None
    base: str | None = None
    main: WeatherMain | None = None
    visibility: int | None = None
    wind: WeatherWind | None = None
    clouds: WeatherClouds | None = None
    dt: int | None = None
    sys: WeatherSys | None = None
    timezone: int | None = None
    location: WeatherLocation | None = None
    forecast: list[ForecastDay] | None = None  # 5-day forecast data
