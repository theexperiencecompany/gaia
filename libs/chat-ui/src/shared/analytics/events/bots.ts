/**
 * PostHog event name constants for GAIA bot analytics.
 *
 * Naming follows the project-wide `domain:action` convention
 * used in the web app's `src/lib/analytics.ts`.
 */

export const BOT_EVENTS = {
  MESSAGE_RECEIVED: "bot:message_received",
  COMMAND_EXECUTED: "bot:command_executed",
  CHAT_STARTED: "bot:chat_started",
  CHAT_COMPLETED: "bot:chat_completed",
  AUTH_INITIATED: "bot:auth_initiated",
  ERROR: "bot:error",
} as const;

export type BotEventName = (typeof BOT_EVENTS)[keyof typeof BOT_EVENTS];
