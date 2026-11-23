"""Registry names of the compiled agent graphs."""

from enum import StrEnum


class GraphName(StrEnum):
    """The @lazy_provider name each tier graph registers under and GraphManager.get_graph looks up."""

    #: Its thread id is the conversation id; tools/lints/comms_graph_owner.py fences who may name it.
    COMMS = "comms_agent"
    EXECUTOR = "executor_agent"
