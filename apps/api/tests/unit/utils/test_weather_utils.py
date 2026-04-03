"""Comprehensive unit tests for app.utils.weather_utils."""

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.utils.weather_utils import (
    fetch_weather_data,
    geocode_location,
    get_location_data,
    prepare_weather_data,
    process_forecast_data,
    user_weather,
)

# ---------------------------------------------------------------------------
# Helpers / Factories
# ---------------------------------------------------------------------------

FAKE_API_KEY = "test-api-key-12345"  # pragma: allowlist secret


def _make_forecast_item(
    date: str,
    hour: str,
    temp: float,
    humidity: int,
    condition: str,
    description: str,
    icon: str,
    dt: int = 1700000000,
) -> Dict[str, Any]:
    """Build a single forecast list item matching the OpenWeatherMap schema."""
    return {
        "dt": dt,
        "dt_txt": f"{date} {hour}",
        "main": {"temp": temp, "humidity": humidity},
        "weather": [{"main": condition, "description": description, "icon": icon}],
    }


def _make_forecast_data(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"list": items}


def _make_current_weather(
    *,
    name: str = "London",
    country: str = "GB",
    temp: float = 15.0,
    include_sys: bool = True,
) -> Dict[str, Any]:
    """Build a minimal current-weather response."""
    data: Dict[str, Any] = {
        "name": name,
        "main": {"temp": temp, "humidity": 72},
        "weather": [{"main": "Clouds", "description": "overcast", "icon": "04d"}],
    }
    if include_sys:
        data["sys"] = {
            "country": country,
            "sunrise": 1700000000,
            "sunset": 1700043200,
        }
    return data


def _mock_httpx_response(json_data: Any, status_code: int = 200) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message="error",
            request=MagicMock(),
            response=resp,
        )
    return resp


