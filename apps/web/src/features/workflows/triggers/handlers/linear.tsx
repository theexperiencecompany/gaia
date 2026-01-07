/**
 * Linear Trigger Handler
 *
 * Handles UI configuration for Linear triggers.
 */

"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Select, SelectItem } from "@heroui/select";
import { useState } from "react";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { useTriggerOptions } from "../hooks/useTriggerOptions";
import type { RegisteredHandler, TriggerSettingsProps } from "../registry";
import type { TriggerConfig } from "../types";

// =============================================================================
// LINEAR SETTINGS COMPONENT
// =============================================================================

interface LinearConfig extends TriggerConfig {
  team_id?: string;
  trigger_slug?: string;
}

interface OptionItem {
  value: string;
  label: string;
}

function LinearSettings({
  triggerConfig,
  onConfigChange,
}: TriggerSettingsProps) {
  const { integrations, connectIntegration } = useIntegrations();
  const config = triggerConfig as LinearConfig;
  const integrationId = "linear";

  const isConnected =
    integrations.find((i) => i.id === integrationId)?.status === "connected";

  const [useManualInput, setUseManualInput] = useState(false);
  const triggerSlug = (config.trigger_slug || config.type) ?? "";

  // Fetch teams (assuming endpoint supports 'team' field)
  const { data: teamsData, isLoading } = useTriggerOptions(
    integrationId,
    triggerSlug,
    "team_id",
    isConnected && !!triggerSlug,
  );

  const teamOptions = (teamsData || []) as OptionItem[];

  if (!isConnected) {
    return (
      <div className="flex flex-col items-center justify-center p-4 space-y-3 bg-zinc-900/50 rounded-lg border border-zinc-800">
        <p className="text-sm text-zinc-400">
          Connect Linear to configure this trigger
        </p>
        <Button
          color="primary"
          variant="flat"
          onPress={() => connectIntegration(integrationId)}
        >
          Connect Linear
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {isLoading ? (
        <Select
          label="Team"
          placeholder="Loading teams..."
          className="w-full max-w-xl"
          isDisabled
          isLoading
          selectedKeys={[]}
        >
          <SelectItem key="loading" textValue="Loading...">
            Loading...
          </SelectItem>
        </Select>
      ) : teamOptions.length > 0 && !useManualInput ? (
        <Select
          label="Team"
          placeholder="Select a team"
          selectedKeys={config.team_id ? [config.team_id] : []}
          onSelectionChange={(keys) => {
            const key = Array.from(keys)[0];
            if (key) {
              onConfigChange({ ...config, team_id: String(key) });
            }
          }}
          isLoading={isLoading}
          description={
            <button
              type="button"
              onClick={() => setUseManualInput(true)}
              className="text-xs text-primary hover:underline"
            >
              Or enter manually
            </button>
          }
          className="w-full max-w-xl"
        >
          {teamOptions.map((option) => (
            <SelectItem key={option.value} textValue={option.label}>
              {option.label}
            </SelectItem>
          ))}
        </Select>
      ) : (
        <Input
          label="Team ID"
          placeholder="Available in Linear URL"
          value={config.team_id || ""}
          onValueChange={(val) => onConfigChange({ ...config, team_id: val })}
          className="w-full max-w-xl"
          description={
            teamOptions.length > 0 ? (
              <button
                type="button"
                onClick={() => setUseManualInput(false)}
                className="text-xs text-primary hover:underline"
              >
                Or select from list
              </button>
            ) : undefined
          }
        />
      )}
    </div>
  );
}

// =============================================================================
// HANDLER DEFINITION
// =============================================================================

export const linearTriggerHandler: RegisteredHandler = {
  triggerSlugs: ["linear_issue_created", "linear_comment_added"],

  createDefaultConfig: (slug: string): TriggerConfig => ({
    type: slug,
    enabled: true,
    team_id: "",
  }),

  SettingsComponent: LinearSettings,

  getDisplayInfo: (config) => ({
    label:
      config.type === "linear_issue_created"
        ? "on new issue"
        : "on new comment",
    integrationId: "linear",
  }),
};
