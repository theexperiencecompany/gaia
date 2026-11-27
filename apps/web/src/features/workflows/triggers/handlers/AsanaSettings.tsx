/**
 * Asana Trigger Settings
 *
 * UI configuration for Asana triggers.
 */

"use client";

import { Input } from "@heroui/react";
import type { AsanaTaskTriggerConfig } from "@shared/api/generated";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

import { TriggerConnectionPrompt } from "../components/TriggerConnectionPrompt";
import {
  TriggerSettingRow,
  TriggerSettingsCard,
} from "../components/TriggerSettingsCard";
import type { TriggerSettingsProps } from "../registry";
import type { TriggerConfigDraft } from "../types";

// The draft holds whichever slug the picker set, so trigger_name is any string.
type AsanaTriggerData = Omit<AsanaTaskTriggerConfig, "trigger_name"> & {
  trigger_name: string;
};

interface AsanaConfig extends TriggerConfigDraft {
  trigger_name?: string;
  trigger_data?: AsanaTriggerData;
}

export function AsanaSettings({
  triggerConfig,
  onConfigChange,
}: TriggerSettingsProps) {
  const { integrations, connectIntegration } = useIntegrations();
  const config = triggerConfig as AsanaConfig;
  const triggerData = config.trigger_data;
  const integrationId = "asana";

  const integration = integrations.find((i) => i.id === integrationId);
  const isConnected = integration?.status === "connected";

  const updateTriggerData = (updates: Partial<AsanaTriggerData>) => {
    const currentTriggerData = triggerData || {
      trigger_name: config.trigger_name || "",
    };
    onConfigChange({
      ...config,
      trigger_data: {
        ...currentTriggerData,
        ...updates,
      },
    });
  };

  if (!isConnected) {
    return integration ? (
      <TriggerConnectionPrompt
        integration={integration}
        onConnect={() => connectIntegration(integration.id)}
      />
    ) : null;
  }

  return (
    <TriggerSettingsCard>
      <TriggerSettingRow
        label="Project GID"
        hint="Required: Asana GID of the project to monitor"
      >
        <Input
          aria-label="Project GID"
          placeholder="Enter project GID (e.g. 1213430481840948)"
          value={triggerData?.project_gid || ""}
          onChange={(e) => updateTriggerData({ project_gid: e.target.value })}
          className="w-full"
        />
      </TriggerSettingRow>
    </TriggerSettingsCard>
  );
}
