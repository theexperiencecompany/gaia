/**
 * Asana Trigger Handler
 *
 * Handles UI configuration for Asana triggers.
 */

"use client";

import { Input } from "@heroui/input";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { TriggerConnectionPrompt } from "../components/TriggerConnectionPrompt";
import {
  TriggerSettingRow,
  TriggerSettingsCard,
} from "../components/TriggerSettingsCard";
import type { RegisteredHandler, TriggerSettingsProps } from "../registry";
import type { TriggerConfig } from "../types";

interface AsanaTriggerData {
  trigger_name: string;
  project_gid?: string;
  workspace_id?: string;
}

interface AsanaConfig extends TriggerConfig {
  trigger_name?: string;
  trigger_data?: AsanaTriggerData;
}

// =============================================================================
// ASANA SETTINGS COMPONENT
// =============================================================================

function AsanaSettings({
  triggerConfig,
  onConfigChange,
}: TriggerSettingsProps) {
  const { integrations, connectIntegration } = useIntegrations();
  const config = triggerConfig as AsanaConfig;
  const triggerData = config.trigger_data;
  const integrationId = "asana";

  const isConnected =
    integrations.find((i) => i.id === integrationId)?.status === "connected";

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
    return (
      <TriggerConnectionPrompt
        integrationName="Asana"
        integrationId={integrationId}
        iconUrl={integrations.find((i) => i.id === integrationId)?.iconUrl}
        onConnect={() => connectIntegration(integrationId)}
      />
    );
  }

  return (
    <TriggerSettingsCard>
      <TriggerSettingRow
        label="Project GID"
        hint="Required — Asana GID of the project to monitor"
      >
        <Input
          aria-label="Project GID"
          placeholder="Enter project GID (e.g. 1213430481840948)"
          value={triggerData?.project_gid || ""}
          onValueChange={(val) => updateTriggerData({ project_gid: val })}
          className="w-full"
        />
      </TriggerSettingRow>
    </TriggerSettingsCard>
  );
}

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
