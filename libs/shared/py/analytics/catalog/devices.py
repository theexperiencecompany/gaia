"""Device bridge and desktop popup events."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier

__all__ = [
    "DesktopPopupDismissed",
    "DesktopPopupOpened",
    "DeviceApproved",
    "DeviceRevoked",
    "DeviceSelfPaired",
]


class DeviceSelfPaired(ServerEvent):
    """An authenticated host paired itself as a device."""

    event: ClassVar[str] = "device:self_paired"
    budget_per_user_day: ClassVar[int] = 50

    client: Identifier
    platform: Identifier


class DeviceApproved(ServerEvent):
    """A user approved a device's pairing code."""

    event: ClassVar[str] = "device:approved"
    budget_per_user_day: ClassVar[int] = 50


class DeviceRevoked(ServerEvent):
    """A user revoked a paired device."""

    event: ClassVar[str] = "device:revoked"
    budget_per_user_day: ClassVar[int] = 50


class DesktopPopupOpened(WebEvent):
    """The desktop assistant popup was summoned; Electron IPC the server never sees."""

    event: ClassVar[str] = "desktop_popup:opened"
    budget_per_user_day: ClassVar[int] = 50

    triggered_by_wake_word: bool


class DesktopPopupDismissed(WebEvent):
    """The desktop assistant popup was dismissed."""

    event: ClassVar[str] = "desktop_popup:dismissed"
    budget_per_user_day: ClassVar[int] = 50
