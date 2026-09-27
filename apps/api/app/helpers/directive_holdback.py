"""Hold a comms turn's frames back while its text could still be a whole-turn directive.

Comms streams text as the model writes it, but a turn that is one <EMOJI> or
<SILENCE> tag is a control directive, never a reply, and no client may see it.
From the first frame emitted while the turn so far could still become one,
frames queue in order; they are released the moment it no longer can, and a
turn that ends as a directive releases everything but its text.
"""

from dataclasses import dataclass, field

from app.agents.core.comms_directive import could_become_comms_directive, interpret_comms_output
from app.constants.comms import CommsDirectiveKind
from app.services.chat.chunks import extract_response_text


@dataclass(slots=True)
class DirectiveHoldback:
    """The frames of one comms turn not yet safe to publish."""

    held: list[str] = field(default_factory=list)

    def admit(self, frame: str, turn_so_far: str) -> list[str]:
        """Return the frames publishable now that frame was emitted with the turn at turn_so_far."""
        if turn_so_far and could_become_comms_directive(turn_so_far):
            self.held.append(frame)
            return []
        released, self.held = [*self.held, frame], []
        return released

    def settle(self, complete_message: str) -> list[str]:
        """Release what is held at the end of the turn, minus the text of a turn that is a directive."""
        held, self.held = self.held, []
        if interpret_comms_output(complete_message).kind is CommsDirectiveKind.REPLY:
            return held
        return [frame for frame in held if not extract_response_text(frame)]
