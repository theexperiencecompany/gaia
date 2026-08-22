/**
 * Google Calendar Trigger Handler
 *
 * Handles UI configuration for calendar triggers:
 * - calendar_event_created
 * - calendar_event_starting_soon
 */

import type { RegisteredHandler } from "../registry";
import type { TriggerConfig } from "../types";
import type { CalendarConfig, CalendarTriggerData } from "./CalendarSettings";
import { CalendarSettings } from "./CalendarSettings";

// =============================================================================
// HANDLER DEFINITION
// =============================================================================

export const calendarTriggerHandler: RegisteredHandler = {
  triggerSlugs: ["calendar_event_created", "calendar_event_starting_soon"],

  createDefaultConfig: (slug: string): TriggerConfig => {
    const baseTriggerData: CalendarTriggerData = {
      trigger_name: slug,
      calendar_ids: ["primary"],
    };

    if (slug === "calendar_event_starting_soon") {
      baseTriggerData.minutes_before_start = 10;
      baseTriggerData.include_all_day = false;
    }

    return {
      type: "integration",
      enabled: true,
      trigger_name: slug,
      trigger_data: baseTriggerData,
    } as TriggerConfig;
  },

  SettingsComponent: CalendarSettings,

  getDisplayInfo: (config) => {
    const triggerName = (config as CalendarConfig).trigger_name;
    return {
      label:
        triggerName === "calendar_event_starting_soon"
          ? "event starting soon"
          : "on new calendar event",
      integrationId: "googlecalendar",
    };
  },
};
