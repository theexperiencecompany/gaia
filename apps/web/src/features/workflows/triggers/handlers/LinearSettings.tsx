/**
 * Linear Trigger Settings
 *
 * UI configuration for Linear triggers: team selection with manual-ID fallback.
 */

"use client";

import { Input, ListBox, Select } from "@heroui/react";
import { useState } from "react";
import { fieldVariants } from "@/components/shared/fieldVariants";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { TriggerConnectionPrompt } from "../components/TriggerConnectionPrompt";
import {
  TriggerSettingRow,
  TriggerSettingsCard,
} from "../components/TriggerSettingsCard";
import { useTriggerOptions } from "../hooks/useTriggerOptions";
import type { TriggerSettingsProps } from "../registry";
import type { TriggerConfigDraft } from "../types";

type LinearTriggerData = {
  trigger_name: string;
  team_id?: string;
};

export interface LinearConfig extends TriggerConfigDraft {
  trigger_name?: string;
  trigger_data?: LinearTriggerData;
}

interface OptionItem {
  value: string;
  label: string;
}

export function LinearSettings({
  triggerConfig,
  onConfigChange,
}: TriggerSettingsProps) {
  const { integrations, connectIntegration } = useIntegrations();
  const config = triggerConfig as LinearConfig;
  const triggerData = config.trigger_data;
  const integrationId = "linear";

  const isConnected =
    integrations.find((i) => i.id === integrationId)?.status === "connected";

  const [useManualInput, setUseManualInput] = useState(false);
  const triggerSlug = config.trigger_name || "";

  // Fetch teams
  const { data: teamsData, isLoading } = useTriggerOptions(
    integrationId,
    triggerSlug,
    "team_id",
    isConnected && !!triggerSlug,
  );

  const teamOptions = (teamsData || []) as OptionItem[];

  const updateTriggerData = (updates: Partial<LinearTriggerData>) => {
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
        integrationName="Linear"
        integrationId={integrationId}
        iconUrl={integrations.find((i) => i.id === integrationId)?.iconUrl}
        onConnect={() => connectIntegration(integrationId)}
      />
    );
  }

  return (
    <TriggerSettingsCard>
      <TriggerSettingRow label="Team" wide>
        {isLoading ? (
          <Select
            aria-label="Team"
            className={fieldVariants({
              labelPlacement: "inside",
              className: "w-full",
            })}
            isDisabled
            selectedKey={null}
          >
            <Select.Trigger>
              <GaiaSelectValue>Loading teams...</GaiaSelectValue>
              <Select.Indicator />
            </Select.Trigger>
            <Select.Popover>
              <ListBox>
                <GaiaListBoxItem
                  key="loading"
                  id="loading"
                  textValue="Loading..."
                >
                  Loading...
                </GaiaListBoxItem>
              </ListBox>
            </Select.Popover>
          </Select>
        ) : teamOptions.length > 0 && !useManualInput ? (
          <div className="flex w-full flex-col gap-1.5">
            <Select
              aria-label="Team"
              selectedKey={triggerData?.team_id ?? null}
              onSelectionChange={(key) => {
                if (key != null) {
                  updateTriggerData({ team_id: String(key) });
                }
              }}
              className={fieldVariants({
                labelPlacement: "inside",
                className: "w-full",
              })}
            >
              <Select.Trigger>
                <GaiaSelectValue>
                  {triggerData?.team_id
                    ? (teamOptions.find((o) => o.value === triggerData.team_id)
                        ?.label ?? triggerData.team_id)
                    : "Select a team"}
                </GaiaSelectValue>
                <Select.Indicator />
              </Select.Trigger>
              <Select.Popover>
                <ListBox>
                  {teamOptions.map((option) => (
                    <GaiaListBoxItem
                      key={option.value}
                      id={option.value}
                      textValue={option.label}
                    >
                      {option.label}
                    </GaiaListBoxItem>
                  ))}
                </ListBox>
              </Select.Popover>
            </Select>
            <button
              type="button"
              onClick={() => setUseManualInput(true)}
              className="text-xs text-primary hover:underline"
            >
              Or enter manually
            </button>
          </div>
        ) : (
          <div className="flex w-full flex-col gap-1.5">
            <Input
              aria-label="Team ID"
              placeholder="Available in Linear URL"
              value={triggerData?.team_id || ""}
              onChange={(e) => updateTriggerData({ team_id: e.target.value })}
              className="w-full"
            />
            {teamOptions.length > 0 ? (
              <button
                type="button"
                onClick={() => setUseManualInput(false)}
                className="text-xs text-primary hover:underline"
              >
                Or select from list
              </button>
            ) : null}
          </div>
        )}
      </TriggerSettingRow>
    </TriggerSettingsCard>
  );
}
