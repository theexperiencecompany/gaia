"""Per-pod registry of device WebSockets this process currently owns."""

from typing import Any, ClassVar, cast

from fastapi import WebSocket

from app.constants.log_tags import LogTag
from shared.py.wide_events import log


class DeviceConnectionManager:
    """Singleton tracking device sockets held by *this* pod.

    Cross-pod delivery is Redis pub/sub (see ``bridge.py``); this only maps a
    device_id to the local socket so the down-relay task can write to it.
    """

    _instance: ClassVar[Any] = None

    def __new__(cls) -> "DeviceConnectionManager":
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._connections = {}
            cls._instance = instance
        return cast("DeviceConnectionManager", cls._instance)

    def __init__(self) -> None:
        # _connections is set in __new__; annotate for mypy.
        self._connections: dict[str, WebSocket]

    def add(self, device_id: str, websocket: WebSocket) -> None:
        self._connections[device_id] = websocket
        log.info(f"{LogTag.API} Device socket registered", device_id=device_id)

    def remove(self, device_id: str, websocket: WebSocket) -> None:
        # Only drop if the stored socket is the one closing — a reconnect on
        # another pod (or a fast re-dial) must not evict the live socket.
        if self._connections.get(device_id) is websocket:
            del self._connections[device_id]
            log.info(f"{LogTag.API} Device socket unregistered", device_id=device_id)

    def get(self, device_id: str) -> WebSocket | None:
        return self._connections.get(device_id)

    def owns(self, device_id: str) -> bool:
        return device_id in self._connections


device_connection_manager = DeviceConnectionManager()
