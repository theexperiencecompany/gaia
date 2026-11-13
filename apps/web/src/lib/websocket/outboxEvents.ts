/** The one WebSocket event that carries words to the user; its `kind` says what the frame holds. */
export const OUTBOX_MESSAGE_EVENT = "outbox.message";

export const OutboxMessageKind = {
  ConversationMessage: "conversation_message",
  Notification: "notification",
  ReportSettled: "report_settled",
} as const;

export type OutboxMessageKind =
  (typeof OutboxMessageKind)[keyof typeof OutboxMessageKind];

/** How the run behind a status chip ended; mirrors the backend's ReportSettledOutcome. */
export const ReportSettledOutcome = {
  DeliveredHere: "delivered_here",
  DeliveredElsewhere: "delivered_elsewhere",
  Recorded: "recorded",
  Failed: "failed",
} as const;

export type ReportSettledOutcome =
  (typeof ReportSettledOutcome)[keyof typeof ReportSettledOutcome];
