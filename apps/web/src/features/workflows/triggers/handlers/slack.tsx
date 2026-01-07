/**
 * Slack Trigger Handler
 *
 * Handles UI configuration for Slack triggers with message filtering.
 */

"use client";

import { Button } from "@heroui/button";
import { Checkbox } from "@heroui/checkbox";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { TriggerSelectToggle } from "../components";
import { useTriggerOptions } from "../hooks/useTriggerOptions";
import type { RegisteredHandler, TriggerSettingsProps } from "../registry";
import type { TriggerConfig } from "../types";

function SlackSettings({
  triggerConfig,
  onConfigChange,
}: TriggerSettingsProps) {
  const { integrations, connectIntegration } = useIntegrations();
  const config = triggerConfig as TriggerConfig & {
    channel_ids?: string;
    exclude_bot_messages?: boolean;
    exclude_direct_messages?: boolean;
    exclude_group_messages?: boolean;
    exclude_mpim_messages?: boolean;
    exclude_thread_replies?: boolean;
  };

  const integrationId = "slack";
  const isConnected =
    integrations.find((i) => i.id === integrationId)?.status === "connected";

  const isMessageTrigger = config.type === "slack_new_message";

  // Fetch channel options for message trigger
  const { data: channelOptions, isLoading: isLoadingChannels } =
    useTriggerOptions(
      "slack",
      config.type,
      "channel_ids",
      isMessageTrigger && isConnected,
    );

  // Get current selected values
  const selectedValues = config.channel_ids
    ? config.channel_ids
        .split(",")
        .map((id) => id.trim())
        .filter(Boolean)
    : [];

  if (!isConnected) {
    return (
      <div className="flex flex-col items-center justify-center p-4 space-y-3 bg-zinc-900/50 rounded-lg border border-zinc-800">
        <p className="text-sm text-zinc-400">
          Connect Slack to configure this trigger
        </p>
        <Button
          color="primary"
          variant="flat"
          onPress={() => connectIntegration(integrationId)}
        >
          Connect Slack
        </Button>
      </div>
    );
  }

  // For channel_created, no config needed - just show a simple confirmation
  if (config.type === "slack_channel_created") {
    return (
      <p className="text-sm text-zinc-500">
        This trigger will fire when a new channel is created. No additional
        configuration needed.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <TriggerSelectToggle
        label="Channels"
        selectProps={{
          options: channelOptions || [],
          selectedValues: selectedValues,
          onSelectionChange: (selectedIds: string[]) => {
            onConfigChange({
              ...config,
              channel_ids: selectedIds.join(","),
            });
          },
          isLoading: isLoadingChannels,
          placeholder: "Select channels",
          renderValue: (items: { key: string; textValue: string }[]) => {
            const count = items.length;
            if (count === 0) return "Select channels";
            if (count === 1) return items[0]?.textValue || "1 channel";
            return `${count} channels selected`;
          },
          description: "Leave empty to trigger on all channels",
        }}
        tagInputProps={{
          values: selectedValues,
          onChange: (selectedIds: string[]) => {
            onConfigChange({
              ...config,
              channel_ids: selectedIds.join(","),
            });
          },
          placeholder: "Add another...",
          emptyPlaceholder: "Enter channel IDs",
        }}
        allowManualInput={true}
      />

      <div className="space-y-2">
        <p className="text-sm font-medium text-foreground-600">
          Exclude Message Types
        </p>
        <div className="flex flex-col gap-2">
          <Checkbox
            isSelected={config.exclude_bot_messages || false}
            onValueChange={(val) =>
              onConfigChange({ ...config, exclude_bot_messages: val })
            }
          >
            Exclude bot messages
          </Checkbox>
          <Checkbox
            isSelected={config.exclude_direct_messages || false}
            onValueChange={(val) =>
              onConfigChange({ ...config, exclude_direct_messages: val })
            }
          >
            Exclude direct messages (1:1)
          </Checkbox>
          <Checkbox
            isSelected={config.exclude_group_messages || false}
            onValueChange={(val) =>
              onConfigChange({ ...config, exclude_group_messages: val })
            }
          >
            Exclude private groups
          </Checkbox>
          <Checkbox
            isSelected={config.exclude_mpim_messages || false}
            onValueChange={(val) =>
              onConfigChange({ ...config, exclude_mpim_messages: val })
            }
          >
            Exclude group DMs
          </Checkbox>
          <Checkbox
            isSelected={config.exclude_thread_replies || false}
            onValueChange={(val) =>
              onConfigChange({ ...config, exclude_thread_replies: val })
            }
          >
            Exclude thread replies
          </Checkbox>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// HANDLER DEFINITION
// =============================================================================

export const slackTriggerHandler: RegisteredHandler = {
  triggerSlugs: ["slack_new_message", "slack_channel_created"],

  createDefaultConfig: (slug: string): TriggerConfig => ({
    type: slug,
    enabled: true,
    ...(slug === "slack_new_message" && {
      channel_ids: "",
      exclude_bot_messages: false,
      exclude_direct_messages: false,
      exclude_group_messages: false,
      exclude_mpim_messages: false,
      exclude_thread_replies: false,
    }),
  }),

  SettingsComponent: SlackSettings,

  getDisplayInfo: (config) => ({
    label:
      config.type === "slack_channel_created"
        ? "on channel created"
        : "on new message",
    integrationId: "slack",
  }),
};
