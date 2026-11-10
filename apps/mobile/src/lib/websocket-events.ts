/**
 * WebSocket event type constants.
 * These match the event types emitted by the backend over the WS connection.
 */
export const WS_EVENTS = {
  OUTBOX_MESSAGE: "outbox.message",
  NOTIFICATION_READ: "notification.read",
  NOTIFICATION_UPDATED: "notification.updated",
  TODO_CREATED: "todo.created",
  TODO_UPDATED: "todo.updated",
  TODO_DELETED: "todo.deleted",
  WORKFLOW_EXECUTION: "workflow.execution",
  WORKFLOW_RUN_STARTED: "workflow.run.started",
  WORKFLOW_RUN_COMPLETED: "workflow.run.completed",
  WORKFLOW_RUN_FAILED: "workflow.run.failed",
  CONVERSATION_UPDATED: "conversation.updated",
  ONBOARDING_COMPLETE: "onboarding.complete",
  INTEGRATION_CONNECTED: "integration.connected",
  INTEGRATION_DISCONNECTED: "integration.disconnected",
} as const;

export type WsEventType = (typeof WS_EVENTS)[keyof typeof WS_EVENTS];

export const OUTBOX_MESSAGE_KINDS = {
  CONVERSATION_MESSAGE: "conversation_message",
  NOTIFICATION: "notification",
} as const;

/** Whether an `outbox.message` frame carries a notification record (not a chat message). */
export function isOutboxNotification(message: unknown): boolean {
  return (
    typeof message === "object" &&
    message !== null &&
    "kind" in message &&
    message.kind === OUTBOX_MESSAGE_KINDS.NOTIFICATION
  );
}
