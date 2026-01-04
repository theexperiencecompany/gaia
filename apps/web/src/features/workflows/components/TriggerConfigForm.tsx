"use client";

import { Select, SelectItem } from "@heroui/select";
import { useEffect } from "react";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
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

  const selectedSchema = triggerSchemas?.find(
    (s) => s.slug === selectedTrigger,
  );

  // Sync trigger config when selectedTrigger exists but config type doesn't match
  // This handles the case when switching back to trigger tab with a previous selection
  useEffect(() => {
    if (!selectedTrigger || schemasLoading) return;

    // Check if the current trigger config type matches the selected trigger
    const handler = getTriggerHandler(selectedTrigger);
    if (!handler) return;

    // Check if current config is a valid trigger type (not schedule/manual)
    const isValidTriggerConfig =
      triggerConfig.type !== "schedule" && triggerConfig.type !== "manual";

    // If we have a selected trigger but the config doesn't match (e.g., was reset to schedule/manual)
    // recreate the config for the selected trigger
    if (!isValidTriggerConfig) {
      const defaultConfig = createDefaultTriggerConfig(selectedTrigger);
      if (defaultConfig) {
        onConfigChange(defaultConfig);
      }
    }
  }, [selectedTrigger, triggerConfig.type, schemasLoading, onConfigChange]);

  const handleTriggerSelect = (trigger: string) => {
    onTriggerChange(trigger);

    // Create default config using handler
    const defaultConfig = createDefaultTriggerConfig(trigger);
    if (defaultConfig) {
      onConfigChange(defaultConfig);
    } else {
      // Fallback to manual
      onConfigChange({
        type: "manual",
        enabled: true,
      });
    }
  };

  if (schemasLoading) {
    return <div className="animate-pulse h-12 bg-zinc-800 rounded-lg" />;
  }

  // Get the handler for the current trigger to render its settings component
  const handler = getTriggerHandler(selectedTrigger);
  const SettingsComponent = handler?.SettingsComponent;

  return (
    <div className="w-full space-y-4">
      {/* Trigger selector */}
      <Select
        aria-label="Choose a trigger"
        placeholder="Choose a trigger for your workflow"
        fullWidth
        className="w-full max-w-xl"
        selectedKeys={selectedTrigger ? [selectedTrigger] : []}
        onSelectionChange={(keys) => {
          const trigger = Array.from(keys)[0] as string;
          handleTriggerSelect(trigger);
        }}
        startContent={
          selectedSchema &&
          getToolCategoryIcon(selectedSchema.integration_id, {
            width: 20,
            height: 20,
            showBackground: false,
          })
        }
      >
        {(triggerSchemas ?? []).map((schema) => (
          <SelectItem
            key={schema.slug}
            textValue={schema.name}
            startContent={getToolCategoryIcon(schema.integration_id, {
              width: 20,
              height: 20,
              showBackground: false,
            })}
            description={schema.description}
          >
            {schema.name}
          </SelectItem>
        ))}
      </Select>

      {/* Trigger description */}
      {selectedSchema && (
        <p className="px-1 text-xs text-zinc-500">
          {selectedSchema.description}
        </p>
      )}

      {/* Render handler-specific settings if available - GENERIC, no type checks */}
      {SettingsComponent && (
        <SettingsComponent
          triggerConfig={triggerConfig}
          onConfigChange={onConfigChange}
        />
      )}
    </div>
  );
}
