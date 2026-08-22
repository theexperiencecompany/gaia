/**
 * Gmail Trigger Handler
 *
 * Handles UI configuration for Gmail/email triggers.
 * gmail_poll_inbox supports configurable polling interval.
 */

import type { RegisteredHandler } from "../registry";
import type { TriggerConfig } from "../types";
import { GmailTriggerSettings } from "./GmailTriggerSettings";

// =============================================================================
// HANDLER DEFINITION
// =============================================================================

export const gmailTriggerHandler: RegisteredHandler = {
  triggerSlugs: ["gmail_new_message", "email", "gmail_poll_inbox"],

  createDefaultConfig: (slug: string): TriggerConfig => {
    if (slug === "gmail_poll_inbox") {
      return {
        type: "integration",
        enabled: true,
        trigger_name: slug,
        trigger_data: {
          trigger_name: slug,
          interval: 15,
        },
      };
    }
    return {
      type: "integration",
      enabled: true,
      trigger_name: slug,
      trigger_data: {
        trigger_name: slug,
      },
    };
  },

  SettingsComponent: GmailTriggerSettings,

  getDisplayInfo: () => ({
    label: "on new emails",
    integrationId: "gmail",
  }),
};
