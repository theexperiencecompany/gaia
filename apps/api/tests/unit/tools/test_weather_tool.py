"""Unit tests for app.agents.tools.weather_tool."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.integrations.weather import WeatherLocation, WeatherReport

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.weather_tool"


def _make_config(user_id: str = FAKE_USER_ID) -> dict[str, Any]:
    """Return a minimal RunnableConfig-like dict."""
    return {"metadata": {"user_id": user_id}}


def _make_weather_data(location: str = "London") -> WeatherReport:
    """Return a weather report as user_weather() produces one."""
    return WeatherReport(
        forecast=[],
        location=WeatherLocation(city=location, country="GB", region="England"),
        main={"temp": 15.2},
    )


def _writer_mock() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests: get_weather
# ---------------------------------------------------------------------------


class TestGetWeather:
    """Tests for the get_weather tool."""

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.user_weather", new_callable=AsyncMock)
    async def test_happy_path(
        self,
        mock_user_weather: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Successful weather lookup returns formatted string with data."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        weather_data = _make_weather_data("Mumbai")
        mock_user_weather.return_value = weather_data

        from app.agents.tools.weather_tool import get_weather

        result = await get_weather.coroutine(
            config=_make_config(),
            location="Mumbai,IN",
        )

        assert "Mumbai,IN" in result
        mock_user_weather.assert_awaited_once_with("Mumbai,IN")
        # Verify writer was called with progress and data
        assert writer.call_count >= 2
        # First call: progress message
        first_call = writer.call_args_list[0]
        assert "progress" in first_call[0][0]
        # Second call: weather_data
        second_call = writer.call_args_list[1]
        assert "weather_data" in second_call[0][0]

    @patch(f"{MODULE}.current_stream_writer")
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

    @patch(f"{MODULE}.current_stream_writer")
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

    @patch(f"{MODULE}.current_stream_writer")
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
        assert data_call["weather_data"] == weather_data.model_dump(mode="json", exclude_unset=True)
        assert data_call["location"] == "Paris,FR"

    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.user_weather", new_callable=AsyncMock)
    async def test_a_weather_report_streams_only_the_fields_it_carries(
        self,
        mock_user_weather: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Unset optional fields (name, sys) are omitted from the card, not sent as nulls."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_user_weather.return_value = WeatherReport(
            forecast=[],
            location=WeatherLocation(city="Pune", country="IN", region=None),
            main={"temp": 21.5},
        )

        from app.agents.tools.weather_tool import get_weather

        await get_weather.coroutine(config=_make_config(), location="Pune,IN")

        assert writer.call_args_list[1][0][0]["weather_data"] == {
            "main": {"temp": 21.5},
            "forecast": [],
            "location": {"city": "Pune", "country": "IN", "region": None},
        }

    @patch(f"{MODULE}.current_stream_writer")
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

    @patch(f"{MODULE}.current_stream_writer")
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

    @patch(f"{MODULE}.current_stream_writer")
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

    @pytest.mark.parametrize(
        "sentence",
        [
            "Could not find location: Atlantis",
            "Weather isn't set up on this GAIA instance, so no weather data is available. "
            "An admin can add an OpenWeather key in Settings → Providers & Tools.",
        ],
    )
    @patch(f"{MODULE}.current_stream_writer")
    @patch(f"{MODULE}.user_weather", new_callable=AsyncMock)
    async def test_no_report_returns_the_sentence_and_shows_no_card(
        self,
        mock_user_weather: AsyncMock,
        mock_writer_factory: MagicMock,
        sentence: str,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_user_weather.return_value = sentence

        from app.agents.tools.weather_tool import get_weather

        result = await get_weather.coroutine(config=_make_config(), location="Atlantis")

        assert result == sentence
        assert all("weather_data" not in call[0][0] for call in writer.call_args_list)
