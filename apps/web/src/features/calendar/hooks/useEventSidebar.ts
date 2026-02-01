import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { calendarApi } from "@/features/calendar/api/calendarApi";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import {
  useAddEvent,
  useRemoveEvent,
  useUpdateEvent,
} from "@/stores/calendarStore";
import type {
  GoogleCalendarEvent,
  RecurrenceData,
} from "@/types/features/calendarTypes";
import {
  dateTimeLocalToISO,
  isoToDateTimeLocal,
  toDateTimeLocalString,
} from "@/utils/date/dateTimeLocalUtils";

const getUserTimezone = (): string => {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
};

const buildRecurrencePayload = (
  type: string,
  customDays: string[],
): RecurrenceData | undefined => {
  if (type === "none") return undefined;

  if (type === "custom" && customDays.length > 0) {
    return {
      rrule: {
        frequency: "WEEKLY",
        by_day: customDays,
      },
    };
  }

  const recurrenceMap: Record<string, RecurrenceData> = {
    daily: { rrule: { frequency: "DAILY" } },
    weekdays: {
      rrule: { frequency: "WEEKLY", by_day: ["MO", "TU", "WE", "TH", "FR"] },
    },
    weekly: { rrule: { frequency: "WEEKLY" } },
    monthly: { rrule: { frequency: "MONTHLY" } },
    yearly: { rrule: { frequency: "YEARLY" } },
  };

  return recurrenceMap[type];
};

interface UseEventSidebarProps {
  onEventUpdate?: () => void;
}

