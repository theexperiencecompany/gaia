"""Unit tests for weather Pydantic models."""

import pytest
from pydantic import ValidationError

from app.models.weather_models import (
    ForecastDay,
    ForecastDayWeather,
    WeatherClouds,
    WeatherCondition,
    WeatherData,
    WeatherLocation,
    WeatherMain,
    WeatherSys,
    WeatherWind,
)


# ---------------------------------------------------------------------------
# WeatherLocation
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestWeatherLocation:
    def test_valid_full(self):
        m = WeatherLocation(city="London", country="UK", region="England")
        assert m.city == "London"
        assert m.country == "UK"
        assert m.region == "England"

    def test_all_optional(self):
        m = WeatherLocation()
        assert m.city is None
        assert m.country is None
        assert m.region is None

    def test_partial(self):
        m = WeatherLocation(city="Paris")
        assert m.city == "Paris"
        assert m.country is None


# ---------------------------------------------------------------------------
# WeatherMain
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestWeatherMain:
    def test_valid(self):
        m = WeatherMain(
            temp=20.5,
            feels_like=19.0,
            temp_min=18.0,
            temp_max=23.0,
            pressure=1013,
            humidity=65,
        )
        assert m.temp == pytest.approx(20.5)
        assert m.feels_like == pytest.approx(19.0)
        assert m.pressure == 1013
        assert m.humidity == 65

    def test_negative_temps(self):
        m = WeatherMain(
            temp=-10.0,
            feels_like=-15.0,
            temp_min=-12.0,
            temp_max=-5.0,
            pressure=1020,
            humidity=80,
        )
        assert m.temp == -10.0

    @pytest.mark.parametrize(
        "field", ["temp", "feels_like", "temp_min", "temp_max", "pressure", "humidity"]
    )
    def test_missing_required_field(self, field):
        data = {
            "temp": 20.0,
            "feels_like": 19.0,
            "temp_min": 18.0,
            "temp_max": 23.0,
            "pressure": 1013,
            "humidity": 65,
        }
        del data[field]
        with pytest.raises(ValidationError):
            WeatherMain(**data)

    def test_float_coercion_for_int_fields(self):
        m = WeatherMain(
            temp=20.0,
            feels_like=19.0,
            temp_min=18.0,
            temp_max=23.0,
            pressure=1013,
            humidity=65,
        )
        assert isinstance(m.pressure, int)
        assert isinstance(m.humidity, int)


# ---------------------------------------------------------------------------
# WeatherWind
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestWeatherWind:
    def test_valid(self):
        m = WeatherWind(speed=5.5, deg=180)
        assert m.speed == pytest.approx(5.5)
        assert m.deg == 180

    def test_missing_speed(self):
        with pytest.raises(ValidationError):
            WeatherWind(deg=180)

    def test_missing_deg(self):
        with pytest.raises(ValidationError):
            WeatherWind(speed=5.5)

    def test_zero_values(self):
        m = WeatherWind(speed=0.0, deg=0)
        assert m.speed == pytest.approx(0.0)
        assert m.deg == 0


# ---------------------------------------------------------------------------
# WeatherClouds
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestWeatherClouds:
    def test_valid(self):
        m = WeatherClouds(all=75)
        assert m.all == 75

    def test_missing(self):
        with pytest.raises(ValidationError):
            WeatherClouds()

    def test_zero(self):
        m = WeatherClouds(all=0)
        assert m.all == 0

    def test_full_coverage(self):
        m = WeatherClouds(all=100)
        assert m.all == 100


# ---------------------------------------------------------------------------
# WeatherSys
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestWeatherSys:
    def test_valid_full(self):
        m = WeatherSys(country="US", sunrise=1700000000, sunset=1700040000)
        assert m.country == "US"
        assert m.sunrise == 1700000000
        assert m.sunset == 1700040000

    def test_country_optional(self):
        m = WeatherSys(sunrise=1700000000, sunset=1700040000)
        assert m.country is None

    def test_missing_sunrise(self):
        with pytest.raises(ValidationError):
            WeatherSys(sunset=1700040000)

    def test_missing_sunset(self):
        with pytest.raises(ValidationError):
            WeatherSys(sunrise=1700000000)


# ---------------------------------------------------------------------------
# WeatherCondition
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestWeatherCondition:
    def test_valid(self):
        m = WeatherCondition(id=800, main="Clear", description="clear sky", icon="01d")
        assert m.id == 800
        assert m.main == "Clear"
        assert m.description == "clear sky"
        assert m.icon == "01d"

    @pytest.mark.parametrize("field", ["id", "main", "description", "icon"])
    def test_missing_required_field(self, field):
        data = {"id": 800, "main": "Clear", "description": "clear sky", "icon": "01d"}
        del data[field]
        with pytest.raises(ValidationError):
            WeatherCondition(**data)


# ---------------------------------------------------------------------------
# ForecastDayWeather
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestForecastDayWeather:
    def test_valid(self):
        m = ForecastDayWeather(main="Rain", description="light rain", icon="10d")
        assert m.main == "Rain"
        assert m.description == "light rain"
        assert m.icon == "10d"

    @pytest.mark.parametrize("field", ["main", "description", "icon"])
    def test_missing_required_field(self, field):
        data = {"main": "Rain", "description": "light rain", "icon": "10d"}
        del data[field]
        with pytest.raises(ValidationError):
            ForecastDayWeather(**data)


