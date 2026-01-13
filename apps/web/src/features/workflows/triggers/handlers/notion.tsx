/**
 * Notion Trigger Handler
 *
 * Handles UI configuration for Notion triggers.
 */

"use client";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

import {
  type OptionItem,
  TriggerConnectionPrompt,
  TriggerSelectToggle,
} from "../components";
import { useTriggerOptions } from "../hooks/useTriggerOptions";
import type { RegisteredHandler, TriggerSettingsProps } from "../registry";
import type { TriggerConfig } from "../types";

// =============================================================================
// TYPE DEFINITIONS
// =============================================================================

interface NotionTriggerData {
  trigger_name: string;
  database_ids?: string[];
  page_ids?: string[];
}

interface NotionConfig extends TriggerConfig {
  trigger_name?: string;
  trigger_data?: NotionTriggerData;
}

// =============================================================================
// NOTION SETTINGS COMPONENT
// =============================================================================

function NotionSettings({
  triggerConfig,
  onConfigChange,
}: TriggerSettingsProps) {
  const { integrations, connectIntegration } = useIntegrations();
  const config = triggerConfig as NotionConfig;
  const triggerData = config.trigger_data;
  const integrationId = "notion";

  const isConnected =
    integrations.find((i) => i.id === integrationId)?.status === "connected";

  const triggerSlug = config.trigger_name || "";

  const isDbTrigger = triggerSlug === "notion_new_page_in_db";
  const isPageTrigger = triggerSlug === "notion_page_updated";

  // Fetch databases for database trigger
  const {
    data: dbData,
    isLoading: isLoadingDb,
    isFetching: isFetchingDb,
  } = useTriggerOptions(
    integrationId,
    triggerSlug,
    "database_id",
    isConnected && isDbTrigger && !!triggerSlug,
  );

  // Fetch pages for page trigger
  const {
    data: pageData,
    isLoading: isLoadingPage,
    isFetching: isFetchingPage,
  } = useTriggerOptions(
    integrationId,
    triggerSlug,
    "page_id",
    isConnected && isPageTrigger && !!triggerSlug,
  );

  const showDbLoading = isLoadingDb || isFetchingDb;
  const showPageLoading = isLoadingPage || isFetchingPage;

  const dbOptions = (dbData || []) as OptionItem[];
  const pageOptions = (pageData || []) as OptionItem[];

  const updateTriggerData = (updates: Partial<NotionTriggerData>) => {
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
        integrationName="Notion"
        _integrationId={integrationId}
        onConnect={() => connectIntegration(integrationId)}
      />
    );
  }

  // Get current selected values for databases
  const selectedDbValues = triggerData?.database_ids || [];

  // Get current selected values for pages
  const selectedPageValues = triggerData?.page_ids || [];

  return (
    <div className="space-y-3">
      {isDbTrigger && (
        <TriggerSelectToggle
          label="Databases"
          selectProps={{
            options: dbOptions,
            selectedValues: selectedDbValues,
            onSelectionChange: (selectedIds: string[]) => {
              updateTriggerData({
                database_ids: selectedIds,
              });
            },
            isLoading: showDbLoading,
            placeholder: "Select databases",
            renderValue: (items: { key: string; textValue: string }[]) => {
              const count = items.length;
              if (count === 0) return "Select databases";
              if (count === 1) return items[0]?.textValue || "1 database";
              return `${count} databases selected`;
            },
          }}
          tagInputProps={{
            values: selectedDbValues,
            onChange: (selectedIds: string[]) => {
              updateTriggerData({
                database_ids: selectedIds,
              });
            },
            placeholder: "Add another...",
            emptyPlaceholder: "Enter database IDs",
          }}
        />
      )}

      {isPageTrigger && (
        <TriggerSelectToggle
          label="Pages"
          selectProps={{
            options: pageOptions,
            selectedValues: selectedPageValues,
            onSelectionChange: (selectedIds: string[]) => {
              updateTriggerData({
                page_ids: selectedIds,
              });
            },
            isLoading: showPageLoading,
            placeholder: "Select pages",
            renderValue: (items: { key: string; textValue: string }[]) => {
              const count = items.length;
              if (count === 0) return "Select pages";
              if (count === 1) return items[0]?.textValue || "1 page";
              return `${count} pages selected`;
            },
          }}
          tagInputProps={{
            values: selectedPageValues,
            onChange: (selectedIds: string[]) => {
              updateTriggerData({
                page_ids: selectedIds,
              });
            },
            placeholder: "Add another...",
            emptyPlaceholder: "Enter page IDs",
          }}
        />
      )}
    </div>
  );
}

// =============================================================================
// HANDLER DEFINITION
// =============================================================================

export const notionTriggerHandler: RegisteredHandler = {
  triggerSlugs: [
    "notion_new_page_in_db",
    "notion_page_updated",
    "notion_all_page_events",
  ],

  createDefaultConfig: (slug: string): TriggerConfig => {
    const triggerData: NotionTriggerData = {
      trigger_name: slug,
    };

    if (slug === "notion_new_page_in_db") {
      triggerData.database_ids = [];
    }
    if (slug === "notion_page_updated") {
      triggerData.page_ids = [];
    }

    return {
      type: "app",
      enabled: true,
      trigger_name: slug,
      trigger_data: triggerData,
    };
  },

  SettingsComponent: NotionSettings,

  getDisplayInfo: (config) => {
    const triggerName = (config as NotionConfig).trigger_name || config.type;
    let label = "on notion event";
    if (triggerName === "notion_new_page_in_db") label = "on new page in db";
    if (triggerName === "notion_page_updated") label = "on page updated";
    if (triggerName === "notion_all_page_events") label = "on any page event";

    return {
      label,
      integrationId: "notion",
    };
  },
};
