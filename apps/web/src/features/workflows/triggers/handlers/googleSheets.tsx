"use client";

import { Select, SelectItem, SelectSection } from "@heroui/select";
import { useEffect, useMemo, useState } from "react";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

import { TriggerConnectionPrompt, TriggerSelectToggle } from "../components";
import { useTriggerOptions } from "../hooks/useTriggerOptions";
import type { RegisteredHandler, TriggerSettingsProps } from "../registry";
import type { TriggerConfig } from "../types";

// =============================================================================
// TYPE DEFINITIONS
// =============================================================================

interface GoogleSheetsTriggerData {
  trigger_name: string;
  spreadsheet_ids?: string[];
  sheet_names?: string[];
}

interface GoogleSheetsConfig extends TriggerConfig {
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

  // ============ SIMPLIFIED STATE: Just 2 states ============
  const [spreadsheetIds, setSpreadsheetIds] = useState<string[]>(
    triggerData?.spreadsheet_ids || [],
  );
  // Store full composite keys (spreadsheet_id::sheet_name) to handle duplicate names
  const [sheetKeys, setSheetKeys] = useState<string[]>(
    triggerData?.sheet_names || [],
  );

  const triggerSlug = config.trigger_name || "";
  // Only new_row trigger needs sheet selection
  const isNewRowTrigger = triggerSlug === "google_sheets_new_row";

  // ============ DATA FETCHING ============
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
    spreadsheetIds.length > 0
      ? { parent_values: spreadsheetIds.join(",") }
      : undefined,
  );

  // ============ SINGLE SYNC EFFECT ============
  useEffect(() => {
    const currentTriggerData = triggerData || {
      trigger_name: config.trigger_name || "",
    };
    onConfigChange({
      ...config,
      trigger_data: {
        ...currentTriggerData,
        spreadsheet_ids: spreadsheetIds,
        // Only include sheet_names for new_row trigger
        ...(isNewRowTrigger && { sheet_names: sheetKeys }),
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spreadsheetIds, sheetKeys, isNewRowTrigger]);

  // ============ DERIVED DATA ============
  const spreadsheetOptions = (spreadsheetsData || []) as OptionItem[];
  const groupedSheetOptions = (sheetsData || []) as (
    | OptionItem
    | GroupedOption
  )[];

  const hasGroupedSheets =
    groupedSheetOptions.length > 0 &&
    "group" in groupedSheetOptions[0] &&
    groupedSheetOptions[0].group !== undefined;

  // Build a flat list of all available sheet names for matching
  const allSheetOptions = useMemo(() => {
    if (hasGroupedSheets) {
      return (groupedSheetOptions as GroupedOption[]).flatMap((g) => g.options);
    }
    return groupedSheetOptions as OptionItem[];
  }, [groupedSheetOptions, hasGroupedSheets]);

  // Convert stored sheet keys to Set<string> for the Select component
  const selectedSheetKeys = useMemo(() => {
    return new Set(sheetKeys);
  }, [sheetKeys]);

  // ============ HANDLERS ============
  const handleSpreadsheetChange = (selected: string[]) => {
    setSpreadsheetIds(selected);
    // Clear sheet selection when spreadsheets change
    setSheetKeys([]);
  };

  const handleSheetSelectionChange = (keys: "all" | Set<React.Key>) => {
    if (keys === "all") {
      // Select all: store all composite keys
      setSheetKeys(allSheetOptions.map((opt) => opt.value));
    } else {
      // Store the composite keys directly
      setSheetKeys(Array.from(keys).map((key) => String(key)));
    }
  };

  const renderSheetValue = (
    items: { key?: React.Key; textValue?: string }[],
  ) => {
    const count = items.length;
    if (count === 0) return "Select sheets";
    if (count === 1) return items[0]?.textValue || "1 sheet";
    return `${count} sheets selected`;
  };

  const renderSpreadsheetValue = (
    items: { key: string; textValue: string }[],
  ) => {
    const count = items.length;
    if (count === 0) return "Select spreadsheets";
    if (count === 1) return items[0]?.textValue || "1 spreadsheet";
    return `${count} spreadsheets selected`;
  };

  if (!isConnected) {
    // ============ RENDER ============
    return (
      <TriggerConnectionPrompt
        integrationName="Google Sheets"
        _integrationId={integrationId}
        onConnect={() => connectIntegration(integrationId)}
      />
    );
  }
  return (
    <div className="space-y-4">
      {/* Spreadsheet Selection */}
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

      {/* Sheet Name Selection - only for new_row trigger */}
      {isNewRowTrigger && (
        <Select
          label="Sheets"
          placeholder="Select sheet(s)"
          selectionMode="multiple"
          selectedKeys={selectedSheetKeys}
          onSelectionChange={handleSheetSelectionChange}
          className="w-full max-w-xl"
          description="Select specific sheets (leave empty for all sheets)"
          isDisabled={spreadsheetIds.length === 0}
          isLoading={isLoadingSheets}
          renderValue={renderSheetValue}
        >
          {hasGroupedSheets
            ? (groupedSheetOptions as GroupedOption[]).map((group) => {
                const spreadsheetName =
                  spreadsheetOptions.find((opt) => opt.value === group.group)
                    ?.label || group.group;
                return (
                  <SelectSection
                    key={group.group}
                    title={spreadsheetName}
                    classNames={{
                      heading: "text-xs font-semibold text-zinc-400 px-2 py-1",
                    }}
                  >
                    {group.options.map((option) => (
                      <SelectItem key={option.value} textValue={option.label}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectSection>
                );
              })
            : (groupedSheetOptions as OptionItem[]).map((option) => (
                <SelectItem key={option.value} textValue={option.label}>
                  {option.label}
                </SelectItem>
              ))}
        </Select>
      )}
    </div>
  );
}

// =============================================================================
// HANDLER REGISTRATION
// =============================================================================

export const googleSheetsTriggerHandler: RegisteredHandler = {
  triggerSlugs: ["google_sheets_new_row", "google_sheets_new_sheet"],

  createDefaultConfig: (slug: string): TriggerConfig => ({
    type: "integration",
    enabled: true,
    trigger_name: slug,
    trigger_data: {
      trigger_name: slug,
      spreadsheet_ids: [],
      sheet_names: [],
    },
  }),

  SettingsComponent: GoogleSheetsSettings,

  getDisplayInfo: (config) => {
    const triggerName =
      (config as GoogleSheetsConfig).trigger_name || config.type;
    return {
      label:
        triggerName === "google_sheets_new_row" ? "on new row" : "on new sheet",
      integrationId: "google_sheets",
    };
  },
};