# ---------------------------------------------------------------------------
# process_forecast_data
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessForecastData:
    """Tests for the synchronous process_forecast_data helper."""

    def test_empty_list_returns_empty(self) -> None:
        result = process_forecast_data({"list": []})
        assert result == []

    def test_missing_list_key_returns_empty(self) -> None:
        result = process_forecast_data({})
        assert result == []

    def test_single_day_single_item(self) -> None:
        items = [
            _make_forecast_item(
                "2024-01-15", "12:00:00", 10.0, 60, "Clear", "clear sky", "01d"
            ),
        ]
        result = process_forecast_data(_make_forecast_data(items))
        assert len(result) == 1
        day = result[0]
        assert day["date"] == "2024-01-15"
        assert day["temp_min"] == pytest.approx(10.0)
        assert day["temp_max"] == pytest.approx(10.0)
        assert day["humidity"] == 60
        assert day["weather"]["main"] == "Clear"
        assert day["weather"]["description"] == "clear sky"
        assert day["weather"]["icon"] == "01d"

    def test_single_day_multiple_items_aggregates(self) -> None:
        items = [
            _make_forecast_item(
                "2024-01-15", "06:00:00", 5.0, 80, "Clouds", "overcast", "04d"
            ),
            _make_forecast_item(
                "2024-01-15", "12:00:00", 12.0, 50, "Clear", "clear sky", "01d"
            ),
            _make_forecast_item(
                "2024-01-15", "18:00:00", 8.0, 70, "Clouds", "broken clouds", "04d"
            ),
        ]
        result = process_forecast_data(_make_forecast_data(items))
        assert len(result) == 1
        day = result[0]
        assert day["temp_min"] == pytest.approx(5.0)
        assert day["temp_max"] == pytest.approx(12.0)
        assert day["humidity"] == round((80 + 50 + 70) / 3)
        # "Clouds" appears twice, so it is the most common condition
        assert day["weather"]["main"] == "Clouds"

    def test_multiple_days_sorted_by_date(self) -> None:
        items = [
            _make_forecast_item(
                "2024-01-17", "12:00:00", 20.0, 40, "Clear", "clear sky", "01d"
            ),
            _make_forecast_item(
                "2024-01-15", "12:00:00", 10.0, 60, "Rain", "light rain", "10d"
            ),
            _make_forecast_item(
                "2024-01-16", "12:00:00", 15.0, 50, "Clouds", "overcast", "04d"
            ),
        ]
        result = process_forecast_data(_make_forecast_data(items))
        assert len(result) == 3
        assert [d["date"] for d in result] == [
            "2024-01-15",
            "2024-01-16",
            "2024-01-17",
        ]

    def test_items_without_dt_txt_are_skipped(self) -> None:
        items = [
            {
                "dt": 1700000000,
                "main": {"temp": 10, "humidity": 50},
                "weather": [{"main": "Clear", "description": "clear", "icon": "01d"}],
            },
            _make_forecast_item(
                "2024-01-15", "12:00:00", 12.0, 60, "Clear", "clear sky", "01d"
            ),
        ]
        result = process_forecast_data(_make_forecast_data(items))
        assert len(result) == 1

    def test_items_with_empty_dt_txt_are_skipped(self) -> None:
        items = [
            {
                "dt": 1700000000,
                "dt_txt": "",
                "main": {"temp": 10, "humidity": 50},
                "weather": [{"main": "Clear", "description": "clear", "icon": "01d"}],
            },
            _make_forecast_item(
                "2024-01-15", "12:00:00", 12.0, 60, "Clear", "clear sky", "01d"
            ),
        ]
        result = process_forecast_data(_make_forecast_data(items))
        assert len(result) == 1

    def test_icon_matches_most_common_condition(self) -> None:
        """Icon should come from an item whose main condition == most_common_condition."""
        items = [
            _make_forecast_item(
                "2024-01-15", "06:00:00", 5.0, 80, "Rain", "light rain", "10d"
            ),
            _make_forecast_item(
                "2024-01-15", "12:00:00", 12.0, 50, "Clear", "clear sky", "01d"
            ),
            _make_forecast_item(
                "2024-01-15", "15:00:00", 11.0, 55, "Clear", "clear sky", "01d"
            ),
            _make_forecast_item(
                "2024-01-15", "18:00:00", 8.0, 70, "Clear", "clear sky", "01n"
            ),
        ]
        result = process_forecast_data(_make_forecast_data(items))
        # Clear appears 3 times; its icon should be picked (first match = "01d")
        assert result[0]["weather"]["icon"] == "01d"

    def test_timestamp_from_first_item_of_day(self) -> None:
        items = [
            _make_forecast_item(
                "2024-01-15", "06:00:00", 5.0, 80, "Clouds", "overcast", "04d", dt=111
            ),
            _make_forecast_item(
                "2024-01-15", "12:00:00", 12.0, 50, "Clear", "clear sky", "01d", dt=222
            ),
        ]
        result = process_forecast_data(_make_forecast_data(items))
        assert result[0]["timestamp"] == 111

    @pytest.mark.parametrize(
        "temps, expected_min, expected_max",
        [
            ([0.0], 0.0, 0.0),
            ([-5.0, 0.0, 5.0], -5.0, 5.0),
            ([100.0, 100.0], 100.0, 100.0),
            ([-40.0, 50.0], -40.0, 50.0),
        ],
        ids=["single-zero", "negative-to-positive", "identical", "extreme-range"],
    )
    def test_temperature_extremes(
        self, temps: List[float], expected_min: float, expected_max: float
    ) -> None:
        items = [
            _make_forecast_item(
                "2024-01-15",
                f"{i:02d}:00:00",
                t,
                50,
                "Clear",
                "clear sky",
                "01d",
            )
            for i, t in enumerate(temps)
        ]
        result = process_forecast_data(_make_forecast_data(items))
        assert result[0]["temp_min"] == expected_min
        assert result[0]["temp_max"] == expected_max

    def test_humidity_rounded(self) -> None:
        items = [
            _make_forecast_item(
                "2024-01-15", "06:00:00", 10.0, 33, "Clear", "clear", "01d"
            ),
            _make_forecast_item(
                "2024-01-15", "12:00:00", 10.0, 34, "Clear", "clear", "01d"
            ),
        ]
        result = process_forecast_data(_make_forecast_data(items))
        # (33 + 34) / 2 = 33.5 → rounds to 34
        assert result[0]["humidity"] == round(33.5)


