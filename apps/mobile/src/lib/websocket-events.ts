/**
 * WebSocket event type constants.
 * These match the event types emitted by the backend over the WS connection.
 */
export const WS_EVENTS = {
  NOTIFICATION_DELIVERED: "notification.delivered",
  NOTIFICATION_READ: "notification.read",
  NOTIFICATION_UPDATED: "notification.updated",
  TODO_CREATED: "todo.created",
  TODO_UPDATED: "todo.updated",
  WORKFLOW_EXECUTION: "workflow.execution",
  CONVERSATION_UPDATED: "conversation.updated",
  ONBOARDING_COMPLETE: "onboarding.complete",
  INTEGRATION_CONNECTED: "integration.connected",
  INTEGRATION_DISCONNECTED: "integration.disconnected",
} as const;

export type WsEventType = (typeof WS_EVENTS)[keyof typeof WS_EVENTS];
