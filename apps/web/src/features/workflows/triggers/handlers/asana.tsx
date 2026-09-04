/**
 * Asana Trigger Handler
 *
 * Handles UI configuration for Asana triggers.
 */

import type { RegisteredHandler } from "../registry";
import type { TriggerConfig } from "../types";
import { AsanaSettings } from "./AsanaSettings";

// =============================================================================
// HANDLER DEFINITION
// =============================================================================

export const asanaTriggerHandler: RegisteredHandler = {
  triggerSlugs: ["asana_task_trigger"],

  createDefaultConfig: (slug: string): TriggerConfig => ({
    type: "integration",
    enabled: true,
    trigger_name: slug,
    trigger_data: {
      trigger_name: slug,
      project_gid: "",
    },
  }),

  SettingsComponent: AsanaSettings,

  getDisplayInfo: () => ({
    label: "on new task",
    integrationId: "asana",
  }),
};
