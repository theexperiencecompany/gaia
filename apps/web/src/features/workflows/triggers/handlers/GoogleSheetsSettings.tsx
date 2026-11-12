/**
 * Google Sheets Trigger Settings
 *
 * UI configuration for Google Sheets triggers: spreadsheet multi-select plus
 * (for the new-row trigger) sheet selection grouped by spreadsheet.
 */

"use client";

import { Description, Header, ListBox, Select } from "@heroui/react";
import { useMemo } from "react";
import { fieldVariants } from "@/components/shared/fieldVariants";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { TriggerConnectionPrompt } from "../components/TriggerConnectionPrompt";
import { TriggerSelectToggle } from "../components/TriggerSelectToggle";
import {
  TriggerSettingRow,
  TriggerSettingsCard,
} from "../components/TriggerSettingsCard";
import { useTriggerOptions } from "../hooks/useTriggerOptions";
import type { TriggerSettingsProps } from "../registry";
import type { TriggerConfigDraft } from "../types";

// =============================================================================
// TYPE DEFINITIONS
// =============================================================================

type GoogleSheetsTriggerData = {
  trigger_name: string;
  spreadsheet_ids?: string[];
  sheet_names?: string[];
};

export interface GoogleSheetsConfig extends TriggerConfigDraft {
  trigger_name?: string;
  trigger_data?: GoogleSheetsTriggerData;
}

interface OptionItem {
  value: string;
  label: string;
}

interface GroupedOption {
  group: string;
  options: OptionItem[];
}

// Stable empty fallback for sheetKeys so the Select value keeps a stable identity.
const NO_SHEET_KEYS: string[] = [];

// =============================================================================
// RENDER HELPERS (pure, module scope)
// =============================================================================

function renderSheetValue(items: { key?: React.Key; textValue?: string }[]) {
  const count = items.length;
  if (count === 0) return "Select sheets";
  if (count === 1) return items[0]?.textValue || "1 sheet";
  return `${count} sheets selected`;
}

function renderSpreadsheetValue(
  items: {
    key: string;
    textValue: string;
  }[],
) {
  const count = items.length;
  if (count === 0) return "Select spreadsheets";
  if (count === 1) return items[0]?.textValue || "1 spreadsheet";
  return `${count} spreadsheets selected`;
}

// =============================================================================
// GOOGLE SHEETS SETTINGS COMPONENT
// =============================================================================

