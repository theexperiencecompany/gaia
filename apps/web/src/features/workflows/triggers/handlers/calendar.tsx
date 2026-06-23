/**
 * Google Calendar Trigger Handler
 *
 * Handles UI configuration for calendar triggers:
 * - calendar_event_created
 * - calendar_event_starting_soon
 */

"use client";

import { Select, SelectItem } from "@heroui/select";
import { useEffect, useState } from "react";

import { useCalendarsQuery } from "@/features/calendar/hooks/useCalendarsQuery";

import { IntervalPicker } from "../components/IntervalPicker";
import {
  TriggerSettingRow,
  TriggerSettingsCard,
  TriggerToggleRow,
} from "../components/TriggerSettingsCard";
import type { RegisteredHandler, TriggerSettingsProps } from "../registry";
import type { TriggerConfig } from "../types";

// =============================================================================
// TYPE DEFINITIONS
// =============================================================================

interface CalendarTriggerData {
  trigger_name: string;
  calendar_ids: string[];
  minutes_before_start?: number;
  include_all_day?: boolean;
}

interface CalendarConfig extends TriggerConfig {
  trigger_name?: string;
  trigger_data?: CalendarTriggerData;
}

// =============================================================================
// CALENDAR SETTINGS COMPONENT
// =============================================================================

function CalendarSettings({
  triggerConfig,
  onConfigChange,
}: TriggerSettingsProps) {
  const { data: calendars = [], isLoading: calendarsLoading } =
    useCalendarsQuery();
  const [selectedCalendars, setSelectedCalendars] = useState<Set<string>>(
    new Set(["primary"]),
  );

  const config = triggerConfig as CalendarConfig;
  const triggerData = config.trigger_data;

  // Helper to update trigger_data only
  const updateTriggerData = (updates: Partial<CalendarTriggerData>) => {
    const currentTriggerData = triggerData || {
      trigger_name: config.trigger_name || "",
      calendar_ids: ["primary"],
    };
    onConfigChange({
      ...triggerConfig,
      trigger_data: {
        ...currentTriggerData,
        ...updates,
      },
    });
  };

  // Initialize selected calendars from trigger_data
  useEffect(() => {
    const calIds = triggerData?.calendar_ids;
    if (calendars.length > 0 && calIds) {
      if (Array.isArray(calIds)) {
        const mappedIds = new Set<string>();
        calIds.forEach((id) => {
          if (id === "primary") {
            const primaryCal = calendars.find((c) => c.primary);
            if (primaryCal) mappedIds.add(primaryCal.id);
          } else {
            mappedIds.add(id);
          }
        });

        // Check if all calendars are selected
        const allIds = calendars.map((c) => c.id);
        const allSelected = allIds.every((id) => mappedIds.has(id));
        if (allSelected && allIds.length > 0) {
          mappedIds.add("all");
        }

        setSelectedCalendars(mappedIds);
      }
    }
  }, [triggerData?.calendar_ids, calendars]);

  const handleCalendarChange = (keys: Set<string>) => {
    const calendarIds = Array.from(keys).filter((k) => k !== "all");
    setSelectedCalendars(keys);
    updateTriggerData({
      calendar_ids: calendarIds.length > 0 ? calendarIds : ["primary"],
    });
  };

  const handleSelectionChange = (keys: Set<string>) => {
    const newKeys = new Set(keys);

    if (newKeys.has("all") && !selectedCalendars.has("all")) {
      const allIds = calendars.map((c) => c.id);
      handleCalendarChange(new Set(["all", ...allIds]));
    } else if (!newKeys.has("all") && selectedCalendars.has("all")) {
      handleCalendarChange(new Set([]));
    } else if (newKeys.has("all") && newKeys.size < calendars.length + 1) {
      newKeys.delete("all");
      handleCalendarChange(newKeys);
    } else {
      const allIds = calendars.map((c) => c.id);
      const hasAllItems = allIds.every((id) => newKeys.has(id));
      if (hasAllItems) {
        newKeys.add("all");
      }
      handleCalendarChange(newKeys);
    }
  };

  const handleMinutesChange = (value: number) => {
    updateTriggerData({ minutes_before_start: value });
  };

  const handleAllDayChange = (checked: boolean) => {
    updateTriggerData({ include_all_day: checked });
  };

  const calendarItems = [
    { id: "all", name: "Select All" },
    ...calendars.map((cal) => ({
      id: cal.id,
      name: `${cal.summary} ${cal.primary ? "(Primary)" : ""}`,
    })),
  ];

  const isEventStartingSoon =
    config.trigger_name === "calendar_event_starting_soon";

  return (
    <TriggerSettingsCard>
      <TriggerSettingRow
        label="Calendars"
        hint="Leave empty to watch all calendars"
      >
        <Select
          aria-label="Select calendars"
          placeholder="Select calendars to monitor"
          selectionMode="multiple"
          className="w-full"
          isLoading={calendarsLoading}
          selectedKeys={selectedCalendars}
          onSelectionChange={(keys) =>
            handleSelectionChange(keys as Set<string>)
          }
        >
          {calendarItems.map((item) => (
            <SelectItem key={item.id} textValue={item.name}>
              {item.name}
            </SelectItem>
          ))}
        </Select>
      </TriggerSettingRow>

      {isEventStartingSoon && (
        <>
          <TriggerSettingRow label="Remind me before">
            <IntervalPicker
              value={triggerData?.minutes_before_start ?? 10}
              onChange={handleMinutesChange}
            />
          </TriggerSettingRow>
          <TriggerToggleRow
            label="Include all-day events"
            hint="Trigger for events without a set time"
            isSelected={triggerData?.include_all_day ?? false}
            onValueChange={handleAllDayChange}
          />
        </>
      )}
    </TriggerSettingsCard>
  );
}

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
