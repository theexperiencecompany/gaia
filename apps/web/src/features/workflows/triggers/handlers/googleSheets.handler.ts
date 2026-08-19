import type { RegisteredHandler } from "../registry";
import type { TriggerConfig } from "../types";
import { GoogleSheetsSettings } from "./googleSheets";

interface GoogleSheetsTriggerData {
  trigger_name: string;
  spreadsheet_ids?: string[];
  sheet_names?: string[];
}

interface GoogleSheetsConfig extends TriggerConfig {
  trigger_name?: string;
  trigger_data?: GoogleSheetsTriggerData;
}

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
      integrationId: "googlesheets",
    };
  },
};
