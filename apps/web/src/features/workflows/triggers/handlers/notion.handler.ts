import type { RegisteredHandler } from "../registry";
import type { TriggerConfig } from "../types";
import { NotionSettings } from "./notion";

interface NotionTriggerData {
  trigger_name: string;
  database_ids?: string[];
  page_ids?: string[];
}

interface NotionConfig extends TriggerConfig {
  trigger_name?: string;
  trigger_data?: NotionTriggerData;
}

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
    if (triggerName === "notion_all_page_events") label = "on any page event";
    return {
      label,
      integrationId: "notion",
    };
  },
};
