import type { ReportSettledOutcome } from "@shared/api/generated";

/** The one WebSocket event that carries words to the user; its `kind` says what the frame holds. */
export const OUTBOX_MESSAGE_EVENT = "outbox.message";

export const OutboxMessageKind = {
  ConversationMessage: "conversation_message",
  ReportSettled: "report_settled",
} as const;

export type OutboxMessageKind =
  (typeof OutboxMessageKind)[keyof typeof OutboxMessageKind];

/** Names for how a run behind a status chip ended; the values are the backend's ReportSettledOutcome. */
export const SettledOutcome = {
  DeliveredHere: "delivered_here",
  DeliveredElsewhere: "delivered_elsewhere",
  Recorded: "recorded",
  Failed: "failed",
} as const satisfies Record<string, ReportSettledOutcome>;
