/**
 * Gmail Trigger Handler
 *
 * Handles UI configuration for Gmail/email triggers.
 * This is a simple trigger with no additional configuration needed.
 */

import type { RegisteredHandler } from "../registry";
import type { TriggerConfig } from "../types";

// =============================================================================
// HANDLER DEFINITION
// =============================================================================

export const gmailTriggerHandler: RegisteredHandler = {
  triggerSlugs: ["gmail_new_message", "email"],

  createDefaultConfig: (): TriggerConfig => ({
    type: "email",
    enabled: true,
  }),

  // No custom settings component needed - Gmail triggers are simple
  SettingsComponent: undefined,

  getDisplayInfo: () => ({
    label: "on new emails",
    integrationId: "gmail",
  }),
};
