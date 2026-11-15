"""The tools comms ends a turn with when it is not worth a message.

Shared by the prompts (which tell comms to call them), the tools themselves, the
graph (which ends the turn after them) and the run's outcome (which reads them).
"""

REACT_TOOL_NAME = "react"
STAY_SILENT_TOOL_NAME = "stay_silent"
