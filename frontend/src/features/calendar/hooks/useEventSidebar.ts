import { useCallback, useEffect, useRef, useState } from "react";

import { calendarApi } from "@/features/calendar/api/calendarApi";
import { GoogleCalendarEvent } from "@/types/features/calendarTypes";

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

  const summaryTimeoutRef = useRef<NodeJS.Timeout>();
  const descriptionTimeoutRef = useRef<NodeJS.Timeout>();
  const dateTimeoutRef = useRef<NodeJS.Timeout>();

  const resetForm = useCallback(() => {
    setSummary("");
    setDescription("");
    setStartDate("");
    setEndDate("");
    setIsAllDay(false);
    setSelectedCalendarId("");
    setSelectedEvent(null);
    setIsCreating(false);
  }, []);

  const openForEvent = useCallback((event: GoogleCalendarEvent) => {
    setSelectedEvent(event);
    setIsCreating(false);
    setSummary(event.summary || "");
    setDescription(event.description || "");

    const startDateTime = event.start?.dateTime || event.start?.date;
    const endDateTime = event.end?.dateTime || event.end?.date;

    setStartDate(
      startDateTime ? new Date(startDateTime).toISOString().slice(0, 16) : "",
    );
    setEndDate(
      endDateTime ? new Date(endDateTime).toISOString().slice(0, 16) : "",
    );
    setIsAllDay(!!event.start?.date);
    setIsOpen(true);
  }, []);

  const openForCreate = useCallback(() => {
    resetForm();
    setIsCreating(true);
    setIsOpen(true);

    const now = new Date();
    const roundedMinutes = Math.ceil(now.getMinutes() / 15) * 15;
    now.setMinutes(roundedMinutes);
    now.setSeconds(0);

    const start = now.toISOString().slice(0, 16);
    const end = new Date(now.getTime() + 60 * 60 * 1000)
      .toISOString()
      .slice(0, 16);

    setStartDate(start);
    setEndDate(end);
  }, [resetForm]);

  const close = useCallback(() => {
    setIsOpen(false);
    setTimeout(resetForm, 300);
  }, [resetForm]);

  const updateEventField = useCallback(
    async (field: string, value: string | boolean) => {
      if (!selectedEvent || isCreating) return;

      setIsSaving(true);
      try {
        const updatePayload: Record<string, unknown> = {
          event_id: selectedEvent.id,
          calendar_id: selectedEvent.calendarId || "primary",
        };

        if (field === "summary") updatePayload.summary = value;
        if (field === "description") updatePayload.description = value;
        if (field === "start")
          updatePayload.start = new Date(value as string).toISOString();
        if (field === "end")
          updatePayload.end = new Date(value as string).toISOString();
        if (field === "isAllDay") updatePayload.is_all_day = value;

        await calendarApi.updateEventByAgent(
          updatePayload as Parameters<typeof calendarApi.updateEventByAgent>[0],
        );
        onEventUpdate?.();
      } catch (error) {
        console.error("Event update error:", error);
      } finally {
        setIsSaving(false);
      }
    },
    [selectedEvent, isCreating, onEventUpdate],
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
      if (field === "start") setStartDate(value);
      if (field === "end") setEndDate(value);

      if (dateTimeoutRef.current) {
        clearTimeout(dateTimeoutRef.current);
      }

      if (!isCreating) {
        dateTimeoutRef.current = setTimeout(() => {
          updateEventField(field, value);
        }, 500);
      }
    },
    [isCreating, updateEventField],
  );

  const handleCreate = useCallback(async () => {
    if (!summary.trim()) {
      return;
    }

    setIsSaving(true);
    try {
      const payload = {
        summary,
        description,
        is_all_day: isAllDay,
        start: isAllDay
          ? startDate.split("T")[0]
          : new Date(startDate).toISOString(),
        end: isAllDay ? endDate.split("T")[0] : new Date(endDate).toISOString(),
        fixedTime: !isAllDay,
        calendar_id: selectedCalendarId || "primary",
      };

      await calendarApi.createEventDefault(payload);
      onEventUpdate?.();
      close();
    } catch (error) {
      console.error("Event creation error:", error);
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
    onEventUpdate,
    close,
  ]);

  const handleDelete = useCallback(async () => {
    if (!selectedEvent || isCreating) return;

    setIsSaving(true);
    try {
      await calendarApi.deleteEventByAgent({
        event_id: selectedEvent.id,
        calendar_id: selectedEvent.calendarId || "primary",
        summary: selectedEvent.summary,
      });
      onEventUpdate?.();
      close();
    } catch (error) {
      console.error("Event deletion error:", error);
    } finally {
      setIsSaving(false);
    }
  }, [selectedEvent, isCreating, onEventUpdate, close]);

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
    setIsAllDay,
    setSelectedCalendarId,
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