export function GoogleSheetsSettings({
  triggerConfig,
  onConfigChange,
}: TriggerSettingsProps) {
  const { integrations, connectIntegration } = useIntegrations();
  const config = triggerConfig as GoogleSheetsConfig;
  const triggerData = config.trigger_data;
  const integrationId = "googlesheets";

  const isConnected =
    integrations.find((i) => i.id === integrationId)?.status === "connected";

  // The parent owns the config: selections are read straight from it and every
  // interaction writes back through onConfigChange, instead of mirroring into
  // local state that an effect pushes upward — one source of truth, no extra renders.
  const spreadsheetIds = triggerData?.spreadsheet_ids || [];
  // Composite keys (spreadsheet_id::sheet_name) to handle duplicate names
  const sheetKeys = triggerData?.sheet_names || NO_SHEET_KEYS;

  const triggerSlug = config.trigger_name || "";
  // Only new_row trigger needs sheet selection
  const isNewRowTrigger = triggerSlug === "google_sheets_new_row";

  // Fetch spreadsheets (no manual debounce - React Query handles caching)
  const { data: spreadsheetsData, isLoading: isLoadingSpreadsheets } =
    useTriggerOptions(
      integrationId,
      triggerSlug,
      "spreadsheet_ids",
      isConnected && !!triggerSlug,
    );

  // Fetch sheets for selected spreadsheets (only for new_row trigger)
  const { data: sheetsData, isLoading: isLoadingSheets } = useTriggerOptions(
    integrationId,
    triggerSlug,
    "sheet_names",
    isNewRowTrigger &&
      isConnected &&
      !!triggerSlug &&
      spreadsheetIds.length > 0,
    spreadsheetIds.length > 0 ? spreadsheetIds : undefined,
  );

  const spreadsheetOptions = (spreadsheetsData || []) as OptionItem[];
  // Memoized so downstream memos don't rebuild on every render (the fallback
  // `|| []` would otherwise create a fresh array identity each render).
  const groupedSheetOptions = useMemo(
    () => (sheetsData || []) as (OptionItem | GroupedOption)[],
    [sheetsData],
  );

  const hasGroupedSheets =
    groupedSheetOptions.length > 0 &&
    "group" in groupedSheetOptions[0] &&
    groupedSheetOptions[0].group !== undefined;

  // Build a flat list of all available sheet names for matching.
  const allSheetOptions = useMemo(() => {
    if (hasGroupedSheets) {
      return (groupedSheetOptions as GroupedOption[]).flatMap((g) => g.options);
    }
    return groupedSheetOptions as OptionItem[];
  }, [groupedSheetOptions, hasGroupedSheets]);

  // Persist a selection pair into the parent-owned config.
  const updateSelections = (
    nextSpreadsheetIds: string[],
    nextSheetKeys: string[],
  ) => {
    const currentTriggerData = triggerData || {
      trigger_name: config.trigger_name || "",
    };
    onConfigChange({
      ...config,
      trigger_data: {
        ...currentTriggerData,
        spreadsheet_ids: nextSpreadsheetIds,
        // Only include sheet_names for new_row trigger
        ...(isNewRowTrigger && { sheet_names: nextSheetKeys }),
      },
    });
  };

  const handleSpreadsheetChange = (selected: string[]) => {
    // Clear sheet selection when spreadsheets change
    updateSelections(selected, []);
  };

  const handleSheetSelectionChange = (keys: "all" | Set<React.Key>) => {
    if (keys === "all") {
      // Select all: store all composite keys
      updateSelections(
        spreadsheetIds,
        allSheetOptions.map((opt) => opt.value),
      );
    } else {
      // Store the composite keys directly
      updateSelections(
        spreadsheetIds,
        Array.from(keys).map((key) => String(key)),
      );
    }
  };

  if (!isConnected) {
    return (
      <TriggerConnectionPrompt
        integrationName="Google Sheets"
        integrationId={integrationId}
        iconUrl={integrations.find((i) => i.id === integrationId)?.iconUrl}
        onConnect={() => connectIntegration(integrationId)}
      />
    );
  }
  return (
    <TriggerSettingsCard>
      {/* Spreadsheet Selection */}
      <TriggerSettingRow label="Spreadsheets" wide>
        <TriggerSelectToggle
          label="Spreadsheets"
          selectProps={{
            options: spreadsheetOptions,
            selectedValues: spreadsheetIds,
            onSelectionChange: handleSpreadsheetChange,
            isLoading: isLoadingSpreadsheets,
            placeholder: "Select spreadsheet(s)",
            renderValue: renderSpreadsheetValue,
            description: (
              <span className="text-xs text-zinc-500">
                Select spreadsheets to monitor
              </span>
            ),
          }}
          tagInputProps={{
            values: spreadsheetIds,
            onChange: handleSpreadsheetChange,
            placeholder: "Add another...",
            emptyPlaceholder: "Enter spreadsheet IDs",
          }}
          allowManualInput={true}
        />
      </TriggerSettingRow>

      {/* Sheet Name Selection - only for new_row trigger */}
      {isNewRowTrigger && (
        <TriggerSettingRow label="Sheets" wide>
          <Select
            aria-label="Sheets"
            placeholder={isLoadingSheets ? "Loading..." : "Select sheet(s)"}
            selectionMode="multiple"
            value={sheetKeys}
            onChange={(keys) => handleSheetSelectionChange(new Set(keys))}
            className={fieldVariants({
              labelPlacement: "inside",
              className: "w-full",
            })}
            isDisabled={spreadsheetIds.length === 0}
          >
            <Select.Trigger>
              <GaiaSelectValue>
                {({ selectedItems }) =>
                  renderSheetValue(
                    (
                      selectedItems as ({
                        key?: React.Key;
                        textValue?: string;
                      } | null)[]
                    ).map((item) => ({
                      key: item?.key,
                      textValue: item?.textValue,
                    })),
                  )
                }
              </GaiaSelectValue>
              <Select.Indicator />
            </Select.Trigger>
            <Description>
              Select specific sheets (leave empty for all sheets)
            </Description>
            <Select.Popover className="min-w-fit">
              <ListBox>
                {hasGroupedSheets
                  ? (groupedSheetOptions as GroupedOption[]).map((group) => {
                      const spreadsheetName =
                        spreadsheetOptions.find(
                          (opt) => opt.value === group.group,
                        )?.label || group.group;
                      return (
                        <ListBox.Section key={group.group} id={group.group}>
                          <Header className="font-semibold">
                            {spreadsheetName}
                          </Header>
                          {group.options.map((option) => (
                            <GaiaListBoxItem
                              key={option.value}
                              id={option.value}
                              textValue={option.label}
                            >
                              {option.label}
                            </GaiaListBoxItem>
                          ))}
                        </ListBox.Section>
                      );
                    })
                  : (groupedSheetOptions as OptionItem[]).map((option) => (
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
        </TriggerSettingRow>
      )}
    </TriggerSettingsCard>
  );
}
