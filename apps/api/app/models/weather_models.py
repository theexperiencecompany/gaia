from typing import Dict, List, Optional, Union
from pydantic import BaseModel


class WeatherLocation(BaseModel):
    city: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None


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
    country: Optional[str] = None
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
    id: Optional[int] = None
    name: Optional[str] = None
    cod: Optional[Union[int, str]] = None
    coord: Optional[Dict[str, float]] = None
    weather: Optional[List[WeatherCondition]] = None
    base: Optional[str] = None
    main: Optional[WeatherMain] = None
    visibility: Optional[int] = None
    wind: Optional[WeatherWind] = None
    clouds: Optional[WeatherClouds] = None
    dt: Optional[int] = None
    sys: Optional[WeatherSys] = None
    timezone: Optional[int] = None
    location: Optional[WeatherLocation] = None
    forecast: Optional[List[ForecastDay]] = None  # 5-day forecast data