# ---------------------------------------------------------------------------
# ForecastDay
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestForecastDay:
    def _base_data(self, **overrides):
        data = {
            "date": "2025-06-01",
            "timestamp": 1748736000,
            "temp_min": 18.0,
            "temp_max": 28.0,
            "humidity": 55,
            "weather": {"main": "Clouds", "description": "overcast", "icon": "04d"},
        }
        data.update(overrides)
        return data

    def test_valid(self):
        m = ForecastDay(**self._base_data())
        assert m.date == "2025-06-01"
        assert m.timestamp == 1748736000
        assert m.temp_min == pytest.approx(18.0)
        assert m.temp_max == pytest.approx(28.0)
        assert m.humidity == 55
        assert isinstance(m.weather, ForecastDayWeather)
        assert m.weather.main == "Clouds"

    def test_missing_weather(self):
        data = self._base_data()
        del data["weather"]
        with pytest.raises(ValidationError):
            ForecastDay(**data)

    def test_missing_date(self):
        data = self._base_data()
        del data["date"]
        with pytest.raises(ValidationError):
            ForecastDay(**data)

    def test_negative_temps(self):
        m = ForecastDay(**self._base_data(temp_min=-5.0, temp_max=-1.0))
        assert m.temp_min == -5.0


# ---------------------------------------------------------------------------
# WeatherData
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestWeatherData:
    def test_all_optional_defaults(self):
        m = WeatherData()
        assert m.id is None
        assert m.name is None
        assert m.cod is None
        assert m.coord is None
        assert m.weather is None
        assert m.base is None
        assert m.main is None
        assert m.visibility is None
        assert m.wind is None
        assert m.clouds is None
        assert m.dt is None
        assert m.sys is None
        assert m.timezone is None
        assert m.location is None
        assert m.forecast is None

    def test_full_weather_data(self):
        m = WeatherData(
            id=2643743,
            name="London",
            cod=200,
            coord={"lon": -0.1257, "lat": 51.5085},
            weather=[
                WeatherCondition(
                    id=800, main="Clear", description="clear sky", icon="01d"
                )
            ],
            base="stations",
            main=WeatherMain(
                temp=15.0,
                feels_like=14.0,
                temp_min=13.0,
                temp_max=17.0,
                pressure=1012,
                humidity=72,
            ),
            visibility=10000,
            wind=WeatherWind(speed=3.6, deg=250),
            clouds=WeatherClouds(all=0),
            dt=1700000000,
            sys=WeatherSys(country="GB", sunrise=1700000000, sunset=1700040000),
            timezone=0,
            location=WeatherLocation(city="London", country="GB"),
            forecast=[
                ForecastDay(
                    date="2025-06-01",
                    timestamp=1748736000,
                    temp_min=12.0,
                    temp_max=18.0,
                    humidity=60,
                    weather=ForecastDayWeather(
                        main="Clouds", description="scattered clouds", icon="03d"
                    ),
                )
            ],
        )
        assert m.name == "London"
        assert m.cod == 200
        assert len(m.weather) == 1  # type: ignore[arg-type]
        assert m.main.temp == pytest.approx(15.0)  # type: ignore[union-attr]
        assert len(m.forecast) == 1  # type: ignore[arg-type]

    def test_cod_can_be_string(self):
        m = WeatherData(cod="404")
        assert m.cod == "404"

    def test_cod_can_be_int(self):
        m = WeatherData(cod=200)
        assert m.cod == 200

    def test_nested_weather_conditions(self):
        conditions = [
            WeatherCondition(id=800, main="Clear", description="clear sky", icon="01d"),
            WeatherCondition(
                id=801, main="Clouds", description="few clouds", icon="02d"
            ),
        ]
        m = WeatherData(weather=conditions)
        assert len(m.weather) == 2  # type: ignore[arg-type]
        assert m.weather[0].main == "Clear"  # type: ignore[index]
        assert m.weather[1].main == "Clouds"  # type: ignore[index]

    def test_forecast_list(self):
        forecast = [
            ForecastDay(
                date=f"2025-06-0{i}",
                timestamp=1748736000 + i * 86400,
                temp_min=15.0 + i,
                temp_max=25.0 + i,
                humidity=50 + i,
                weather=ForecastDayWeather(
                    main="Clear", description="clear sky", icon="01d"
                ),
            )
            for i in range(1, 6)
        ]
        m = WeatherData(forecast=forecast)
        assert len(m.forecast) == 5  # type: ignore[arg-type]

    def test_coord_dict(self):
        m = WeatherData(coord={"lon": -73.99, "lat": 40.73})
        assert m.coord["lon"] == -73.99  # type: ignore[index]
        assert m.coord["lat"] == pytest.approx(40.73)  # type: ignore[index]

    def test_location_nested(self):
        m = WeatherData(
            location=WeatherLocation(city="Tokyo", country="JP", region="Kanto")
        )
        assert m.location.city == "Tokyo"  # type: ignore[union-attr]
        assert m.location.region == "Kanto"  # type: ignore[union-attr]
