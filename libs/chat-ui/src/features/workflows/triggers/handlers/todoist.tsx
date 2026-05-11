/**
 * Todoist Trigger Handler
 *
 * Handles UI configuration for Todoist triggers.
 * Simple trigger with no additional configuration needed.
 */

import type { RegisteredHandler } from "../registry";
import type { TriggerConfig } from "../types";

// =============================================================================
// HANDLER DEFINITION
// =============================================================================

export const todoistTriggerHandler: RegisteredHandler = {
  triggerSlugs: ["todoist_new_task_created"],

  createDefaultConfig: (slug: string): TriggerConfig => ({
    type: "integration",
    enabled: true,
    trigger_name: slug,
    trigger_data: {
      trigger_name: slug,
    },
  }),

  // No custom settings component needed - simple trigger
  SettingsComponent: undefined,

  getDisplayInfo: () => ({
    label: "on new task",
    integrationId: "todoist",
  }),
};
