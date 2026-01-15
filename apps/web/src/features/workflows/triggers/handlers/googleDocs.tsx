/**
 * Google Docs Trigger Handler
 *
 * Handles UI configuration for Google Docs triggers.
 */

"use client";

import type { RegisteredHandler } from "../registry";
import type { TriggerConfig } from "../types";

export const googleDocsTriggerHandler: RegisteredHandler = {
  triggerSlugs: [
    "google_docs_new_document",
    "google_docs_document_deleted",
    "google_docs_document_updated",
  ],

  createDefaultConfig: (slug: string): TriggerConfig => ({
    type: "integration",
    enabled: true,
    trigger_name: slug,
    trigger_data: {
      trigger_name: slug,
    },
  }),

  // No custom settings component needed - simple trigger
  SettingsComponent: undefined,

  getDisplayInfo: (config) => {
    const triggerName = config.trigger_name;
    let label = "on new document";
    if (triggerName === "google_docs_document_deleted")
      label = "on document deleted";
    if (triggerName === "google_docs_document_updated")
      label = "on document updated";

    return {
      label,
      integrationId: "google_docs",
    };
  },
};
