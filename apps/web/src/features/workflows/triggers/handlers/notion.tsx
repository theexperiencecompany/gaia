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
// NOTION SETTINGS COMPONENT
// =============================================================================

interface NotionConfig extends TriggerConfig {
  database_id?: string; // Backward compatibility
  page_id?: string; // Backward compatibility
  database_ids?: string[]; // Multi-select support
  page_ids?: string[]; // Multi-select support
  trigger_slug?: string;
}

function NotionSettings({
  triggerConfig,
  onConfigChange,
}: TriggerSettingsProps) {
  const { integrations, connectIntegration } = useIntegrations();
  const config = triggerConfig as NotionConfig;
  const integrationId = "notion";

  const isConnected =
    integrations.find((i) => i.id === integrationId)?.status === "connected";

  const triggerSlug = (config.trigger_slug || config.type) ?? "";

  const isDbTrigger = config.type === "notion_new_page_in_db";
  const isPageTrigger = config.type === "notion_page_updated";

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

  // Show loading if either loading or fetching
  const showDbLoading = isLoadingDb || isFetchingDb;
  const showPageLoading = isLoadingPage || isFetchingPage;

  const dbOptions = (dbData || []) as OptionItem[];
  const pageOptions = (pageData || []) as OptionItem[];

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
  const selectedDbValues =
    config.database_ids && config.database_ids.length > 0
      ? config.database_ids
      : config.database_id
        ? [config.database_id]
        : [];

  // Get current selected values for pages
  const selectedPageValues =
    config.page_ids && config.page_ids.length > 0
      ? config.page_ids
      : config.page_id
        ? [config.page_id]
        : [];

  return (
    <div className="space-y-3">
      {isDbTrigger && (
        <TriggerSelectToggle
          label="Databases"
          selectProps={{
            options: dbOptions,
            selectedValues: selectedDbValues,
            onSelectionChange: (selectedIds: string[]) => {
              onConfigChange({
                ...config,
                database_ids: selectedIds,
                database_id: selectedIds[0] || "", // Backward compatibility
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
              onConfigChange({
                ...config,
                database_ids: selectedIds,
                database_id: selectedIds[0] || "",
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
              onConfigChange({
                ...config,
                page_ids: selectedIds,
                page_id: selectedIds[0] || "", // Backward compatibility
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
              onConfigChange({
                ...config,
                page_ids: selectedIds,
                page_id: selectedIds[0] || "",
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
    const config: NotionConfig = {
      type: slug,
      enabled: true,
    };
    if (slug === "notion_new_page_in_db") config.database_ids = [];
    if (slug === "notion_page_updated") config.page_ids = [];
    return config;
  },

  SettingsComponent: NotionSettings,

  getDisplayInfo: (config) => {
    let label = "on notion event";
    if (config.type === "notion_new_page_in_db") label = "on new page in db";
    if (config.type === "notion_page_updated") label = "on page updated";
    if (config.type === "notion_all_page_events") label = "on any page event";

    return {
      label,
      integrationId: "notion",
    };
  },
};
