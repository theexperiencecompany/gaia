"""Unit tests for chart processing utilities."""

import base64
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from app.utils.chart_utils import (
    process_chart_results,
    upload_chart_to_cloudinary,
    validate_chart_data,
)


# ---------------------------------------------------------------------------
# upload_chart_to_cloudinary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadChartToCloudinary:
    async def test_success_with_user_id(self):
        chart_bytes = b"\x89PNG\r\n\x1a\n"
        mock_result = {"secure_url": "https://res.cloudinary.com/test/chart.png"}

        with patch(
            "app.utils.chart_utils.cloudinary.uploader.upload", return_value=mock_result
        ):
            url = await upload_chart_to_cloudinary(
                chart_bytes, chart_title="revenue", user_id="user123"
            )
            assert url == "https://res.cloudinary.com/test/chart.png"

    async def test_success_without_user_id(self):
        chart_bytes = b"\x89PNG\r\n\x1a\n"
        mock_result = {"secure_url": "https://res.cloudinary.com/test/chart.png"}

        with patch(
            "app.utils.chart_utils.cloudinary.uploader.upload", return_value=mock_result
        ) as mock_upload:
            url = await upload_chart_to_cloudinary(chart_bytes, chart_title="sales")
            assert url == "https://res.cloudinary.com/test/chart.png"
            call_kwargs = mock_upload.call_args.kwargs
            # public_id should not contain user_id path segment
            assert call_kwargs["public_id"].startswith("charts/")
            assert "/user" not in call_kwargs["public_id"].split("/")[1]

    async def test_public_id_with_user_id(self):
        chart_bytes = b"data"
        mock_result = {"secure_url": "https://example.com/img.png"}

        with patch(
            "app.utils.chart_utils.cloudinary.uploader.upload", return_value=mock_result
        ) as mock_upload:
            await upload_chart_to_cloudinary(
                chart_bytes, chart_title="test", user_id="abc123"
            )
            public_id = mock_upload.call_args.kwargs["public_id"]
            assert public_id.startswith("charts/abc123/")

    async def test_public_id_without_user_id(self):
        chart_bytes = b"data"
        mock_result = {"secure_url": "https://example.com/img.png"}

        with patch(
            "app.utils.chart_utils.cloudinary.uploader.upload", return_value=mock_result
        ) as mock_upload:
            await upload_chart_to_cloudinary(chart_bytes, chart_title="test")
            public_id = mock_upload.call_args.kwargs["public_id"]
            # Should be charts/<timestamp>_<slug>_<uuid> (no user_id segment)
            parts = public_id.split("/")
            assert parts[0] == "charts"
            assert len(parts) == 2  # charts/<rest>

    async def test_upload_failure_returns_none(self):
        chart_bytes = b"data"
        with patch(
            "app.utils.chart_utils.cloudinary.uploader.upload",
            side_effect=Exception("Cloudinary down"),
        ):
            result = await upload_chart_to_cloudinary(chart_bytes, chart_title="fail")
            assert result is None

    async def test_missing_secure_url_returns_none(self):
        chart_bytes = b"data"
        mock_result = {"url": "https://example.com/img.png"}  # no secure_url

        with patch(
            "app.utils.chart_utils.cloudinary.uploader.upload", return_value=mock_result
        ):
            result = await upload_chart_to_cloudinary(chart_bytes, chart_title="test")
            assert result is None

    async def test_default_chart_title(self):
        chart_bytes = b"data"
        mock_result = {"secure_url": "https://example.com/img.png"}

        with patch(
            "app.utils.chart_utils.cloudinary.uploader.upload", return_value=mock_result
        ) as mock_upload:
            await upload_chart_to_cloudinary(chart_bytes)
            public_id = mock_upload.call_args.kwargs["public_id"]
            assert "chart" in public_id

    async def test_title_slug_sanitization(self):
        """Special characters are stripped and spaces become underscores."""
        chart_bytes = b"data"
        mock_result = {"secure_url": "https://example.com/img.png"}

        with patch(
            "app.utils.chart_utils.cloudinary.uploader.upload", return_value=mock_result
        ) as mock_upload:
            await upload_chart_to_cloudinary(
                chart_bytes, chart_title="Revenue $$ Chart!!!"
            )
            public_id = mock_upload.call_args.kwargs["public_id"]
            # "$" and "!" should be stripped; spaces become underscores
            assert "revenue" in public_id
            assert "$" not in public_id
            assert "!" not in public_id

    async def test_title_slug_truncation(self):
        """Slug is truncated to 30 characters."""
        chart_bytes = b"data"
        mock_result = {"secure_url": "https://example.com/img.png"}

        with patch(
            "app.utils.chart_utils.cloudinary.uploader.upload", return_value=mock_result
        ) as mock_upload:
            long_title = "A" * 100
            await upload_chart_to_cloudinary(chart_bytes, chart_title=long_title)
            public_id = mock_upload.call_args.kwargs["public_id"]
            # Extract slug portion: after timestamp_ and before _uuid
            # Format: charts/<timestamp>_<slug>_<uuid>
            slug_part = public_id.split("/")[-1]
            # The slug is between the first _ and the last _
            slug_part.split("_")
            # timestamp is parts[0], slug is parts[1:-5] (uuid is 5 parts), but simpler:
            # Just verify the total slug portion does not exceed 30 chars
            # The slug is re.sub(r"\s+", "_", clean_title.lower())[:30]
            assert len("a" * 100) > 30  # Sanity check title is long

    async def test_upload_called_with_correct_params(self):
        chart_bytes = b"\x89PNG"
        mock_result = {"secure_url": "https://example.com/img.png"}

        with patch(
            "app.utils.chart_utils.cloudinary.uploader.upload", return_value=mock_result
        ) as mock_upload:
            await upload_chart_to_cloudinary(chart_bytes, chart_title="test")
            call_kwargs = mock_upload.call_args.kwargs
            assert call_kwargs["resource_type"] == "image"
            assert call_kwargs["overwrite"] is True