# ---------------------------------------------------------------------------
# geocode_location
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestGeocodeLocation:
    """Tests for geocode_location (async, hits Nominatim API)."""

    async def test_success_full_address(self) -> None:
        nominatim_response = [
            {
                "lat": "51.5074",
                "lon": "-0.1278",
                "display_name": "London, Greater London, England, UK",
                "address": {
                    "city": "London",
                    "country": "United Kingdom",
                    "state": "England",
                },
            }
        ]
        mock_resp = _mock_httpx_response(nominatim_response)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("app.utils.weather_utils.http_async_client", mock_client):
            result = await geocode_location("London")

        assert result["lat"] == pytest.approx(51.5074)
        assert result["lon"] == -0.1278
        assert result["city"] == "London"
        assert result["country"] == "United Kingdom"
        assert result["region"] == "England"
        assert result["display_name"] == "London, Greater London, England, UK"

    async def test_empty_results_raises(self) -> None:
        mock_resp = _mock_httpx_response([])
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("app.utils.weather_utils.http_async_client", mock_client):
            with pytest.raises(Exception, match="Failed to geocode location"):
                await geocode_location("NonexistentPlace12345")

    async def test_missing_address_fields(self) -> None:
        nominatim_response = [
            {
                "lat": "40.7128",
                "lon": "-74.0060",
                "display_name": "New York",
                # No "address" key at all
            }
        ]
        mock_resp = _mock_httpx_response(nominatim_response)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("app.utils.weather_utils.http_async_client", mock_client):
            result = await geocode_location("New York")

        assert result["lat"] == pytest.approx(40.7128)
        assert result["lon"] == -74.006
        assert result["city"] is None
        assert result["country"] is None
        assert result["region"] is None

    async def test_http_error_raises(self) -> None:
        mock_resp = _mock_httpx_response({}, status_code=500)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("app.utils.weather_utils.http_async_client", mock_client):
            with pytest.raises(Exception, match="Failed to geocode location"):
                await geocode_location("London")

    async def test_uses_correct_headers_and_params(self) -> None:
        mock_resp = _mock_httpx_response(
            [{"lat": "0", "lon": "0", "display_name": "X"}]
        )
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("app.utils.weather_utils.http_async_client", mock_client):
            await geocode_location("Tokyo")

        call_kwargs = mock_client.get.call_args
        assert call_kwargs.args[0] == "https://nominatim.openstreetmap.org/search"
        assert call_kwargs.kwargs["params"]["q"] == "Tokyo"
        assert call_kwargs.kwargs["params"]["format"] == "json"
        assert call_kwargs.kwargs["params"]["limit"] == "1"
        assert "User-Agent" in call_kwargs.kwargs["headers"]


