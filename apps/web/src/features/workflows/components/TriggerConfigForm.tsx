"use client";

import { useEffect, useMemo } from "react";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { TriggerAutocomplete } from "@/features/workflows/components/TriggerAutocomplete";
import {
  createDefaultTriggerConfig,
  getTriggerHandler,
  type TriggerConfig,
  useTriggerSchemas,
} from "@/features/workflows/triggers";

interface TriggerConfigFormProps {
  selectedTrigger: string;
  triggerConfig: TriggerConfig;
  onTriggerChange: (trigger: string) => void;
  onConfigChange: (config: TriggerConfig) => void;
}

export function TriggerConfigForm({
  selectedTrigger,
  triggerConfig,
  onTriggerChange,
  onConfigChange,
}: TriggerConfigFormProps) {
  const { data: triggerSchemas, isLoading: schemasLoading } =
    useTriggerSchemas();
  const { integrations, connectIntegration } = useIntegrations();

  // Get integration statuses
  const integrationStatusMap = useMemo(() => {
    const map = new Map<string, boolean>();
    integrations.forEach((integration) => {
      map.set(integration.id, integration.status === "connected");
    });
    return map;
  }, [integrations]);

  const handleTriggerSelect = (trigger: string | null) => {
    if (!trigger) {
      onTriggerChange("");
      return;
    }

    onTriggerChange(trigger);

    // Find schema here if needed for sync (though usually done in effect, but safer here)
    const schema = triggerSchemas?.find((s) => s.slug === trigger);

    const defaultConfig = createDefaultTriggerConfig(trigger);

    if (defaultConfig) {
      // Add integration_id and trigger_slug to config
      const finalConfig = {
        ...defaultConfig,
        integration_id: schema?.integration_id,
        trigger_slug: schema?.slug,
      };
      onConfigChange(finalConfig);
    } else {
      onConfigChange({
        type: "manual",
        enabled: true,
      });
    }
  };

  // Sync config when selectedTrigger changes (redundant if handleTriggerSelect does it,
  // but good for initial load or external changes)
  // However, handleTriggerSelect handles the user interaction.
  // This effect handles "if selectedTrigger is passed but config doesn't match".
  useEffect(() => {
    if (!selectedTrigger || schemasLoading) return;

    const handler = getTriggerHandler(selectedTrigger);
    if (!handler) return;

    const isValidTriggerConfig =
      triggerConfig.type !== "schedule" && triggerConfig.type !== "manual";

    if (!isValidTriggerConfig) {
      const defaultConfig = createDefaultTriggerConfig(selectedTrigger);
      if (defaultConfig) {
        onConfigChange(defaultConfig);
      }
    }
  }, [selectedTrigger, triggerConfig.type, schemasLoading, onConfigChange]);

  const handleConnectIntegration = async (integrationId: string) => {
    await connectIntegration(integrationId);
  };

  const handler = getTriggerHandler(selectedTrigger);
  const SettingsComponent = handler?.SettingsComponent;

  return (
    <div className="w-full space-y-4">
      {/* Searchable trigger autocomplete */}
      <TriggerAutocomplete
        selectedTrigger={selectedTrigger}
        onTriggerChange={handleTriggerSelect}
        triggerSchemas={triggerSchemas}
        isLoading={schemasLoading}
        integrationStatusMap={integrationStatusMap}
        onConnectIntegration={handleConnectIntegration}
      />

      {/* Render handler-specific settings */}
      {SettingsComponent && (
        <SettingsComponent
          triggerConfig={triggerConfig}
          onConfigChange={onConfigChange}
        />
      )}
    </div>
  );
}
