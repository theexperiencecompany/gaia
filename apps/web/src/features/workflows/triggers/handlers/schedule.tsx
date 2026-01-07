/**
 * Schedule and Manual Trigger Handlers
 *
 * These are built-in triggers that don't require external integrations.
 */

import type { RegisteredHandler } from "../registry";
import type { TriggerConfig } from "../types";

// =============================================================================
// SCHEDULE HANDLER
// =============================================================================

export const scheduleTriggerHandler: RegisteredHandler = {
  triggerSlugs: ["schedule"],

  createDefaultConfig: (): TriggerConfig => ({
    type: "schedule",
    enabled: true,
    cron_expression: "0 9 * * *", // Daily at 9 AM
    timezone: "UTC",
  }),

  // Schedule builder is handled directly in WorkflowModal
  SettingsComponent: undefined,

  getDisplayInfo: () => ({
    label: "scheduled",
    integrationId: null,
  }),
};

// =============================================================================
// MANUAL HANDLER
// =============================================================================

export const manualTriggerHandler: RegisteredHandler = {
  triggerSlugs: ["manual"],

  createDefaultConfig: (): TriggerConfig => ({
    type: "manual",
    enabled: true,
  }),

  SettingsComponent: undefined,

  getDisplayInfo: () => ({
    label: "manual trigger",
    integrationId: null,
  }),
};
