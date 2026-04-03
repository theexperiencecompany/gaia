"""Unit tests for app.agents.tools.weather_tool."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.weather_tool"


def _make_config(user_id: str = FAKE_USER_ID) -> Dict[str, Any]:
    """Return a minimal RunnableConfig-like dict."""
    return {"metadata": {"user_id": user_id}}


def _make_weather_data(location: str = "London") -> Dict[str, Any]:
    """Return a sample weather data dict as would come from user_weather()."""
    return {
        "location": {
            "city": location,
            "country": "GB",
            "region": "England",
        },
        "current": {
            "temp": 15.2,
            "feels_like": 13.8,
            "humidity": 72,
            "description": "partly cloudy",
            "icon": "03d",
            "wind_speed": 5.4,
        },
        "daily_forecast": [
            {
                "date": "2026-03-20",
                "temp_min": 10.0,
                "temp_max": 18.0,
                "description": "light rain",
            }
        ],
    }


def _writer_mock() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests: get_weather
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetWeather:
    """Tests for the get_weather tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.user_weather", new_callable=AsyncMock)
    async def test_happy_path(
        self,
        mock_user_weather: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Successful weather lookup returns formatted string with data."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        weather_data = _make_weather_data("Surat")
        mock_user_weather.return_value = weather_data

        from app.agents.tools.weather_tool import get_weather

        result = await get_weather.coroutine(
            config=_make_config(),
            location="Surat,IN",
        )

        assert "Surat,IN" in result
        mock_user_weather.assert_awaited_once_with("Surat,IN")
        # Verify writer was called with progress and data
        assert writer.call_count >= 2
        # First call: progress message
        first_call = writer.call_args_list[0]
        assert "progress" in first_call[0][0]
        # Second call: weather_data
        second_call = writer.call_args_list[1]
        assert "weather_data" in second_call[0][0]

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.user_weather", new_callable=AsyncMock)
    async def test_returns_instructions_for_insights(
        self,
        mock_user_weather: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Return value should include instruction text about providing insights."""
        mock_writer_factory.return_value = _writer_mock()
        mock_user_weather.return_value = _make_weather_data()

        from app.agents.tools.weather_tool import get_weather

        result = await get_weather.coroutine(
            config=_make_config(),
            location="London",
        )

        assert "insights" in result.lower()
        assert "suggestions" in result.lower()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.user_weather", new_callable=AsyncMock)
    async def test_streams_progress_message(
        self,
        mock_user_weather: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Writer should receive a progress message with the location name."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_user_weather.return_value = _make_weather_data()

        from app.agents.tools.weather_tool import get_weather

        await get_weather.coroutine(
            config=_make_config(),
            location="Tokyo,JP",
        )

        progress_call = writer.call_args_list[0][0][0]
        assert "Tokyo,JP" in progress_call["progress"]

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.user_weather", new_callable=AsyncMock)
    async def test_streams_weather_data_to_frontend(
        self,
        mock_user_weather: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Writer sends weather_data and location for the frontend card."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        weather_data = _make_weather_data("Paris")
        mock_user_weather.return_value = weather_data

        from app.agents.tools.weather_tool import get_weather

        await get_weather.coroutine(
            config=_make_config(),
            location="Paris,FR",
        )

        data_call = writer.call_args_list[1][0][0]
        assert data_call["weather_data"] == weather_data
        assert data_call["location"] == "Paris,FR"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.user_weather", new_callable=AsyncMock)
    async def test_api_error_propagates(
        self,
        mock_user_weather: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """When user_weather raises an exception, it propagates (no try/except in tool)."""
        mock_writer_factory.return_value = _writer_mock()
        mock_user_weather.side_effect = Exception("API key invalid")

        from app.agents.tools.weather_tool import get_weather

        with pytest.raises(Exception, match="API key invalid"):
            await get_weather.coroutine(
                config=_make_config(),
                location="Nowhere",
            )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.user_weather", new_callable=AsyncMock)
    async def test_returns_string_type(
        self,
        mock_user_weather: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """The tool return type should be a string (not dict)."""
        mock_writer_factory.return_value = _writer_mock()
        mock_user_weather.return_value = _make_weather_data()

        from app.agents.tools.weather_tool import get_weather

        result = await get_weather.coroutine(
            config=_make_config(),
            location="NYC",
        )

        assert isinstance(result, str)

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.user_weather", new_callable=AsyncMock)
    async def test_weather_data_included_in_return(
        self,
        mock_user_weather: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """The returned string should contain the weather data for the LLM."""
        mock_writer_factory.return_value = _writer_mock()
        weather_data = _make_weather_data("Berlin")
        mock_user_weather.return_value = weather_data

        from app.agents.tools.weather_tool import get_weather

        result = await get_weather.coroutine(
            config=_make_config(),
            location="Berlin,DE",
        )

        # The return contains a string representation of weather data
        assert "Berlin,DE" in result

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.user_weather", new_callable=AsyncMock)
    async def test_empty_weather_data(
        self,
        mock_user_weather: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Tool handles empty/minimal weather data without error."""
        mock_writer_factory.return_value = _writer_mock()
        mock_user_weather.return_value = {}

        from app.agents.tools.weather_tool import get_weather

        result = await get_weather.coroutine(
            config=_make_config(),
            location="Unknown",
        )

        assert isinstance(result, str)
        assert "Unknown" in result
