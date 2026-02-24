/**
 * Gmail Trigger Handler
 *
 * Handles UI configuration for Gmail/email triggers.
 * gmail_poll_inbox supports configurable polling interval.
 */

"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { useState } from "react";

import type { RegisteredHandler, TriggerSettingsProps } from "../registry";
import type { TriggerConfig } from "../types";

// =============================================================================
// TYPE DEFINITIONS
// =============================================================================

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

const PRESET_INTERVALS = [5, 15, 30, 60] as const;

function GmailPollSettings({
  triggerConfig,
  onConfigChange,
}: TriggerSettingsProps) {
  const config = triggerConfig as GmailPollConfig;
  const currentInterval = config.trigger_data?.interval ?? 15;
  const [inputValue, setInputValue] = useState(String(currentInterval));

  const updateInterval = (minutes: number) => {
    const clamped = Math.min(1440, Math.max(1, minutes));
    setInputValue(String(clamped));
    onConfigChange({
      ...triggerConfig,
      trigger_data: {
        trigger_name: config.trigger_name || "gmail_poll_inbox",
        ...config.trigger_data,
        interval: clamped,
      },
    });
  };

  const handleInputChange = (value: string) => {
    setInputValue(value);
    const parsed = parseInt(value, 10);
    if (!Number.isNaN(parsed) && parsed >= 1 && parsed <= 1440) {
      updateInterval(parsed);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {PRESET_INTERVALS.map((mins) => (
          <Button
            key={mins}
            size="sm"
            variant={currentInterval === mins ? "flat" : "bordered"}
            color={currentInterval === mins ? "primary" : "default"}
            className="min-w-14 text-xs"
            onPress={() => updateInterval(mins)}
          >
            {mins}m
          </Button>
        ))}
        <Input
          type="number"
          aria-label="Custom poll interval in minutes"
          placeholder="Custom"
          min={1}
          max={1440}
          className="w-28"
          size="sm"
          classNames={{
            input:
              "text-xs [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none",
          }}
          value={
            PRESET_INTERVALS.includes(
              currentInterval as (typeof PRESET_INTERVALS)[number],
            )
              ? ""
              : inputValue
          }
          onValueChange={handleInputChange}
          endContent={
            <span className="pointer-events-none text-xs text-zinc-500">
              min
            </span>
          }
        />
      </div>
      <p className="text-xs text-zinc-500">
        Check inbox every {currentInterval}{" "}
        {currentInterval === 1 ? "minute" : "minutes"} for new emails
      </p>
    </div>
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
