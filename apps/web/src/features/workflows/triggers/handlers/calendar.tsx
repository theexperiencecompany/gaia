/**
 * Google Calendar Trigger Handler
 *
 * Handles UI configuration for calendar triggers:
 * - calendar_event_created
 * - calendar_event_starting_soon
 */

"use client";

import { Input } from "@heroui/input";
import { Select, SelectItem } from "@heroui/select";
import { Switch } from "@heroui/switch";
import { useEffect, useState } from "react";

import { useCalendarsQuery } from "@/features/calendar/hooks/useCalendarsQuery";

import type { RegisteredHandler, TriggerSettingsProps } from "../registry";
import type { TriggerConfig } from "../types";

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

  // Type-safe access to calendar config fields
  const config = triggerConfig as TriggerConfig & {
    calendar_ids?: string[];
    minutes_before_start?: number;
    include_all_day?: boolean;
  };

  // Initialize selected calendars from trigger config
  useEffect(() => {
    if (calendars.length > 0 && config.calendar_ids) {
      const calIds = config.calendar_ids;
      if (calIds && Array.isArray(calIds)) {
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
  }, [config.calendar_ids, calendars]);

  const handleCalendarChange = (keys: Set<string>) => {
    const calendarIds = Array.from(keys).filter((k) => k !== "all");
    setSelectedCalendars(keys);

    onConfigChange({
      ...triggerConfig,
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
    onConfigChange({
      ...triggerConfig,
      minutes_before_start: value,
    });
  };

  const handleAllDayChange = (checked: boolean) => {
    onConfigChange({
      ...triggerConfig,
      include_all_day: checked,
    });
  };

  const calendarItems = [
    { id: "all", name: "Select All" },
    ...calendars.map((cal) => ({
      id: cal.id,
      name: `${cal.summary} ${cal.primary ? "(Primary)" : ""}`,
    })),
  ];

  const isEventStartingSoon =
    triggerConfig.type === "calendar_event_starting_soon";

  return (
    <div className="space-y-3">
      <Select
        aria-label="Select calendars"
        label="Calendars"
        placeholder="Select calendars to monitor"
        selectionMode="multiple"
        fullWidth
        className="w-full max-w-xl"
        isLoading={calendarsLoading}
        selectedKeys={selectedCalendars}
        onSelectionChange={(keys) => handleSelectionChange(keys as Set<string>)}
      >
        {calendarItems.map((item) => (
          <SelectItem key={item.id} textValue={item.name}>
            {item.name}
          </SelectItem>
        ))}
      </Select>

      {/* Event starting soon config */}
      {isEventStartingSoon && (
        <>
          <Input
            type="number"
            label="Minutes before event"
            placeholder="10"
            min={1}
            max={1440}
            className="w-full max-w-xl"
            classNames={{
              input:
                "[appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none",
            }}
            value={String(config.minutes_before_start || 10)}
            onChange={(e) => {
              const val = parseInt(e.target.value, 10);
              if (!Number.isNaN(val) && val >= 1 && val <= 1440) {
                handleMinutesChange(val);
              }
            }}
            description="How many minutes before event start (1-1440)"
          />
          <Switch
            isSelected={config.include_all_day ?? false}
            onValueChange={handleAllDayChange}
            size="sm"
          >
            <span className="text-sm">Include all-day events</span>
          </Switch>
        </>
      )}
    </div>
  );
}

// =============================================================================
// HANDLER DEFINITION
// =============================================================================

export const calendarTriggerHandler: RegisteredHandler = {
  triggerSlugs: ["calendar_event_created", "calendar_event_starting_soon"],

  createDefaultConfig: (slug: string): TriggerConfig => {
    const baseConfig = {
      enabled: true,
      trigger_name: slug,
      calendar_ids: ["primary"],
    };

    if (slug === "calendar_event_starting_soon") {
      return {
        ...baseConfig,
        type: "calendar_event_starting_soon",
        minutes_before_start: 10,
        include_all_day: false,
      } as TriggerConfig;
    }

    return {
      ...baseConfig,
      type: "calendar_event_created",
    } as TriggerConfig;
  },

  SettingsComponent: CalendarSettings,

  getDisplayInfo: (config) => ({
    label:
      config.type === "calendar_event_starting_soon"
        ? "event starting soon"
        : "on new calendar event",
    integrationId: "google_calendar",
  }),
};
