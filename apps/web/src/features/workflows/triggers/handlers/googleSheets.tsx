"use client";

import { Select, SelectItem, SelectSection } from "@heroui/select";
import { useEffect, useState } from "react";

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
  spreadsheet_ids?: string;
  sheet_names?: string;
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

  const [spreadsheetIds, setSpreadsheetIds] = useState<Set<string>>(
    new Set(triggerData?.spreadsheet_ids?.split(",").filter(Boolean) || []),
  );
  // Store just sheet names initially - will be converted to full keys when sheets load
  const [sheetKeys, setSheetKeys] = useState<Set<string>>(new Set());
  const [pendingSheetNames, setPendingSheetNames] = useState<string[]>(
    triggerData?.sheet_names?.split(",").filter(Boolean) || [],
  );
  const [searchQuery, _setSearchQuery] = useState("");
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState("");
  const [debouncedSpreadsheetIds, setDebouncedSpreadsheetIds] = useState<
    string[]
  >(Array.from(spreadsheetIds));

  const triggerSlug = config.trigger_name || "";

  // Debounce search query
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearchQuery(searchQuery);
    }, 300);

    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Debounce spreadsheet IDs to reduce API calls
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSpreadsheetIds(Array.from(spreadsheetIds));
    }, 500);

    return () => clearTimeout(timer);
  }, [spreadsheetIds]);

  // Fetch spreadsheets with search
  const { data: spreadsheetsData, isLoading: isLoadingSpreadsheets } =
    useTriggerOptions(
      integrationId,
      triggerSlug,
      "spreadsheet_ids",
      isConnected && !!triggerSlug,
      debouncedSearchQuery ? { search: debouncedSearchQuery } : undefined,
    );

  // Fetch sheet names (dependent on spreadsheets) - use debounced IDs
  const { data: sheetsData, isLoading: isLoadingSheets } = useTriggerOptions(
    integrationId,
    triggerSlug,
    "sheet_names",
    isConnected && !!triggerSlug && debouncedSpreadsheetIds.length > 0,
    debouncedSpreadsheetIds.length > 0
      ? { parent_values: debouncedSpreadsheetIds.join(",") }
      : undefined,
  );

  const updateTriggerData = (updates: Partial<GoogleSheetsTriggerData>) => {
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

  useEffect(() => {
    // Extract just the sheet names from unique keys for backend
    const sheetNames = Array.from(sheetKeys).map((key) => {
      const parts = key.split("::");
      return parts.length > 1 ? parts[1] : key;
    });

    updateTriggerData({
      spreadsheet_ids: Array.from(spreadsheetIds).join(","),
      sheet_names: sheetNames.join(","),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spreadsheetIds, sheetKeys]);

  const spreadsheetOptions = (spreadsheetsData || []) as OptionItem[];
  const groupedSheetOptions = (sheetsData || []) as (
    | OptionItem
    | GroupedOption
  )[];

  const hasGroupedSheets =
    groupedSheetOptions.length > 0 &&
    "group" in groupedSheetOptions[0] &&
    groupedSheetOptions[0].group !== undefined;

  // Reconstruct full sheet keys from pending sheet names when sheets data loads
  // This handles the update view case where we only have sheet names stored
  useEffect(() => {
    if (pendingSheetNames.length === 0 || groupedSheetOptions.length === 0) {
      return;
    }

    const reconstructedKeys = new Set<string>();

    // Build a map of sheet name -> full keys for quick lookup
    const sheetNameToKeys = new Map<string, string[]>();

    if (hasGroupedSheets) {
      for (const group of groupedSheetOptions as GroupedOption[]) {
        for (const option of group.options) {
          const parts = option.value.split("::");
          const sheetName = parts.length > 1 ? parts[1] : option.value;
          const existing = sheetNameToKeys.get(sheetName) || [];
          existing.push(option.value);
          sheetNameToKeys.set(sheetName, existing);
        }
      }
    } else {
      for (const option of groupedSheetOptions as OptionItem[]) {
        const parts = option.value.split("::");
        const sheetName = parts.length > 1 ? parts[1] : option.value;
        const existing = sheetNameToKeys.get(sheetName) || [];
        existing.push(option.value);
        sheetNameToKeys.set(sheetName, existing);
      }
    }

    // Match pending sheet names to full keys
    for (const sheetName of pendingSheetNames) {
      const matchingKeys = sheetNameToKeys.get(sheetName);
      if (matchingKeys) {
        for (const key of matchingKeys) {
          reconstructedKeys.add(key);
        }
      }
    }

    if (reconstructedKeys.size > 0) {
      setSheetKeys(reconstructedKeys);
      setPendingSheetNames([]); // Clear pending after reconstruction
    }
  }, [groupedSheetOptions, pendingSheetNames, hasGroupedSheets]);

  if (!isConnected) {
    return (
      <TriggerConnectionPrompt
        integrationName="Google Sheets"
        _integrationId={integrationId}
        onConnect={() => connectIntegration(integrationId)}
      />
    );
  }

  const handleSheetSelectionChange = (keys: "all" | Set<React.Key>) => {
    // Store the full unique keys directly (spreadsheet_id::sheet_name)
    const keysArray =
      keys === "all" ? [] : Array.from(keys).map((key) => String(key));
    setSheetKeys(new Set(keysArray));
  };

  const renderValue = (items: { key: string; textValue: string }[]) => {
    // Check if "all" is selected
    if (sheetKeys.has("all")) return "All Sheets";

    const count = items.filter((item) => item.key !== "all").length;
    if (count === 0) return "Select sheets";
    if (count === 1) return items[0]?.textValue || "1 sheet";
    return `${count} sheets selected`;
  };

  return (
    <div className="space-y-4">
      {/* Spreadsheet Selection with Search */}
      <TriggerSelectToggle
        label="Spreadsheets"
        selectProps={{
          options: spreadsheetOptions,
          selectedValues: Array.from(spreadsheetIds),
          onSelectionChange: (selectedIds: string[]) => {
            const newSelection = new Set(selectedIds);
            setSpreadsheetIds(newSelection);
            // Clear sheet selection when spreadsheets change
            setSheetKeys(new Set());
          },
          isLoading: isLoadingSpreadsheets,
          placeholder: "Select spreadsheet(s)",
          renderValue: renderValue,
          description: (
            <span className="text-xs text-zinc-500">
              Select spreadsheets to monitor
            </span>
          ),
        }}
        tagInputProps={{
          values: Array.from(spreadsheetIds),
          onChange: (selectedIds: string[]) => {
            setSpreadsheetIds(new Set(selectedIds));
            setSheetKeys(new Set());
          },
          placeholder: "Add another...",
          emptyPlaceholder: "Enter spreadsheet IDs",
        }}
        allowManualInput={true}
      />

      {/* Sheet Name Selection */}
      <Select
        label="Sheets"
        placeholder="Select sheet(s)"
        selectionMode="multiple"
        selectedKeys={sheetKeys}
        onSelectionChange={handleSheetSelectionChange}
        className="w-full max-w-xl"
        description="Select specific sheets (leave empty for all sheets)"
        isDisabled={spreadsheetIds.size === 0}
        isLoading={isLoadingSheets}
        renderValue={
          renderValue as (
            items: { key?: React.Key; textValue?: string }[],
          ) => React.ReactNode
        }
      >
        {hasGroupedSheets
          ? (groupedSheetOptions as GroupedOption[]).map((group) => (
              <SelectSection
                key={group.group}
                title={group.group}
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
            ))
          : (groupedSheetOptions as OptionItem[]).map((option) => (
              <SelectItem key={option.value} textValue={option.label}>
                {option.label}
              </SelectItem>
            ))}
      </Select>
    </div>
  );
}

// Handler Registration

export const googleSheetsTriggerHandler: RegisteredHandler = {
  triggerSlugs: ["google_sheets_new_row", "google_sheets_new_sheet"],

  createDefaultConfig: (slug: string): TriggerConfig => ({
    type: "integration",
    enabled: true,
    trigger_name: slug,
    trigger_data: {
      trigger_name: slug,
      spreadsheet_ids: "",
      sheet_names: "",
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
