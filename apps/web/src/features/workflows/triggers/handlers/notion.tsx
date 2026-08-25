/**
 * Notion Trigger Handler
 *
 * Handles UI configuration for Notion triggers.
 */

import type { RegisteredHandler } from "../registry";
import type { TriggerConfig } from "../types";
import type { NotionConfig, NotionTriggerData } from "./NotionSettings";
import { NotionSettings } from "./NotionSettings";

// =============================================================================
// HANDLER DEFINITION
// =============================================================================

export const notionTriggerHandler: RegisteredHandler = {
  triggerSlugs: [
    "notion_new_page_in_db",
    "notion_page_updated",
    "notion_page_content_updated",
  ],

  createDefaultConfig: (slug: string): TriggerConfig => {
    const triggerData: NotionTriggerData = {
      trigger_name: slug,
    };

    if (slug === "notion_new_page_in_db") {
      triggerData.database_ids = [];
    }
    if (
      slug === "notion_page_updated" ||
      slug === "notion_page_content_updated"
    ) {
      triggerData.page_ids = [];
    }

    return {
      type: "integration",
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
    if (triggerName === "notion_page_content_updated")
      label = "on page content updated";

    return {
      label,
      integrationId: "notion",
    };
  },
};
