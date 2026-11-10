/** The one WebSocket event that carries words to the user; its `kind` says what the frame holds. */
export const OUTBOX_MESSAGE_EVENT = "outbox.message";

export const OutboxMessageKind = {
  ConversationMessage: "conversation_message",
  Notification: "notification",
} as const;

export type OutboxMessageKind =
  (typeof OutboxMessageKind)[keyof typeof OutboxMessageKind];