# ---------------------------------------------------------------------------
# get_location_data
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestGetLocationData:
    """Tests for get_location_data (location_name vs ip_address paths)."""

    async def test_with_location_name_success(self) -> None:
        geocode_result = {
            "lat": 48.8566,
            "lon": 2.3522,
            "city": "Paris",
            "country": "France",
            "region": "Ile-de-France",
            "display_name": "Paris, France",
        }
        with patch(
            "app.utils.weather_utils.geocode_location",
            new_callable=AsyncMock,
            return_value=geocode_result,
        ):
            result = await get_location_data(location_name="Paris")

        assert result["lat"] == pytest.approx(48.8566)
        assert result["lon"] == 2.3522
        assert result["city"] == "Paris"
        assert result["country"] == "France"
        assert result["region"] == "Ile-de-France"
        assert result["cache_key"] == "weather:location:paris"

    async def test_location_name_with_spaces_normalised_in_cache_key(self) -> None:
        geocode_result = {
            "lat": 40.0,
            "lon": -74.0,
            "city": "New York",
            "country": "US",
            "region": "NY",
            "display_name": "New York, US",
        }
        with patch(
            "app.utils.weather_utils.geocode_location",
            new_callable=AsyncMock,
            return_value=geocode_result,
        ):
            result = await get_location_data(location_name="New York")

        assert result["cache_key"] == "weather:location:new_york"

    async def test_location_name_missing_city_falls_back_to_display_name(self) -> None:
        geocode_result = {
            "lat": 51.0,
            "lon": 0.0,
            "city": None,
            "country": "UK",
            "region": "Kent",
            "display_name": "Tunbridge Wells, Kent, UK",
        }
        with patch(
            "app.utils.weather_utils.geocode_location",
            new_callable=AsyncMock,
            return_value=geocode_result,
        ):
            result = await get_location_data(location_name="Tunbridge Wells")

        # city extracted from display_name split
        assert result["city"] == "Tunbridge Wells"

    async def test_location_name_missing_city_and_display_name(self) -> None:
        geocode_result = {
            "lat": 51.0,
            "lon": 0.0,
            "city": None,
            "country": "UK",
            "region": "Kent",
            "display_name": None,
        }
        with patch(
            "app.utils.weather_utils.geocode_location",
            new_callable=AsyncMock,
            return_value=geocode_result,
        ):
            result = await get_location_data(location_name="SomePlace")

        # city stays None because display_name is falsy
        assert result["city"] is None

    async def test_geocode_failure_propagates(self) -> None:
        with patch(
            "app.utils.weather_utils.geocode_location",
            new_callable=AsyncMock,
            side_effect=Exception("geocode boom"),
        ):
            with pytest.raises(Exception, match="geocode boom"):
                await get_location_data(location_name="BadPlace")

    async def test_with_ip_address_success(self) -> None:
        ip_response = {
            "status": "success",
            "lat": 37.7749,
            "lon": -122.4194,
            "city": "San Francisco",
            "country": "United States",
            "regionName": "California",
        }
        mock_resp = _mock_httpx_response(ip_response)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("app.utils.weather_utils.http_async_client", mock_client):
            result = await get_location_data(ip_address="8.8.8.8")

        assert result["lat"] == 37.7749
        assert result["lon"] == -122.4194
        assert result["city"] == "San Francisco"
        assert result["country"] == "United States"
        assert result["region"] == "California"
        assert result["cache_key"] == "weather:ip:8.8.8.8"

    async def test_with_ip_address_failed_status(self) -> None:
        ip_response = {"status": "fail", "message": "invalid query"}
        mock_resp = _mock_httpx_response(ip_response)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("app.utils.weather_utils.http_async_client", mock_client):
            with pytest.raises(Exception, match="Failed to get location from IP"):
                await get_location_data(ip_address="0.0.0.0")

    async def test_with_ip_address_http_error(self) -> None:
        mock_resp = _mock_httpx_response({}, status_code=503)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("app.utils.weather_utils.http_async_client", mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await get_location_data(ip_address="1.2.3.4")


# ---------------------------------------------------------------------------
# fetch_weather_data
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestFetchWeatherData:
    """Tests for fetch_weather_data (parallel HTTP requests)."""

    async def test_both_requests_succeed(self) -> None:
        weather_json = {"main": {"temp": 20}}
        forecast_json: dict[str, object] = {"list": []}

        weather_resp = _mock_httpx_response(weather_json)
        forecast_resp = _mock_httpx_response(forecast_json)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[weather_resp, forecast_resp])

        with patch("app.utils.weather_utils.http_async_client", mock_client):
            current, forecast = await fetch_weather_data(51.5, -0.12, FAKE_API_KEY)

        assert current == weather_json
        assert forecast == forecast_json
        assert mock_client.get.call_count == 2

    async def test_weather_request_fails(self) -> None:
        weather_resp = _mock_httpx_response({}, status_code=401)
        forecast_resp = _mock_httpx_response({"list": []})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[weather_resp, forecast_resp])

        with patch("app.utils.weather_utils.http_async_client", mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_weather_data(51.5, -0.12, FAKE_API_KEY)

    async def test_forecast_request_fails(self) -> None:
        weather_resp = _mock_httpx_response({"main": {"temp": 20}})
        forecast_resp = _mock_httpx_response({}, status_code=500)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[weather_resp, forecast_resp])

        with patch("app.utils.weather_utils.http_async_client", mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_weather_data(51.5, -0.12, FAKE_API_KEY)

    async def test_urls_contain_correct_params(self) -> None:
        resp = _mock_httpx_response({})
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)

        with patch("app.utils.weather_utils.http_async_client", mock_client):
            await fetch_weather_data(10.0, 20.0, "MY_KEY")

        calls = [str(c) for c in mock_client.get.call_args_list]
        joined = " ".join(calls)
        assert "lat=10.0" in joined
        assert "lon=20.0" in joined
        assert "appid=MY_KEY" in joined
        assert "units=metric" in joined


