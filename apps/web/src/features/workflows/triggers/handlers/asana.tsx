/**
 * Asana Trigger Handler
 *
 * Handles UI configuration for Asana triggers.
 */

"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
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
      <div className="flex flex-col items-center justify-center p-4 space-y-3 bg-zinc-900/50 rounded-lg border border-zinc-800">
        <p className="text-sm text-zinc-400">
          Connect Asana to configure this trigger
        </p>
        <Button
          color="primary"
          variant="flat"
          onPress={() => connectIntegration(integrationId)}
        >
          Connect Asana
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <Input
        label="Project ID (optional)"
        placeholder="Enter project ID to filter"
        value={triggerData?.project_id || ""}
        onValueChange={(val) => updateTriggerData({ project_id: val })}
        className="w-full max-w-xl"
        description="Leave empty to trigger on all projects"
      />
      <Input
        label="Workspace ID (optional)"
        placeholder="Enter workspace ID to filter"
        value={triggerData?.workspace_id || ""}
        onValueChange={(val) => updateTriggerData({ workspace_id: val })}
        className="w-full max-w-xl"
        description="Leave empty to trigger on all workspaces"
      />
    </div>
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
