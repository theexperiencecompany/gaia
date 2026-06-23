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
  project_id?: string;
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
      <TriggerSettingRow label="Project ID" hint="Leave empty for all projects">
        <Input
          aria-label="Project ID"
          placeholder="Enter project ID"
          value={triggerData?.project_id || ""}
          onValueChange={(val) => updateTriggerData({ project_id: val })}
          className="w-full"
        />
      </TriggerSettingRow>
      <TriggerSettingRow
        label="Workspace ID"
        hint="Leave empty for all workspaces"
      >
        <Input
          aria-label="Workspace ID"
          placeholder="Enter workspace ID"
          value={triggerData?.workspace_id || ""}
          onValueChange={(val) => updateTriggerData({ workspace_id: val })}
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
      project_id: "",
      workspace_id: "",
    },
  }),

  SettingsComponent: AsanaSettings,

  getDisplayInfo: () => ({
    label: "on new task",
    integrationId: "asana",
  }),
};
