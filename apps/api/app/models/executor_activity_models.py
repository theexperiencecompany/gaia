"""What a conversation's executor is doing right now, as read off its busy lock."""

from dataclasses import dataclass
from enum import StrEnum


class ExecutorActivity(StrEnum):
    """What the conversation's executor is doing, as the busy lock and its liveness say."""

    IDLE = "idle"
    RUNNING = "running"
    #: The lock is held by a run whose process died; nothing is working on it.
    DEAD = "dead"


@dataclass(frozen=True)
class ExecutorActivitySnapshot:
    activity: ExecutorActivity
    task_id: str = ""
    #: The busy lock's value, naming the holding run; empty when nothing holds it.
    holder: str = ""
