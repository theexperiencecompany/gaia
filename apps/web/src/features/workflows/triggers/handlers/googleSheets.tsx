/**
 * Google Sheets Trigger Handler
 *
 * Handles UI configuration for Google Sheets triggers.
 */

import type { RegisteredHandler } from "../registry";
import type { TriggerConfig } from "../types";
import type { GoogleSheetsConfig } from "./GoogleSheetsSettings";
import { GoogleSheetsSettings } from "./GoogleSheetsSettings";

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
      integrationId: "googlesheets",
    };
  },
};