export const useEventSidebar = ({
  onEventUpdate,
}: UseEventSidebarProps = {}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedEvent, setSelectedEvent] =
    useState<GoogleCalendarEvent | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  const [summary, setSummary] = useState("");
  const [description, setDescription] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [isAllDay, setIsAllDay] = useState(false);
  const [selectedCalendarId, setSelectedCalendarId] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [recurrenceType, setRecurrenceType] = useState<string>("none");
  const [customRecurrenceDays, setCustomRecurrenceDays] = useState<string[]>(
    [],
  );

  const updateEventInStore = useUpdateEvent();
  const removeEventFromStore = useRemoveEvent();
  const addEventToStore = useAddEvent();

  const summaryTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const descriptionTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const dateTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const resetForm = useCallback(() => {
    setSummary("");
    setDescription("");
    setStartDate("");
    setEndDate("");
    setIsAllDay(false);
    setSelectedCalendarId("");
    setSelectedEvent(null);
    setIsCreating(false);
    setRecurrenceType("none");
    setCustomRecurrenceDays([]);
  }, []);

  const openForEvent = useCallback((event: GoogleCalendarEvent) => {
    setSelectedEvent(event);
    setIsCreating(false);
    setSummary(event.summary || "");
    setDescription(event.description || "");

    const startDateTime = event.start?.dateTime || event.start?.date;
    const endDateTime = event.end?.dateTime || event.end?.date;

    // Convert ISO strings to datetime-local format preserving the local time
    if (startDateTime) {
      setStartDate(isoToDateTimeLocal(startDateTime));
    }
    if (endDateTime) {
      setEndDate(isoToDateTimeLocal(endDateTime));
    }

    setIsAllDay(!!event.start?.date);
    setIsOpen(true);
  }, []);

  const openForCreate = useCallback(
    (selectedDate?: Date) => {
      resetForm();
      setIsCreating(true);
      setIsOpen(true);

      let now: Date;

      if (selectedDate && selectedDate instanceof Date) {
        // Use the selected date but set a reasonable time
        now = new Date(selectedDate);

        // Validate the date is valid
        if (Number.isNaN(now.getTime())) {
          console.error("Invalid selectedDate received, using current date");
          now = new Date();
        }

        now.setHours(9); // Default to 9 AM
        now.setMinutes(0);
        now.setSeconds(0);
        now.setMilliseconds(0);
      } else {
        // If no date provided, use current time and round to nearest 15 minutes
        now = new Date();
        const currentMinutes = now.getMinutes();
        const roundedMinutes = Math.ceil(currentMinutes / 15) * 15;

        if (roundedMinutes === 60) {
          now.setHours(now.getHours() + 1);
          now.setMinutes(0);
        } else {
          now.setMinutes(roundedMinutes);
        }
        now.setSeconds(0);
        now.setMilliseconds(0);
      }

      // Validate that now is a valid date before using it
      if (Number.isNaN(now.getTime())) {
        console.error("Invalid date after processing, aborting");
        return;
      }

      const start = toDateTimeLocalString(now);
      const end = toDateTimeLocalString(
        new Date(now.getTime() + 60 * 60 * 1000),
      );

      setStartDate(start);
      setEndDate(end);
    },
    [resetForm],
  );

  const close = useCallback(() => {
    setIsOpen(false);
    setTimeout(resetForm, 300);
  }, [resetForm]);

  const updateEventField = useCallback(
    async (field: string, value: string | boolean) => {
      if (!selectedEvent || isCreating) return;

      setIsSaving(true);
      try {
        // Preserve original event timezone if available, otherwise use user's current timezone
        const originalTimezone =
          selectedEvent.start?.timeZone ||
          selectedEvent.end?.timeZone ||
          getUserTimezone();

        const updatePayload: Record<string, unknown> = {
          event_id: selectedEvent.id,
          calendar_id:
            selectedEvent.calendarId || selectedCalendarId || "primary",
        };

        if (field === "summary") {
          updatePayload.summary = value;
        } else if (field === "description") {
          updatePayload.description = value;
        } else if (field === "start" || field === "end") {
          // Convert datetime-local to ISO string with timezone info
          const isoString = dateTimeLocalToISO(value as string);
          updatePayload[field] = isoString;
          updatePayload.timezone = originalTimezone; // Preserve original timezone
        } else if (field === "isAllDay") {
          updatePayload.is_all_day = value;
          if (value) {
            // For all-day events, send just the date part safely
            updatePayload.start = startDate.includes("T")
              ? startDate.split("T")[0]
              : startDate;
            updatePayload.end = endDate.includes("T")
              ? endDate.split("T")[0]
              : endDate;
          } else {
            // For timed events, send ISO strings with timezone
            updatePayload.start = dateTimeLocalToISO(startDate);
            updatePayload.end = dateTimeLocalToISO(endDate);
            updatePayload.timezone = originalTimezone; // Preserve original timezone
          }
        }

        // Call the API
        const updatedEvent = await calendarApi.updateEventByAgent(
          updatePayload as Parameters<typeof calendarApi.updateEventByAgent>[0],
        );

        // Update the event in the store
        updateEventInStore(selectedEvent.id, updatedEvent);

        // Update local selected event state to reflect changes immediately
        setSelectedEvent(updatedEvent);

        // Sync local form state with updated event
        setSummary(updatedEvent.summary || "");
        setDescription(updatedEvent.description || "");

        const updatedStartDateTime =
          updatedEvent.start?.dateTime || updatedEvent.start?.date;
        const updatedEndDateTime =
          updatedEvent.end?.dateTime || updatedEvent.end?.date;

        if (updatedStartDateTime) {
          setStartDate(isoToDateTimeLocal(updatedStartDateTime));
        }
        if (updatedEndDateTime) {
          setEndDate(isoToDateTimeLocal(updatedEndDateTime));
        }
        setIsAllDay(!!updatedEvent.start?.date);

        onEventUpdate?.();
      } catch (error) {
        console.error("Event update error:", error);
        const errorMsg =
          error instanceof Error ? error.message : "Failed to update event";
        toast.error(errorMsg);
      } finally {
        setIsSaving(false);
      }
    },
    [
      selectedEvent,
      isCreating,
      selectedCalendarId,
      startDate,
      endDate,
      updateEventInStore,
      onEventUpdate,
    ],
  );

  const handleSummaryChange = useCallback(
    (value: string) => {
      setSummary(value);

      if (summaryTimeoutRef.current) {
        clearTimeout(summaryTimeoutRef.current);
      }

      if (!isCreating) {
        summaryTimeoutRef.current = setTimeout(() => {
          updateEventField("summary", value);
        }, 800);
      }
    },
    [isCreating, updateEventField],
  );

  const handleDescriptionChange = useCallback(
    (value: string) => {
      setDescription(value);

      if (descriptionTimeoutRef.current) {
        clearTimeout(descriptionTimeoutRef.current);
      }

      if (!isCreating) {
        descriptionTimeoutRef.current = setTimeout(() => {
          updateEventField("description", value);
        }, 1000);
      }
    },
    [isCreating, updateEventField],
  );

  const handleDateChange = useCallback(
    (field: "start" | "end", value: string) => {
      // Update local state first
      if (field === "start") {
        setStartDate(value);
      }
      if (field === "end") {
        setEndDate(value);
      }

      if (dateTimeoutRef.current) {
        clearTimeout(dateTimeoutRef.current);
      }

      if (!isCreating) {
        dateTimeoutRef.current = setTimeout(() => {
          // Validate only when actually saving
          const currentStart = field === "start" ? value : startDate;
          const currentEnd = field === "end" ? value : endDate;

          if (
            currentStart &&
            currentEnd &&
            new Date(currentStart) >= new Date(currentEnd)
          ) {
            toast.error(
              field === "start"
                ? "Start time must be before end time"
                : "End time must be after start time",
            );
            return;
          }

          updateEventField(field, value);
        }, 1000);
      }
    },
    [isCreating, startDate, endDate, updateEventField],
  );

  const handleAllDayChange = useCallback(
    (value: boolean) => {
      setIsAllDay(value);

      if (!isCreating) {
        // Immediately trigger update for all-day toggle
        updateEventField("isAllDay", value);
      }
    },
    [isCreating, updateEventField],
  );

  const handleCalendarChange = useCallback(
    async (calendarId: string) => {
      setSelectedCalendarId(calendarId);

      if (!isCreating && selectedEvent) {
        const oldCalendarId = selectedEvent.calendarId || "primary";

        if (oldCalendarId === calendarId) {
          return;
        }

        setIsSaving(true);
        try {
          // Preserve original event timezone if available, otherwise use user's current timezone
          const originalTimezone =
            selectedEvent.start?.timeZone ||
            selectedEvent.end?.timeZone ||
            getUserTimezone();

          // For all-day events, extract date safely
          let startDateValue: string;
          let endDateValue: string;

          if (isAllDay) {
            // Extract date from datetime-local format or use as-is if already in date format
            startDateValue = startDate.includes("T")
              ? startDate.split("T")[0]
              : startDate;
            endDateValue = endDate.includes("T")
              ? endDate.split("T")[0]
              : endDate;
          } else {
            // For timed events, convert to ISO preserving the timezone
            startDateValue = dateTimeLocalToISO(startDate);
            endDateValue = dateTimeLocalToISO(endDate);
          }

          const createPayload = {
            summary,
            description,
            is_all_day: isAllDay,
            start: startDateValue,
            end: endDateValue,
            fixedTime: !isAllDay,
            calendar_id: calendarId,
            timezone: originalTimezone, // Preserve original timezone
          };

          // Create in new calendar first
          const newEvent = await calendarApi.createEventDefault(createPayload);

          // Delete from old calendar
          await calendarApi.deleteEventByAgent({
            event_id: selectedEvent.id,
            calendar_id: oldCalendarId,
            summary: selectedEvent.summary,
          });

          // Update store: remove old event and add new event
          removeEventFromStore(selectedEvent.id);
          addEventToStore(newEvent);

          // Update local state with the new event and sync all form fields
          setSelectedEvent(newEvent);
          setSelectedCalendarId(newEvent.calendarId || calendarId);

          // Sync form state with the new event
          setSummary(newEvent.summary || "");
          setDescription(newEvent.description || "");

          const newStartDateTime =
            newEvent.start?.dateTime || newEvent.start?.date;
          const newEndDateTime = newEvent.end?.dateTime || newEvent.end?.date;

          if (newStartDateTime) {
            setStartDate(isoToDateTimeLocal(newStartDateTime));
          }
          if (newEndDateTime) {
            setEndDate(isoToDateTimeLocal(newEndDateTime));
          }
          setIsAllDay(!!newEvent.start?.date);

          onEventUpdate?.();
          toast.success("Event moved to new calendar");
        } catch (error) {
          console.error("Calendar change error:", error);
          const errorMsg =
            error instanceof Error
              ? error.message
              : "Failed to move event to new calendar";
          toast.error(errorMsg);
          setSelectedCalendarId(selectedEvent.calendarId || "primary");
        } finally {
          setIsSaving(false);
        }
      }
    },
    [
      isCreating,
      selectedEvent,
      summary,
      description,
      isAllDay,
      startDate,
      endDate,
      removeEventFromStore,
      addEventToStore,
      onEventUpdate,
    ],
  );

  const handleCreate = useCallback(async () => {
    if (!summary.trim()) {
      toast.error("Event title is required");
      return;
    }

    if (new Date(startDate) >= new Date(endDate)) {
      toast.error("End time must be after start time");
      return;
    }

    if (!selectedCalendarId) {
      toast.error("Please select a calendar");
      return;
    }

    setIsSaving(true);
    try {
      const recurrence = buildRecurrencePayload(
        recurrenceType,
        customRecurrenceDays,
      );

      const payload = {
        summary,
        description,
        is_all_day: isAllDay,
        start: isAllDay
          ? startDate.split("T")[0]
          : dateTimeLocalToISO(startDate),
        end: isAllDay ? endDate.split("T")[0] : dateTimeLocalToISO(endDate),
        fixedTime: !isAllDay,
        calendar_id: selectedCalendarId || "primary",
        timezone: getUserTimezone(),
        ...(recurrence && { recurrence }),
      };

      const createdEvent = await calendarApi.createEventDefault(payload);

      // Track calendar event creation
      trackEvent(ANALYTICS_EVENTS.CALENDAR_EVENT_CREATED, {
        is_all_day: isAllDay,
        has_description: !!description,
        has_recurrence: !!recurrence,
        recurrence_type: recurrenceType,
        calendar_id: selectedCalendarId,
      });
      // Add the created event to the store so it appears immediately
      addEventToStore(createdEvent);

      onEventUpdate?.();
      close();
      toast.success("Event created successfully");
    } catch (error) {
      console.error("Event creation error:", error);
      toast.error("Failed to create event");
    } finally {
      setIsSaving(false);
    }
  }, [
    summary,
    description,
    isAllDay,
    startDate,
    endDate,
    selectedCalendarId,
    recurrenceType,
    customRecurrenceDays,
    onEventUpdate,
    close,
  ]);

  const handleDelete = useCallback(async () => {
    if (!selectedEvent || isCreating) return;

    setIsSaving(true);
    try {
      await calendarApi.deleteEventByAgent({
        event_id: selectedEvent.id,
        calendar_id:
          selectedEvent.calendarId || selectedCalendarId || "primary",
        summary: selectedEvent.summary,
      });

      // Track calendar event deletion
      trackEvent(ANALYTICS_EVENTS.CALENDAR_EVENT_DELETED, {
        event_id: selectedEvent.id,
        calendar_id: selectedEvent.calendarId || selectedCalendarId,
      });

      // Remove event from store immediately
      removeEventFromStore(selectedEvent.id);

      onEventUpdate?.();
      close();
    } catch (error) {
      console.error("Event deletion error:", error);
    } finally {
      setIsSaving(false);
    }
  }, [
    selectedEvent,
    isCreating,
    selectedCalendarId,
    removeEventFromStore,
    onEventUpdate,
    close,
  ]);

  useEffect(() => {
    return () => {
      if (summaryTimeoutRef.current) clearTimeout(summaryTimeoutRef.current);
      if (descriptionTimeoutRef.current)
        clearTimeout(descriptionTimeoutRef.current);
      if (dateTimeoutRef.current) clearTimeout(dateTimeoutRef.current);
    };
  }, []);

  return {
    isOpen,
    selectedEvent,
    isCreating,
    summary,
    description,
    startDate,
    endDate,
    isAllDay,
    selectedCalendarId,
    isSaving,
    recurrenceType,
    customRecurrenceDays,
    setIsAllDay: handleAllDayChange,
    setSelectedCalendarId: handleCalendarChange,
    setRecurrenceType,
    setCustomRecurrenceDays,
    handleSummaryChange,
    handleDescriptionChange,
    handleDateChange,
    handleCreate,
    handleDelete,
    openForEvent,
    openForCreate,
    close,
  };
};
