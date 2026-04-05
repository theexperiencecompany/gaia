/**
 * PostHog event name constants for GAIA CLI analytics.
 *
 * Naming follows the project-wide `domain:action` convention
 * used in the web app's `src/lib/analytics.ts`.
 */

export const CLI_EVENTS = {
  COMMAND_STARTED: "cli:command_started",
  COMMAND_COMPLETED: "cli:command_completed",
  COMMAND_FAILED: "cli:command_failed",
  SETUP_COMPLETED: "cli:setup_completed",
  SERVICES_STARTED: "cli:services_started",
} as const;

export type CliEventName = (typeof CLI_EVENTS)[keyof typeof CLI_EVENTS];