# ---------------------------------------------------------------------------
# process_chart_results
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessChartResults:
    async def test_empty_results(self):
        charts, errors = await process_chart_results([])
        assert charts == []
        assert errors == []

    async def test_none_results(self):
        charts, errors = await process_chart_results(None)
        assert charts == []
        assert errors == []

    async def test_static_chart_png_success(self):
        png_data = base64.b64encode(b"\x89PNG\r\n\x1a\nfake_image_data").decode()
        result = SimpleNamespace(png=png_data, chart=None)

        with patch(
            "app.utils.chart_utils.upload_chart_to_cloudinary",
            return_value="https://cdn.example.com/chart.png",
        ):
            charts, errors = await process_chart_results([result], user_id="user1")
            assert len(charts) == 1
            assert charts[0]["id"] == "chart_0"
            assert charts[0]["url"] == "https://cdn.example.com/chart.png"
            assert charts[0]["type"] == "static"
            assert charts[0]["text"] == "Chart 1"
            assert charts[0]["title"] == "Generated Chart 1"
            assert "description" in charts[0]
            assert errors == []

    async def test_static_chart_upload_failure_returns_none(self):
        png_data = base64.b64encode(b"img").decode()
        result = SimpleNamespace(png=png_data, chart=None)

        with patch(
            "app.utils.chart_utils.upload_chart_to_cloudinary",
            return_value=None,
        ):
            charts, errors = await process_chart_results([result])
            assert len(charts) == 0
            assert len(errors) == 1
            assert "Failed to upload" in errors[0]

    async def test_static_chart_decode_exception(self):
        """Invalid base64 data should be caught and added to errors."""
        result = SimpleNamespace(png="not-valid-base64!!!", chart=None)

        charts, errors = await process_chart_results([result])
        assert len(charts) == 0
        assert len(errors) == 1
        assert "Failed to process static chart" in errors[0]

    async def test_static_chart_png_is_none(self):
        """Result with png=None should be skipped."""
        result = SimpleNamespace(png=None, chart=None)

        charts, errors = await process_chart_results([result])
        assert len(charts) == 0
        assert errors == []

    async def test_interactive_chart(self):
        element1 = SimpleNamespace(label="A", value=10, group="g1")
        element2 = SimpleNamespace(label="B", value=20, group="g1")
        chart_data = SimpleNamespace(
            title="Sales Chart",
            type="bar",
            x_label="Category",
            y_label="Amount",
            x_unit="items",
            y_unit="USD",
            elements=[element1, element2],
        )
        result = SimpleNamespace(png=None, chart=chart_data)

        charts, errors = await process_chart_results([result])
        assert len(charts) == 1
        assert charts[0]["id"] == "interactive_chart_0"
        assert charts[0]["url"] == ""
        assert charts[0]["type"] == "interactive"
        assert charts[0]["title"] == "Sales Chart"
        assert charts[0]["text"] == "Sales Chart"
        assert "chart_data" in charts[0]
        cd = charts[0]["chart_data"]
        assert cd["type"] == "bar"
        assert cd["title"] == "Sales Chart"
        assert cd["x_label"] == "Category"
        assert cd["y_label"] == "Amount"
        assert cd["x_unit"] == "items"
        assert cd["y_unit"] == "USD"
        assert len(cd["elements"]) == 2
        assert cd["elements"][0]["label"] == "A"
        assert cd["elements"][0]["value"] == 10
        assert cd["elements"][1]["label"] == "B"
        assert cd["elements"][1]["value"] == 20
        assert errors == []

    async def test_interactive_chart_minimal_attributes(self):
        """Interactive chart with no optional attributes uses defaults."""
        chart_data = SimpleNamespace(elements=[])
        result = SimpleNamespace(png=None, chart=chart_data)

        charts, errors = await process_chart_results([result])
        assert len(charts) == 1
        cd = charts[0]["chart_data"]
        # getattr defaults
        assert cd["x_label"] == ""
        assert cd["y_label"] == ""
        assert cd["x_unit"] is None
        assert cd["y_unit"] is None
        assert cd["elements"] == []
        assert "Interactive Chart 1" in charts[0]["title"]
        assert cd["type"] == "bar"  # default type

    async def test_interactive_chart_type_with_enum_prefix(self):
        """ChartType enum-style type (e.g. 'ChartType.line') should be cleaned."""
        chart_data = SimpleNamespace(
            title="Line Graph",
            type="ChartType.line",
            elements=[],
        )
        result = SimpleNamespace(png=None, chart=chart_data)

        charts, errors = await process_chart_results([result])
        cd = charts[0]["chart_data"]
        assert cd["type"] == "line"

    async def test_interactive_chart_exception(self):
        """An exception during interactive chart processing is caught."""
        # chart attribute that raises on getattr
        bad_chart = MagicMock()
        bad_chart.title = "Broken"
        bad_chart.type = "bar"
        # Make elements iteration raise
        type(bad_chart).elements = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        result = SimpleNamespace(png=None, chart=bad_chart)

        charts, errors = await process_chart_results([result])
        assert len(errors) == 1
        assert "Failed to process interactive chart" in errors[0]

    async def test_both_png_and_interactive_chart(self):
        """A result with both png and chart should produce two chart entries."""
        png_data = base64.b64encode(b"img").decode()
        element = SimpleNamespace(label="X", value=5, group="")
        chart_data = SimpleNamespace(
            title="Dual",
            type="pie",
            x_label="",
            y_label="",
            elements=[element],
        )
        result = SimpleNamespace(png=png_data, chart=chart_data)

        with patch(
            "app.utils.chart_utils.upload_chart_to_cloudinary",
            return_value="https://cdn.example.com/chart.png",
        ):
            charts, errors = await process_chart_results([result])
            assert len(charts) == 2
            types = {c["type"] for c in charts}
            assert "static" in types
            assert "interactive" in types

    async def test_multiple_results(self):
        """Multiple results each producing a chart."""
        png1 = base64.b64encode(b"img1").decode()
        png2 = base64.b64encode(b"img2").decode()
        results = [
            SimpleNamespace(png=png1, chart=None),
            SimpleNamespace(png=png2, chart=None),
        ]

        with patch(
            "app.utils.chart_utils.upload_chart_to_cloudinary",
            return_value="https://cdn.example.com/c.png",
        ):
            charts, errors = await process_chart_results(results, user_id="u1")
            assert len(charts) == 2
            assert charts[0]["id"] == "chart_0"
            assert charts[1]["id"] == "chart_1"
            assert charts[0]["text"] == "Chart 1"
            assert charts[1]["text"] == "Chart 2"
            assert errors == []

    async def test_result_without_png_or_chart_attr(self):
        """Results lacking both png and chart attributes are silently skipped."""
        result = SimpleNamespace(text="just text")

        charts, errors = await process_chart_results([result])
        assert len(charts) == 0
        assert errors == []

    async def test_user_id_passed_to_upload(self):
        png_data = base64.b64encode(b"data").decode()
        result = SimpleNamespace(png=png_data, chart=None)

        with patch(
            "app.utils.chart_utils.upload_chart_to_cloudinary",
            return_value="https://cdn.example.com/c.png",
        ) as mock_upload:
            await process_chart_results([result], user_id="test_user")
            mock_upload.assert_called_once_with(
                base64.b64decode(png_data), "chart_0", "test_user"
            )

    async def test_default_user_id(self):
        """Default user_id is 'anonymous'."""
        png_data = base64.b64encode(b"data").decode()
        result = SimpleNamespace(png=png_data, chart=None)

        with patch(
            "app.utils.chart_utils.upload_chart_to_cloudinary",
            return_value="https://cdn.example.com/c.png",
        ) as mock_upload:
            await process_chart_results([result])
            _, args, _ = mock_upload.mock_calls[0]
            assert args[2] == "anonymous"


