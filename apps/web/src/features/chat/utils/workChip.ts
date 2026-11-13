import type {
  ReportSettledOutcome,
  WorkRunOutcome,
} from "@shared/api/generated";
import type { IMessage } from "@/lib/db/chatDb";
import { SettledOutcome } from "@/lib/websocket/outboxEvents";

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

const SETTLED_STATE_BY_OUTCOME: Record<
  ReportSettledOutcome,
  Exclude<WorkChipState, "working">
> = {
  [SettledOutcome.DeliveredHere]: "done",
  [SettledOutcome.DeliveredElsewhere]: "done",
  [SettledOutcome.Recorded]: "nothing_new",
  [SettledOutcome.Failed]: "failed",
};

/** A turn that started several runs reads as the worst of them: a failure, else something done, else nothing new. */
const SETTLED_STATE_PRECEDENCE = ["failed", "done", "nothing_new"] as const;

function combinedSettledState(
  runs: WorkRunOutcome[] | null | undefined,
): Exclude<WorkChipState, "working"> | undefined {
  const states = new Set(
    (runs ?? []).map((run) => SETTLED_STATE_BY_OUTCOME[run.outcome]),
  );
  return SETTLED_STATE_PRECEDENCE.find((state) => states.has(state));
}

/**
 * Where the work an accepted turn started stands: the outcomes the server
 * recorded for that turn's own runs, else whether an answer followed it.
 */
export function workChipState(
  messages: IMessage[],
  acceptedMessageId: string,
): WorkChipState {
  const accepted = messages.find((m) => m.id === acceptedMessageId);
  return (
    combinedSettledState(accepted?.workOutcomes) ??
    (isFollowedByAnswer(messages, acceptedMessageId) ? "done" : "working")
  );
}
