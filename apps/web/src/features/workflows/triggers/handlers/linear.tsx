/**
 * Linear Trigger Handler
 *
 * Handles UI configuration for Linear triggers.
 */

import type { RegisteredHandler } from "../registry";
import type { TriggerConfig } from "../types";
import type { LinearConfig } from "./LinearSettings";
import { LinearSettings } from "./LinearSettings";

// =============================================================================
// HANDLER DEFINITION
// =============================================================================

export const linearTriggerHandler: RegisteredHandler = {
  triggerSlugs: [
    "linear_issue_created",
    "linear_issue_updated",
    "linear_comment_added",
  ],

  createDefaultConfig: (slug: string): TriggerConfig => ({
    type: "integration",
    enabled: true,
    trigger_name: slug,
    trigger_data: {
      trigger_name: slug,
      team_id: "",
    },
  }),

  SettingsComponent: LinearSettings,

  getDisplayInfo: (config) => {
    const triggerName = (config as LinearConfig).trigger_name || config.type;
    let label = "on linear event";
    if (triggerName === "linear_issue_created") label = "on new issue";
    if (triggerName === "linear_issue_updated") label = "on issue updated";
    if (triggerName === "linear_comment_added") label = "on new comment";

    return {
      label,
      integrationId: "linear",
    };
  },
};
