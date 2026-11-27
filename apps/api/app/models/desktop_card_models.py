"""The screenshot_data card's payload: the desktop screen take_screenshot captured, as the chat shows it."""

from app.schemas.common import ResponseModel


class ScreenshotCard(ResponseModel):
    """A captured screen's thumbnail as a data URL, with the screen's size when the desktop app reported it."""

    thumbnail: str
    width: int | None
    height: int | None
