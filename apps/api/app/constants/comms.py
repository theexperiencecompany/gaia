"""The tools comms ends a turn with when it is not worth a message.

Shared by the prompts (which tell comms to call them), the tools themselves, the
graph (which ends the turn after them) and the run's outcome (which reads them).
"""

REACT_TOOL_NAME = "react"
STAY_SILENT_TOOL_NAME = "stay_silent"
#: Names the messages a reply answers; ends the turn when it is the step's only kind of call.
ANSWERED_TOOL_NAME = "answered"
#: The tools whose call ends a comms turn: a message calling only these is the reply itself.
TURN_ENDING_TOOL_NAMES = frozenset({ANSWERED_TOOL_NAME, REACT_TOOL_NAME, STAY_SILENT_TOOL_NAME})
