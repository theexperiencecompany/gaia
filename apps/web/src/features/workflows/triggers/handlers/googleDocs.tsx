/**
 * Google Docs Trigger Handler
 *
 * Handles UI configuration for Google Docs triggers.
 */

"use client";

import type { RegisteredHandler } from "../registry";
import type { TriggerConfig } from "../types";

export const googleDocsTriggerHandler: RegisteredHandler = {
  triggerSlugs: ["google_docs_new_document"],

  createDefaultConfig: (slug: string): TriggerConfig => ({
    type: "app",
    enabled: true,
    trigger_name: slug,
    trigger_data: {
      trigger_name: slug,
    },
  }),

  // No custom settings component needed - simple trigger
  SettingsComponent: undefined,

  getDisplayInfo: () => ({
    label: "on new document",
    integrationId: "google_docs",
  }),
};
