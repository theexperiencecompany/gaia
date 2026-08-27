/**
 * Slack Trigger Handler
 *
 * Handles UI configuration for Slack triggers with message filtering.
 */

import type { RegisteredHandler } from "../registry";
import type { TriggerConfig } from "../types";
import type { SlackConfig, SlackTriggerData } from "./SlackSettings";
import { SlackSettings } from "./SlackSettings";

// =============================================================================
// HANDLER DEFINITION
// =============================================================================

export const slackTriggerHandler: RegisteredHandler = {
  triggerSlugs: ["slack_new_message", "slack_channel_created"],

  createDefaultConfig: (slug: string): TriggerConfig => {
    const baseTriggerData: SlackTriggerData = {
      trigger_name: slug,
    };

    if (slug === "slack_new_message") {
      baseTriggerData.channel_ids = [];
      baseTriggerData.exclude_bot_messages = false;
      baseTriggerData.exclude_direct_messages = false;
      baseTriggerData.exclude_group_messages = false;
      baseTriggerData.exclude_mpim_messages = false;
      baseTriggerData.exclude_thread_replies = false;
    }

    return {
      type: "integration",
      enabled: true,
      trigger_name: slug,
      trigger_data: baseTriggerData,
    };
  },

  SettingsComponent: SlackSettings,

  getDisplayInfo: (config) => {
    const triggerName = (config as SlackConfig).trigger_name || config.type;
    return {
      label:
        triggerName === "slack_channel_created"
          ? "on channel created"
          : "on new message",
      integrationId: "slack",
    };
  },
};
