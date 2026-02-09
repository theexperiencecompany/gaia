"use client";

import { useEffect, useMemo } from "react";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { TriggerAutocomplete } from "@/features/workflows/components/TriggerAutocomplete";
import {
  createDefaultTriggerConfig,
  findTriggerSchema,
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

  const integrationStatusMap = useMemo(() => {
    const map = new Map<string, boolean>();
    integrations.forEach((integration) => {
      map.set(integration.id, integration.status === "connected");
    });
    return map;
  }, [integrations]);

  const selectedSchema = findTriggerSchema(triggerSchemas, selectedTrigger);
  const normalizedSlug = selectedSchema?.slug ?? selectedTrigger;

  const handleTriggerSelect = (trigger: string | null) => {
    if (!trigger) {
      onTriggerChange("");
      return;
    }

    onTriggerChange(trigger);

    const schema = triggerSchemas?.find((s) => s.slug === trigger);
    const defaultConfig = createDefaultTriggerConfig(trigger);

    if (defaultConfig) {
      onConfigChange({
        ...defaultConfig,
        integration_id: schema?.integration_id,
        trigger_slug: schema?.slug,
      });
    } else {
      onConfigChange({
        type: "manual",
        enabled: true,
      });
    }
  };

  useEffect(() => {
    if (!normalizedSlug || schemasLoading) return;

    const handler = getTriggerHandler(normalizedSlug);
    if (!handler) return;

    const isValidTriggerConfig =
      triggerConfig.type !== "schedule" && triggerConfig.type !== "manual";

    if (!isValidTriggerConfig) {
      const defaultConfig = createDefaultTriggerConfig(normalizedSlug);
      if (defaultConfig) {
        onConfigChange(defaultConfig);
      }
    }
  }, [normalizedSlug, triggerConfig.type, schemasLoading, onConfigChange]);

  const handler = getTriggerHandler(normalizedSlug);
  const SettingsComponent = handler?.SettingsComponent;

  return (
    <div className="w-full space-y-4">
      <TriggerAutocomplete
        selectedTrigger={selectedTrigger}
        onTriggerChange={handleTriggerSelect}
        triggerSchemas={triggerSchemas}
        isLoading={schemasLoading}
        integrationStatusMap={integrationStatusMap}
        onConnectIntegration={connectIntegration}
      />

      {SettingsComponent && (
        <SettingsComponent
          triggerConfig={{
            ...triggerConfig,
            trigger_name:
              normalizedSlug ||
              (triggerConfig as { trigger_name?: string }).trigger_name,
          }}
          onConfigChange={onConfigChange}
        />
      )}
    </div>
  );
}