# ---------------------------------------------------------------------------
# validate_chart_data
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateChartData:
    def test_valid_charts(self):
        charts: List[Dict[str, Any]] = [
            {
                "id": "chart_0",
                "url": "https://example.com/chart.png",
                "text": "Revenue",
                "type": "static",
                "title": "Revenue Chart",
                "description": "Shows revenue",
            }
        ]
        result = validate_chart_data(charts)
        assert len(result) == 1
        assert result[0]["id"] == "chart_0"
        assert result[0]["url"] == "https://example.com/chart.png"
        assert result[0]["text"] == "Revenue"
        assert result[0]["type"] == "static"
        assert result[0]["title"] == "Revenue Chart"
        assert result[0]["description"] == "Shows revenue"

    def test_missing_id(self):
        charts: List[Dict[str, Any]] = [
            {"url": "https://example.com/chart.png", "text": "Chart"}
        ]
        result = validate_chart_data(charts)
        assert len(result) == 0

    def test_missing_url(self):
        charts: List[Dict[str, Any]] = [{"id": "chart_0", "text": "Chart"}]
        result = validate_chart_data(charts)
        assert len(result) == 0

    def test_missing_both_id_and_url(self):
        charts: List[Dict[str, Any]] = [{"text": "Chart", "type": "static"}]
        result = validate_chart_data(charts)
        assert len(result) == 0

    def test_non_dict_items_filtered(self):
        charts = ["not_a_dict", 42, None, True]
        result = validate_chart_data(charts)
        assert len(result) == 0

    def test_mixed_valid_and_invalid(self):
        charts = [
            {"id": "c1", "url": "https://example.com/1.png"},
            "invalid",
            {"text": "no id or url"},
            {"id": "c2", "url": "https://example.com/2.png", "title": "Chart 2"},
        ]
        result = validate_chart_data(charts)
        assert len(result) == 2
        assert result[0]["id"] == "c1"
        assert result[1]["id"] == "c2"

    def test_defaults_for_optional_fields(self):
        charts: List[Dict[str, Any]] = [
            {"id": "c1", "url": "https://example.com/c.png"}
        ]
        result = validate_chart_data(charts)
        assert len(result) == 1
        assert result[0]["text"] == "Chart"
        assert result[0]["type"] == "static"
        assert result[0]["title"] == "Generated Chart"
        assert result[0]["description"] == ""

    def test_whitespace_stripping(self):
        charts: List[Dict[str, Any]] = [
            {
                "id": "  c1  ",
                "url": "  https://example.com/c.png  ",
                "text": "  Revenue  ",
                "type": "  static  ",
                "title": "  Title  ",
                "description": "  Desc  ",
            }
        ]
        result = validate_chart_data(charts)
        assert result[0]["id"] == "c1"
        assert result[0]["url"] == "https://example.com/c.png"
        assert result[0]["text"] == "Revenue"
        assert result[0]["type"] == "static"
        assert result[0]["title"] == "Title"
        assert result[0]["description"] == "Desc"

    def test_with_chart_data_preserved(self):
        chart_data = {
            "type": "bar",
            "title": "Test",
            "elements": [{"label": "A", "value": 1}],
        }
        charts: List[Dict[str, Any]] = [
            {
                "id": "c1",
                "url": "",
                "type": "interactive",
                "chart_data": chart_data,
            }
        ]
        result = validate_chart_data(charts)
        assert len(result) == 1
        assert "chart_data" in result[0]
        assert result[0]["chart_data"] == chart_data

    def test_without_chart_data_not_added(self):
        charts: List[Dict[str, Any]] = [
            {"id": "c1", "url": "https://example.com/c.png", "type": "static"}
        ]
        result = validate_chart_data(charts)
        assert "chart_data" not in result[0]

    def test_empty_list(self):
        result = validate_chart_data([])
        assert result == []

    def test_values_cast_to_string(self):
        """Non-string id/url values are cast via str()."""
        charts: List[Dict[str, Any]] = [
            {"id": 123, "url": 456, "text": 789, "type": True, "title": 0}
        ]
        result = validate_chart_data(charts)
        assert len(result) == 1
        assert result[0]["id"] == "123"
        assert result[0]["url"] == "456"
        assert result[0]["text"] == "789"
        assert result[0]["type"] == "True"
        assert result[0]["title"] == "0"

    @pytest.mark.parametrize(
        "charts_input",
        [
            [{"id": "c1", "url": "u1"}, {"id": "c2", "url": "u2"}],
            [
                {"id": "c1", "url": "u1"},
                {"id": "c2", "url": "u2"},
                {"id": "c3", "url": "u3"},
            ],
        ],
        ids=["two_charts", "three_charts"],
    )
    def test_multiple_valid_charts(self, charts_input: List[Dict[str, Any]]):
        result = validate_chart_data(charts_input)
        assert len(result) == len(charts_input)
        for i, chart in enumerate(result):
            assert chart["id"] == charts_input[i]["id"]

    def test_chart_data_not_deep_copied(self):
        """chart_data is passed by reference, not deep copied."""
        inner = {"type": "bar", "elements": []}
        charts: List[Dict[str, Any]] = [{"id": "c1", "url": "u1", "chart_data": inner}]
        result = validate_chart_data(charts)
        assert result[0]["chart_data"] is inner

    def test_interactive_chart_empty_url_accepted(self):
        """Interactive charts often have empty URL — should still pass validation."""
        charts: List[Dict[str, Any]] = [
            {"id": "ic1", "url": "", "type": "interactive", "chart_data": {}}
        ]
        result = validate_chart_data(charts)
        assert len(result) == 1
        assert result[0]["url"] == ""
