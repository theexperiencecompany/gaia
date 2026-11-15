"""What a waiter is told once the user did what GAIA asked: what is done, and how to pick back up.

Read by the agent model (a chat's executor, a tracked todo run, a workflow run), never shown
to the user as-is.
"""

from types import MappingProxyType
from typing import Final

from app.constants.waits import WaitCondition

#: What the user did, per condition; {name} is the subject's display name.
WAIT_MET_SENTENCES = MappingProxyType(
    {
        WaitCondition.INTEGRATION_CONNECTED: "The user just connected {name}.",
        WaitCondition.WORKFLOW_TRIGGER_CONFIGURED: (
            'The user just finished setting up the trigger of the workflow "{name}".'
        ),
    }
)

WAIT_MET_ENTRY = (
    "{met} You asked them to do this {age} ago (hours and minutes), and the work that "
    "needed it stopped there. Pick it up from where it stopped.\n"
    "First judge whether it still matters. The longer it has been, the more likely the user "
    "moved on, did it another way, or the details changed. If it looks stale, do not run it: "
    "tell the user it is done on their side and ask whether they still want the rest.\n"
    "On your own, only read and search: look things up, fetch, list. Anything that sends, "
    "posts, creates, edits, deletes, pays, or cannot be undone is not yours to do now. Say "
    "exactly what you would do and ask the user to confirm first.\n"
    "Report what you found the way a person would: lead with the point, in plain words, "
    "without announcing what they did at length."
)

#: Why a tracked todo woke when the user did what it was waiting on; the note at the top says what.
WAIT_MET_WAKE_REASON: Final = (
    "The user did what this todo was waiting on, as the note at the top says."
)
