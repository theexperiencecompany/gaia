"""Chart processing utilities for code execution."""

import base64
import io
import re
import time
import uuid
from typing import Dict, List, Any

import cloudinary.uploader

from app.config.loggers import chat_logger as logger


async def upload_chart_to_cloudinary(
    chart_bytes: bytes, chart_title: str = "chart", user_id: str | None = None
) -> str | None:
    """
    Upload a chart image to Cloudinary and return the secure URL.

    Args:
        chart_bytes: The chart image data as bytes
        chart_title: Title for the chart (used in filename)
        user_id: User ID for organizing uploads

    Returns:
        Secure URL of uploaded chart or None if upload fails

    Raises:
        Exception: If upload fails (logged but not re-raised)
    """
    try:
        chart_id = str(uuid.uuid4())
        timestamp = int(time.time())

        # Create a clean slug from chart title
        clean_title = re.sub(r"[^a-zA-Z0-9\s]", "", chart_title)
        slug = re.sub(r"\s+", "_", clean_title.lower())[:30]

        # Create public_id with proper organization
        if user_id:
            public_id = f"charts/{user_id}/{timestamp}_{slug}_{chart_id}"
        else:
            public_id = f"charts/{timestamp}_{slug}_{chart_id}"

        upload_result = cloudinary.uploader.upload(
            io.BytesIO(chart_bytes),
            resource_type="image",
            public_id=public_id,
            overwrite=True,
        )

        image_url = upload_result.get("secure_url")
        if image_url:
            logger.info(f"Chart uploaded successfully. URL: {image_url}")
            return image_url
        else:
            logger.error("Missing secure_url in Cloudinary upload response")
            return None

    except Exception as e:
        logger.error(f"Failed to upload chart to Cloudinary: {str(e)}", exc_info=True)
        return None


async def process_chart_results(
    execution_results: List, user_id: str = "anonymous"
) -> tuple[List[Dict[str, Any]], List[str]]:
    """
    Process execution results to extract and upload charts.

    Args:
        execution_results: List of execution results from E2B
        user_id: User ID for chart uploads

    Returns:
        Tuple of (charts_list, error_messages)
    """
    charts: List[Dict[str, Any]] = []
    chart_errors: List[str] = []

    if not execution_results:
        logger.info("No execution results to process for charts")
        return charts, chart_errors

    logger.info(f"Processing {len(execution_results)} execution results for charts")

    for i, result in enumerate(execution_results):
        logger.info(
            f"Processing result {i}: type={type(result)}, attributes={dir(result)}"
        )
        logger.info(
            f"Processing result {i}: has_png={hasattr(result, 'png')}, has_chart={hasattr(result, 'chart')}"
        )
        if hasattr(result, "png"):
            logger.info(f"Result {i} PNG value: {result.png is not None}")
        if hasattr(result, "chart"):
            logger.info(f"Result {i} chart value: {result.chart is not None}")

        # Check for static chart (PNG base64) - upload as image
        if hasattr(result, "png") and result.png:
            try:
                chart_bytes = base64.b64decode(result.png)
                chart_url = await upload_chart_to_cloudinary(
                    chart_bytes, f"chart_{i}", user_id
                )
                if chart_url:
                    charts.append(
                        {
                            "id": f"chart_{i}",
                            "url": chart_url,
                            "text": f"Chart {i + 1}",
                            "type": "static",
                            "title": f"Generated Chart {i + 1}",
                            "description": "Static chart generated from code execution",
                        }
                    )
                    logger.info(f"Successfully processed static chart {i + 1}")
                else:
                    error_msg = f"Failed to upload static chart {i + 1} to Cloudinary"
                    chart_errors.append(error_msg)
                    logger.warning(error_msg)
            except Exception as e:
                error_msg = f"Failed to process static chart {i + 1}: {str(e)}"
                chart_errors.append(error_msg)
                logger.error(error_msg, exc_info=True)

        # Check for interactive chart data - send structured data to frontend
        if hasattr(result, "chart") and result.chart:
            try:
                chart_data = result.chart
                chart_title = getattr(chart_data, "title", f"Interactive Chart {i + 1}")
                chart_type = getattr(chart_data, "type", "bar")

                charts.append(
                    {
                        "id": f"interactive_chart_{i}",
                        "url": "",  # No URL needed for interactive charts
                        "text": chart_title,
                        "type": "interactive",
                        "title": chart_title,
                        "description": f"Interactive {chart_type} chart with dynamic data",
                        "chart_data": {
                            "type": str(chart_type).lower().replace("charttype.", ""),
                            "title": chart_title,
                            "x_label": getattr(chart_data, "x_label", ""),
                            "y_label": getattr(chart_data, "y_label", ""),
                            "x_unit": getattr(chart_data, "x_unit", None),
                            "y_unit": getattr(chart_data, "y_unit", None),
                            "elements": [
                                {
                                    "label": getattr(element, "label", ""),
                                    "value": getattr(element, "value", 0),
                                    "group": getattr(element, "group", ""),
                                }
                                for element in getattr(chart_data, "elements", [])
                            ],
                        },
                    }
                )
                logger.info(
                    f"Successfully processed interactive chart {i + 1}: {chart_type}"
                )
            except Exception as e:
                error_msg = f"Failed to process interactive chart {i + 1}: {str(e)}"
                chart_errors.append(error_msg)
                logger.error(error_msg, exc_info=True)

    return charts, chart_errors


def validate_chart_data(charts: List[Dict]) -> List[Dict]:
    """
    Validate and sanitize chart data.

    Args:
        charts: List of chart dictionaries

    Returns:
        List of validated chart dictionaries
    """
    validated_charts = []

    for chart in charts:
        if not isinstance(chart, dict):
            continue

        # Ensure required fields exist
        if "id" not in chart or "url" not in chart:
            continue

        # Sanitize and validate
        validated_chart = {
            "id": str(chart.get("id", "")).strip(),
            "url": str(chart.get("url", "")).strip(),
            "text": str(chart.get("text", "Chart")).strip(),
            "type": str(chart.get("type", "static")).strip(),
            "title": str(chart.get("title", "Generated Chart")).strip(),
            "description": str(chart.get("description", "")).strip(),
        }

        # Preserve chart_data for interactive charts
        if "chart_data" in chart:
            validated_chart["chart_data"] = chart["chart_data"]

        validated_charts.append(validated_chart)

    return validated_charts
