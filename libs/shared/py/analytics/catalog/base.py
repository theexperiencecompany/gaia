"""Base classes of the event catalog: one model per event, owned by exactly one surface."""

from collections.abc import Mapping
from datetime import timedelta
from enum import Enum, StrEnum
import re
import types
from typing import Annotated, ClassVar, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict

from shared.py.analytics.catalog.attribution import Attribution
from shared.py.analytics.catalog.properties import IdKind

EVENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$")

_SCALAR_KINDS: tuple[type, ...] = (bool, int, float)
_COLLECTION_ORIGINS: tuple[object, ...] = (list, tuple, frozenset)


class Surface(StrEnum):
    """The one surface that emits an event; a second emitter for the same action is a double count."""

    SERVER = "server"
    WEB = "web"
    BOT = "bot"
    VOICE = "voice"


class CatalogError(TypeError):
    """An event model breaks the catalog contract: bad name, duplicate name or free-text property."""


_REGISTRY: dict[str, type["AnalyticsEvent"]] = {}


def _is_allowed_kind(annotation: object, metadata: tuple[object, ...] = ()) -> bool:
    """Whether a property annotation is a count, enum, id, duration or boolean (or a list of them)."""
    if annotation is str:
        return any(isinstance(item, IdKind) for item in metadata)
    if isinstance(annotation, type):
        return issubclass(annotation, Enum) or annotation in _SCALAR_KINDS
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Annotated:
        return _is_allowed_kind(args[0], (*metadata, *args[1:]))
    if origin is Literal:
        return all(isinstance(arg, str | int | bool) for arg in args)
    if origin in (Union, types.UnionType):
        return all(arg is type(None) or _is_allowed_kind(arg) for arg in args)
    if origin in _COLLECTION_ORIGINS:
        return all(arg is Ellipsis or _is_allowed_kind(arg) for arg in args)
    return False


class AnalyticsEvent(BaseModel):
    """One analytics event: the ClassVars name it, the fields are its properties.

    A concrete event sets event and budget_per_user_day, the most one user may
    emit in a day before the volume alert treats it as a loop. base_properties
    is what the surface's capture stamps on; at_most_once_ttl gates the event
    to one send per dedupe key for that long.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event: ClassVar[str]
    owner: ClassVar[Surface]
    previous_names: ClassVar[tuple[str, ...]] = ()
    budget_per_user_day: ClassVar[int]
    base_properties: ClassVar[type[BaseModel] | None] = None
    at_most_once_ttl: ClassVar[timedelta | None] = None

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: object) -> None:
        """Validate and register a concrete event the moment its class is defined."""
        super().__pydantic_init_subclass__(**kwargs)
        if "event" not in cls.__dict__:
            return
        if not EVENT_NAME_PATTERN.fullmatch(cls.event):
            raise CatalogError(f"{cls.__name__}: {cls.event!r} is not domain:action")
        if cls.event in _REGISTRY:
            raise CatalogError(
                f"{cls.__name__}: {cls.event!r} is already {_REGISTRY[cls.event].__name__}"
            )
        for field_name, field in cls.model_fields.items():
            if not _is_allowed_kind(field.annotation, tuple(field.metadata)):
                raise CatalogError(
                    f"{cls.__name__}.{field_name}: {field.annotation!r} is not a count, "
                    "enum, id kind, duration or boolean"
                )
        if cls.base_properties is not None:
            shadowed = cls.model_fields.keys() & cls.base_properties.model_fields.keys()
            if shadowed:
                raise CatalogError(
                    f"{cls.__name__}: {sorted(shadowed)} shadow the stamped base properties"
                )
        if not isinstance(getattr(cls, "budget_per_user_day", None), int):
            raise CatalogError(f"{cls.__name__}: budget_per_user_day must be set")
        _REGISTRY[cls.event] = cls

    def to_properties(self) -> dict[str, object]:
        """Dump the PostHog properties, leaving a None field out rather than sending null."""
        return self.model_dump(mode="json", exclude_none=True)


class ServerEvent(AnalyticsEvent):
    """An event the API (or its workers) owns and emits."""

    owner: ClassVar[Surface] = Surface.SERVER
    base_properties: ClassVar[type[BaseModel] | None] = Attribution


class WebEvent(AnalyticsEvent):
    """A browser-only interaction the server never sees."""

    owner: ClassVar[Surface] = Surface.WEB


class BotEvent(AnalyticsEvent):
    """An event the bot runtime owns: platform I/O the API never sees."""

    owner: ClassVar[Surface] = Surface.BOT


class VoiceEvent(AnalyticsEvent):
    """An event the LiveKit voice worker owns."""

    owner: ClassVar[Surface] = Surface.VOICE
    base_properties: ClassVar[type[BaseModel] | None] = Attribution


def registered_events() -> Mapping[str, type[AnalyticsEvent]]:
    """Every concrete event defined so far, keyed by event name."""
    return types.MappingProxyType(_REGISTRY)


__all__ = [
    "EVENT_NAME_PATTERN",
    "AnalyticsEvent",
    "BotEvent",
    "CatalogError",
    "ServerEvent",
    "Surface",
    "VoiceEvent",
    "WebEvent",
    "registered_events",
]