# ---------------------------------------------------------------------------
# prepare_weather_data
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestPrepareWeatherData:
    """Tests for prepare_weather_data (assembles the final weather dict)."""

    async def _call(
        self,
        location_info: Dict[str, Any],
        current_weather: Dict[str, Any] | None = None,
        forecast_data: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        if current_weather is None:
            current_weather = _make_current_weather()
        if forecast_data is None:
            forecast_data = {"list": []}

        with patch(
            "app.utils.weather_utils.fetch_weather_data",
            new_callable=AsyncMock,
            return_value=(current_weather, forecast_data),
        ):
            return await prepare_weather_data(51.5, -0.12, location_info, FAKE_API_KEY)

    async def test_with_sys_and_country(self) -> None:
        loc = {"city": "London", "country": "GB", "region": "England"}
        result = await self._call(loc)
        assert result["sys"]["country"] == "GB"
        assert result["location"]["city"] == "London"
        assert result["location"]["country"] == "GB"
        assert result["location"]["region"] == "England"

    async def test_sys_present_but_missing_country_uses_location_country(self) -> None:
        current = _make_current_weather()
        del current["sys"]["country"]
        loc = {"city": "Berlin", "country": "DE", "region": "Berlin"}
        result = await self._call(loc, current_weather=current)
        assert result["sys"]["country"] == "DE"

    async def test_sys_present_missing_country_no_location_country(self) -> None:
        current = _make_current_weather()
        del current["sys"]["country"]
        loc = {"city": "Somewhere", "country": None, "region": None}
        result = await self._call(loc, current_weather=current)
        assert result["sys"]["country"] == ""

    async def test_no_sys_field_creates_minimal_sys(self) -> None:
        current = _make_current_weather(include_sys=False)
        loc = {"city": "Tokyo", "country": "JP", "region": "Kanto"}
        result = await self._call(loc, current_weather=current)
        assert "sys" in result
        assert result["sys"]["country"] == "JP"
        assert "sunrise" in result["sys"]
        assert "sunset" in result["sys"]
        # sunset should be ~12 hours after sunrise
        assert result["sys"]["sunset"] > result["sys"]["sunrise"]

    async def test_no_sys_field_no_country_defaults_empty(self) -> None:
        current = _make_current_weather(include_sys=False)
        loc = {"city": "Unknown", "country": None, "region": None}
        result = await self._call(loc, current_weather=current)
        assert result["sys"]["country"] == ""

    async def test_name_field_set_from_city_when_missing(self) -> None:
        current = _make_current_weather()
        current["name"] = ""
        loc = {"city": "Oslo", "country": "NO", "region": None}
        result = await self._call(loc, current_weather=current)
        assert result["name"] == "Oslo"

    async def test_name_field_preserved_when_present(self) -> None:
        current = _make_current_weather(name="ExistingName")
        loc = {"city": "DifferentCity", "country": "XX", "region": None}
        result = await self._call(loc, current_weather=current)
        assert result["name"] == "ExistingName"

    async def test_name_not_set_when_both_missing(self) -> None:
        current = _make_current_weather()
        current["name"] = ""
        loc = {"city": None, "country": None, "region": None}
        result = await self._call(loc, current_weather=current)
        # name stays empty because city is None
        assert result.get("name") == ""

    async def test_forecast_data_included(self) -> None:
        forecast = _make_forecast_data(
            [
                _make_forecast_item(
                    "2024-01-15", "12:00:00", 10.0, 50, "Clear", "clear", "01d"
                ),
            ]
        )
        loc = {"city": "Rome", "country": "IT", "region": "Lazio"}
        result = await self._call(loc, forecast_data=forecast)
        assert len(result["forecast"]) == 1
        assert result["forecast"][0]["date"] == "2024-01-15"

    async def test_current_weather_fields_spread(self) -> None:
        current = _make_current_weather(temp=25.0)
        loc = {"city": "Cairo", "country": "EG", "region": None}
        result = await self._call(loc, current_weather=current)
        # Current weather fields should be spread into the top level
        assert result["main"]["temp"] == 25.0
        assert result["weather"][0]["main"] == "Clouds"


# ---------------------------------------------------------------------------
# user_weather
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestUserWeather:
    """Tests for the top-level user_weather orchestrator."""

    @pytest.fixture(autouse=True)
    def _patch_log(self) -> None:
        """Suppress structured logging in tests."""
        # log.set / log.debug / log.error are called; just let them pass
        pass

    async def test_missing_api_key_returns_error(self) -> None:
        mock_settings = MagicMock()
        mock_settings.OPENWEATHER_API_KEY = None

        with patch("app.utils.weather_utils.settings", mock_settings):
            result = await user_weather(location_name="London")

        assert "Failed to fetch weather" in result
        assert "API key" in result

    async def test_empty_string_api_key_returns_error(self) -> None:
        mock_settings = MagicMock()
        mock_settings.OPENWEATHER_API_KEY = ""

        with patch("app.utils.weather_utils.settings", mock_settings):
            result = await user_weather(location_name="London")

        assert "Failed to fetch weather" in result

    async def test_cached_weather_returned(self) -> None:
        mock_settings = MagicMock()
        mock_settings.OPENWEATHER_API_KEY = FAKE_API_KEY
        cached_data = {"name": "London", "main": {"temp": 15}}

        location_data = {
            "lat": 51.5,
            "lon": -0.12,
            "city": "London",
            "country": "GB",
            "region": "England",
            "cache_key": "weather:location:london",
        }

        with (
            patch("app.utils.weather_utils.settings", mock_settings),
            patch(
                "app.utils.weather_utils.get_location_data",
                new_callable=AsyncMock,
                return_value=location_data,
            ),
            patch(
                "app.utils.weather_utils.get_cache",
                new_callable=AsyncMock,
                return_value=cached_data,
            ) as mock_get_cache,
            patch(
                "app.utils.weather_utils.prepare_weather_data",
                new_callable=AsyncMock,
            ) as mock_prepare,
        ):
            result = await user_weather(location_name="London")

        assert result == cached_data
        mock_get_cache.assert_awaited_once_with("weather:location:london")
        mock_prepare.assert_not_awaited()

    async def test_success_no_cache_fetches_and_caches(self) -> None:
        mock_settings = MagicMock()
        mock_settings.OPENWEATHER_API_KEY = FAKE_API_KEY
        weather_data = {"name": "Paris", "main": {"temp": 22}}

        location_data = {
            "lat": 48.8566,
            "lon": 2.3522,
            "city": "Paris",
            "country": "France",
            "region": "Ile-de-France",
            "cache_key": "weather:location:paris",
        }

        with (
            patch("app.utils.weather_utils.settings", mock_settings),
            patch(
                "app.utils.weather_utils.get_location_data",
                new_callable=AsyncMock,
                return_value=location_data,
            ),
            patch(
                "app.utils.weather_utils.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.utils.weather_utils.prepare_weather_data",
                new_callable=AsyncMock,
                return_value=weather_data,
            ),
            patch(
                "app.utils.weather_utils.set_cache",
                new_callable=AsyncMock,
            ) as mock_set_cache,
        ):
            result = await user_weather(location_name="Paris")

        assert result == weather_data
        mock_set_cache.assert_awaited_once()
        cache_call_args = mock_set_cache.call_args
        assert cache_call_args.args[0] == "weather:location:paris"
        assert cache_call_args.args[1] == weather_data

    async def test_location_failure_returns_error_message(self) -> None:
        mock_settings = MagicMock()
        mock_settings.OPENWEATHER_API_KEY = FAKE_API_KEY

        with (
            patch("app.utils.weather_utils.settings", mock_settings),
            patch(
                "app.utils.weather_utils.get_location_data",
                new_callable=AsyncMock,
                side_effect=Exception("location not found"),
            ),
        ):
            result = await user_weather(location_name="BadPlace")

        assert "Could not find location" in result
        assert "BadPlace" in result

    async def test_location_failure_with_none_location_name(self) -> None:
        mock_settings = MagicMock()
        mock_settings.OPENWEATHER_API_KEY = FAKE_API_KEY

        with (
            patch("app.utils.weather_utils.settings", mock_settings),
            patch(
                "app.utils.weather_utils.get_location_data",
                new_callable=AsyncMock,
                side_effect=Exception("ip lookup failed"),
            ),
        ):
            result = await user_weather(location_name=None)

        assert "Could not find location" in result

    async def test_prepare_weather_failure_returns_location_error(self) -> None:
        mock_settings = MagicMock()
        mock_settings.OPENWEATHER_API_KEY = FAKE_API_KEY

        location_data = {
            "lat": 51.5,
            "lon": -0.12,
            "city": "London",
            "country": "GB",
            "region": "England",
            "cache_key": "weather:location:london",
        }

        with (
            patch("app.utils.weather_utils.settings", mock_settings),
            patch(
                "app.utils.weather_utils.get_location_data",
                new_callable=AsyncMock,
                return_value=location_data,
            ),
            patch(
                "app.utils.weather_utils.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.utils.weather_utils.prepare_weather_data",
                new_callable=AsyncMock,
                side_effect=Exception("API down"),
            ),
        ):
            result = await user_weather(location_name="London")

        # The inner except catches this and returns the location error message
        assert "Could not find location" in result

    async def test_cache_ttl_uses_one_hour(self) -> None:
        """Verify the cache is set with ONE_HOUR_TTL (3600 seconds)."""
        mock_settings = MagicMock()
        mock_settings.OPENWEATHER_API_KEY = FAKE_API_KEY
        weather_data = {"name": "Berlin"}

        location_data = {
            "lat": 52.52,
            "lon": 13.405,
            "city": "Berlin",
            "country": "DE",
            "region": "Berlin",
            "cache_key": "weather:location:berlin",
        }

        with (
            patch("app.utils.weather_utils.settings", mock_settings),
            patch(
                "app.utils.weather_utils.get_location_data",
                new_callable=AsyncMock,
                return_value=location_data,
            ),
            patch(
                "app.utils.weather_utils.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.utils.weather_utils.prepare_weather_data",
                new_callable=AsyncMock,
                return_value=weather_data,
            ),
            patch(
                "app.utils.weather_utils.set_cache",
                new_callable=AsyncMock,
            ) as mock_set_cache,
        ):
            await user_weather(location_name="Berlin")

        # ONE_HOUR_TTL = 3600
        assert mock_set_cache.call_args.args[2] == 3600
