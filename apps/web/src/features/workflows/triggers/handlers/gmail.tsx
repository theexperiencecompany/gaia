/**
 * Gmail Trigger Handler
 *
 * Handles UI configuration for Gmail/email triggers.
 * gmail_poll_inbox supports configurable polling interval.
 */

"use client";

import { IntervalPicker } from "../components/IntervalPicker";
import {
  TriggerSettingRow,
  TriggerSettingsCard,
} from "../components/TriggerSettingsCard";
import type { RegisteredHandler, TriggerSettingsProps } from "../registry";
import type { TriggerConfig } from "../types";

// =============================================================================
// TYPE DEFINITIONS
// =============================================================================

// Mirrors the backend cap (MAX_GMAIL_POLL_INTERVAL_MINUTES) so the picker can
// offer day-scale intervals (e.g. a weekly digest) without producing a value
// the API would reject.
const GMAIL_MAX_INTERVAL_MINUTES = 60 * 24 * 30; // 30 days

// Spread across the useful triage range: every 15m, hourly, a few times a day,
// and once a day. Anything else is available via "Custom".
const GMAIL_INTERVAL_PRESETS = [15, 60, 360, 1440]; // 15m, 1h, 6h, 1d

interface GmailPollTriggerData {
  trigger_name: string;
  interval: number;
}

interface GmailPollConfig extends TriggerConfig {
  trigger_name?: string;
  trigger_data?: GmailPollTriggerData;
}

// =============================================================================
// POLL INBOX SETTINGS COMPONENT
// =============================================================================

function GmailPollSettings({
  triggerConfig,
  onConfigChange,
}: TriggerSettingsProps) {
  const config = triggerConfig as GmailPollConfig;
  const currentInterval = config.trigger_data?.interval ?? 15;

  const updateInterval = (minutes: number) => {
    onConfigChange({
      ...triggerConfig,
      trigger_data: {
        trigger_name: config.trigger_name || "gmail_poll_inbox",
        ...config.trigger_data,
        interval: minutes,
      },
    });
  };

  return (
    <TriggerSettingsCard>
      <TriggerSettingRow label="Check my inbox every">
        <IntervalPicker
          value={currentInterval}
          onChange={updateInterval}
          presets={GMAIL_INTERVAL_PRESETS}
          maxMinutes={GMAIL_MAX_INTERVAL_MINUTES}
        />
      </TriggerSettingRow>
    </TriggerSettingsCard>
  );
}

// Wrapper that only renders settings for poll_inbox — other gmail triggers have none
function GmailTriggerSettings(props: TriggerSettingsProps) {
  const config = props.triggerConfig as GmailPollConfig;
  if (config.trigger_name !== "gmail_poll_inbox") return null;
  return <GmailPollSettings {...props} />;
}

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
