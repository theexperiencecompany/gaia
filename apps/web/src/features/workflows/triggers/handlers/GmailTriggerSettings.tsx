/**
 * Gmail Trigger Settings
 *
 * UI configuration for Gmail/email triggers.
 * gmail_poll_inbox supports configurable polling interval.
 */

"use client";

import { IntervalPicker } from "../components/IntervalPicker";
import {
  TriggerSettingRow,
  TriggerSettingsCard,
} from "../components/TriggerSettingsCard";
import type { TriggerSettingsProps } from "../registry";
import type { TriggerConfig } from "../types";

interface GmailPollTriggerData {
  trigger_name: string;
  interval: number;
}

export interface GmailPollConfig extends TriggerConfig {
  trigger_name?: string;
  trigger_data?: GmailPollTriggerData;
}

// Mirrors the backend cap (MAX_GMAIL_POLL_INTERVAL_MINUTES) so the picker can
// offer day-scale intervals (e.g. a weekly digest) without producing a value
// the API would reject.
const GMAIL_MAX_INTERVAL_MINUTES = 60 * 24 * 30; // 30 days

// Spread across the useful triage range: every 15m, hourly, a few times a day,
// and once a day. Anything else is available via "Custom".
const GMAIL_INTERVAL_PRESETS = [15, 60, 360, 1440]; // 15m, 1h, 6h, 1d

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
export function GmailTriggerSettings(props: TriggerSettingsProps) {
  const config = props.triggerConfig as GmailPollConfig;
  if (config.trigger_name !== "gmail_poll_inbox") return null;
  return <GmailPollSettings {...props} />;
}
