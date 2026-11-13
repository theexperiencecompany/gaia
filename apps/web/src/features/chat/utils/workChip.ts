import type { IMessage } from "@/lib/db/chatDb";
import { ReportSettledOutcome } from "@/lib/websocket/outboxEvents";

/** The backend message kind of a turn that handed work off and said nothing. */
export const ACCEPTED_MESSAGE_KIND = "accepted";

const SILENT_KINDS = new Set<string | undefined>([
  ACCEPTED_MESSAGE_KIND,
  "emoji_ack",
]);

export type WorkChipState = "working" | "done" | "nothing_new" | "failed";

/**
 * Whether any assistant text followed the accepted turn. Only the read for a
 * turn whose run's outcome never reached this device (another device settled
 * it, or the event was missed): it cannot tell which run the text answers.
 */
function isFollowedByAnswer(
  messages: IMessage[],
  acceptedMessageId: string,
): boolean {
  const index = messages.findIndex((m) => m.id === acceptedMessageId);
  if (index === -1) return false;
  return messages
    .slice(index + 1)
    .some(
      (m) =>
        m.role === "assistant" &&
        m.content.trim().length > 0 &&
        !SILENT_KINDS.has(m.kind ?? undefined),
    );
}

/**
 * Where the work an accepted turn started stands: the outcome the server
 * reported for that turn's own run, else whether an answer followed it.
 */
export function workChipState(
  messages: IMessage[],
  acceptedMessageId: string,
): WorkChipState {
  const accepted = messages.find((m) => m.id === acceptedMessageId);
  switch (accepted?.workOutcome) {
    case ReportSettledOutcome.DeliveredHere:
    case ReportSettledOutcome.DeliveredElsewhere:
      return "done";
    case ReportSettledOutcome.Recorded:
      return "nothing_new";
    case ReportSettledOutcome.Failed:
      return "failed";
    default:
      return isFollowedByAnswer(messages, acceptedMessageId)
        ? "done"
        : "working";
  }
}
