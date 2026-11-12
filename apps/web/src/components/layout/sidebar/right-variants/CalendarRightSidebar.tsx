"use client";

import {
  Button,
  Input,
  Label,
  ListBox,
  Select,
  Switch,
  TextArea,
} from "@heroui/react";
import { Delete02Icon, RepeatIcon, UserCircleIcon } from "@icons";
import React, { useEffectEvent } from "react";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { inputVariants } from "@/components/shared/controlVariants";
import { fieldVariants } from "@/components/shared/fieldVariants";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { SidebarContent, SidebarFooter } from "@/components/ui/sidebar";
import {
  NaturalLanguageDateInput,
  NaturalLanguageDateRangeInput,
} from "@/features/calendar/components/NaturalLanguageDateInput";
import { formatRecurrence } from "@/features/calendar/utils/recurrenceUtils";
import { useConfirmation } from "@/hooks/useConfirmation";
import type { CalendarItem } from "@/types/api/calendarApiTypes";
import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";
import CalendarEventAIActions from "./CalendarEventAIActions";

const WEEKDAYS = [
  { label: "S", value: "SU" },
  { label: "M", value: "MO" },
  { label: "T", value: "TU" },
  { label: "W", value: "WE" },
  { label: "T", value: "TH" },
  { label: "F", value: "FR" },
  { label: "S", value: "SA" },
];

interface EventSidebarProps {
  isCreating: boolean;
  selectedEvent: GoogleCalendarEvent | null;
  summary: string;
  description: string;
  startDate: string;
  endDate: string;
  isAllDay: boolean;
  selectedCalendarId: string;
  isSaving: boolean;
  recurrenceType: string;
  customRecurrenceDays: string[];
  calendars: CalendarItem[];
  onSummaryChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
  onAllDayChange: (value: boolean) => void;
  onCalendarChange: (calendarId: string) => void;
  onRecurrenceTypeChange: (type: string) => void;
  onCustomRecurrenceDaysChange: (days: string[]) => void;
  onCreate: () => void;
  onDelete: () => void;
}

interface EventTitleFieldsProps {
  summary: string;
  description: string;
  isCreating: boolean;
  onSummaryChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
}

const EventTitleFields: React.FC<EventTitleFieldsProps> = ({
  summary,
  description,
  isCreating,
  onSummaryChange,
  onDescriptionChange,
}) => (
  <div className="space-y-2">
    <Input
      type="text"
      value={summary}
      onChange={(e) => onSummaryChange(e.target.value)}
      placeholder="Event title"
      className="border-b border-zinc-700 bg-transparent px-0 text-2xl shadow-none placeholder:text-zinc-700 hover:bg-transparent focus:bg-transparent"
      autoFocus={isCreating}
    />

    <TextArea
      value={description}
      onChange={(e) => onDescriptionChange(e.target.value)}
      placeholder="Add description"
      rows={6}
      className={inputVariants({
        variant: "translucent",
        className: "placeholder:text-zinc-700",
      })}
    />
  </div>
);

interface EventDateTimeSectionProps {
  isAllDay: boolean;
  startDate: string;
  endDate: string;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
  onAllDayChange: (value: boolean) => void;
}

const EventDateTimeSection: React.FC<EventDateTimeSectionProps> = ({
  isAllDay,
  startDate,
  endDate,
  onStartDateChange,
  onEndDateChange,
  onAllDayChange,
}) => (
  <>
    {/* All-day Toggle */}
    <Switch isSelected={isAllDay} onChange={onAllDayChange} size="sm">
      <span className="text-sm text-zinc-500">All-day event</span>
    </Switch>

    {/* Date & Time Section */}
    <div className="mt-4 mb-10 space-y-3">
      {isAllDay ? (
        <NaturalLanguageDateRangeInput
          label="Date Range"
          startValue={startDate}
          endValue={endDate}
          onStartChange={onStartDateChange}
          onEndChange={onEndDateChange}
          placeholder="Tomorrow, next week, Dec 25 to Dec 31..."
        />
      ) : (
        <>
          <NaturalLanguageDateInput
            label="Start"
            value={startDate}
            onChange={onStartDateChange}
            placeholder="Tomorrow at 3pm..."
            isAllDay={false}
          />

          <NaturalLanguageDateInput
            label="End"
            value={endDate}
            onChange={onEndDateChange}
            placeholder="In 2 hours, 5pm, tomorrow..."
            isAllDay={false}
          />
        </>
      )}
    </div>
  </>
);

interface RecurrenceSelectorProps {
  recurrenceType: string;
  customRecurrenceDays: string[];
  onRecurrenceTypeChange: (type: string) => void;
  onCustomRecurrenceDaysChange: (days: string[]) => void;
}

const RecurrenceSelector: React.FC<RecurrenceSelectorProps> = ({
  recurrenceType,
  customRecurrenceDays,
  onRecurrenceTypeChange,
  onCustomRecurrenceDaysChange,
}) => (
  <div className="space-y-3">
    <Select
      className={fieldVariants({ labelPlacement: "inside" })}
      selectedKey={recurrenceType || null}
      onSelectionChange={(key) => {
        if (key != null) onRecurrenceTypeChange(String(key));
      }}
    >
      <Label>Repeat</Label>
      <Select.Trigger
        className={inputVariants({
          variant: "translucent",
          className: "shadow-none",
        })}
      >
        <RepeatIcon className="size-4 text-zinc-500" />
        <GaiaSelectValue />
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover className="border border-zinc-800">
        <ListBox>
          <GaiaListBoxItem id="none" textValue="Does not repeat">
            Does not repeat
          </GaiaListBoxItem>
          <GaiaListBoxItem id="daily" textValue="Daily">
            Daily
          </GaiaListBoxItem>
          <GaiaListBoxItem id="weekdays" textValue="Every weekday (Mon-Fri)">
            Every weekday (Mon-Fri)
          </GaiaListBoxItem>
          <GaiaListBoxItem id="weekly" textValue="Weekly">
            Weekly
          </GaiaListBoxItem>
          <GaiaListBoxItem id="monthly" textValue="Monthly">
            Monthly
          </GaiaListBoxItem>
          <GaiaListBoxItem id="yearly" textValue="Yearly">
            Yearly
          </GaiaListBoxItem>
          <GaiaListBoxItem id="custom" textValue="Custom (select days)">
            Custom (select days)
          </GaiaListBoxItem>
        </ListBox>
      </Select.Popover>
    </Select>

    {recurrenceType === "custom" && (
      <div className="space-y-2">
        <div className="text-sm font-medium text-zinc-400">Repeat on</div>
        <div className="flex flex-wrap gap-2">
          {WEEKDAYS.map((day) => (
            <button
              type="button"
              key={day.value}
              onClick={() => {
                const newDays = customRecurrenceDays.includes(day.value)
                  ? customRecurrenceDays.filter((d) => d !== day.value)
                  : [...customRecurrenceDays, day.value];
                onCustomRecurrenceDaysChange(newDays);
              }}
              className={`flex size-9 items-center justify-center rounded-full text-sm font-medium transition-colors ${customRecurrenceDays.includes(day.value) ? "bg-blue-600 text-white" : "bg-zinc-800/50 text-zinc-400 hover:bg-zinc-700"}`}
            >
              {day.label}
            </button>
          ))}
        </div>
      </div>
    )}
  </div>
);

interface CalendarSelectorProps {
  calendars: CalendarItem[];
  selectedCalendarId: string;
  onCalendarChange: (calendarId: string) => void;
}

const CalendarSelector: React.FC<CalendarSelectorProps> = ({
  calendars,
  selectedCalendarId,
  onCalendarChange,
}) => (
  <div className="space-y-3">
    <Select
      className={fieldVariants({ labelPlacement: "inside" })}
      selectedKey={selectedCalendarId || null}
      onSelectionChange={(key) => {
        if (key != null) onCalendarChange(String(key));
      }}
      isRequired
    >
      <Label>Calendar</Label>
      <Select.Trigger
        className={inputVariants({
          variant: "translucent",
          className: "shadow-none",
        })}
      >
        {selectedCalendarId && (
          <div
            className="size-3 rounded-full"
            style={{
              backgroundColor:
                calendars.find((cal) => cal.id === selectedCalendarId)
                  ?.backgroundColor || "#3b82f6",
            }}
          />
        )}
        <GaiaSelectValue />
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover className="border border-zinc-800">
        <ListBox>
          {calendars.map((cal) => (
            <GaiaListBoxItem
              key={cal.id}
              id={cal.id}
              textValue={`${cal.name || cal.summary}${cal.primary ? " (Primary)" : ""}`}
            >
              <div
                className="size-3 rounded-full"
                style={{
                  backgroundColor: cal.backgroundColor || "#3b82f6",
                }}
              />
              {cal.name || cal.summary}
              {cal.primary ? " (Primary)" : ""}
            </GaiaListBoxItem>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  </div>
);

interface EventDetailsAccordionProps {
  event: GoogleCalendarEvent;
}

const EventDetailsAccordion: React.FC<EventDetailsAccordionProps> = ({
  event,
}) => (
  <Accordion type="single" collapsible className="w-full">
    <AccordionItem value="details" className="border-zinc-800/50">
      <AccordionTrigger className="text-sm font-medium text-zinc-400 hover:text-zinc-300">
        Additional Details
      </AccordionTrigger>
      <AccordionContent>
        <div className="space-y-3 rounded-lg bg-zinc-800/20 p-4">
          {event.created && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-zinc-500">Created</span>
              <span className="text-zinc-400" suppressHydrationWarning>
                {new Date(event.created).toLocaleDateString()}
              </span>
            </div>
          )}
          {event.updated && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-zinc-500">Updated</span>
              <span className="text-zinc-400" suppressHydrationWarning>
                {new Date(event.updated).toLocaleDateString()}
              </span>
            </div>
          )}
          {event.organizer?.email && (
            <div className="flex items-start justify-between gap-3 text-sm">
              <div className="flex items-center gap-2 text-zinc-500">
                <UserCircleIcon className="size-4" />
                <span>Organizer</span>
              </div>
              <span className="truncate text-right text-zinc-400">
                {event.organizer.email}
              </span>
            </div>
          )}
        </div>
      </AccordionContent>
    </AccordionItem>
  </Accordion>
);

interface DeleteEventButtonProps {
  disabled: boolean;
  onConfirmDelete: () => Promise<void>;
}

const DeleteEventButton: React.FC<DeleteEventButtonProps> = ({
  disabled,
  onConfirmDelete,
}) => (
  <button
    type="button"
    onClick={onConfirmDelete}
    disabled={disabled}
    className="cursor-pointer rounded-lg bg-zinc-800/50 p-2.5 text-red-400 transition-[background-color,transform] hover:bg-red-500/10 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
    aria-label="Delete event"
  >
    <Delete02Icon className="size-4" />
  </button>
);

export const EventSidebar: React.FC<EventSidebarProps> = ({
  isCreating,
  selectedEvent,
  summary,
  description,
  startDate,
  endDate,
  isAllDay,
  selectedCalendarId,
  isSaving,
  recurrenceType,
  customRecurrenceDays,
  onSummaryChange,
  onDescriptionChange,
  onStartDateChange,
  onEndDateChange,
  onAllDayChange,
  onCalendarChange,
  onRecurrenceTypeChange,
  onCustomRecurrenceDaysChange,
  onCreate,
  onDelete,
  calendars,
}) => {
  const { confirm, confirmationProps } = useConfirmation();

  // Handle Delete key press when event is selected
  const handleDeleteKeyDown = useEffectEvent(async (e: KeyboardEvent) => {
    if (!selectedEvent || isCreating) return;

    // Only trigger if not focused on an input element
    const target = e.target as HTMLElement;
    const isInputElement =
      target.tagName === "INPUT" ||
      target.tagName === "TEXTAREA" ||
      target.isContentEditable;

    if ((e.key === "Delete" || e.key === "Backspace") && !isInputElement) {
      e.preventDefault();

      const confirmed = await confirm({
        title: "Delete Event",
        message: `Are you sure you want to delete "${summary}"? This action cannot be undone.`,
        confirmText: "Delete",
        cancelText: "Cancel",
        variant: "destructive",
      });

      if (confirmed) {
        onDelete();
      }
    }
  });

  React.useEffect(() => {
    if (typeof window !== "undefined")
      window.addEventListener("keydown", handleDeleteKeyDown);
    return () => {
      if (typeof window !== "undefined")
        window.removeEventListener("keydown", handleDeleteKeyDown);
    };
  }, []);

  // Set default calendar when calendars are loaded and creating
  React.useEffect(() => {
    if (calendars.length > 0 && !selectedCalendarId && isCreating) {
      const primaryCalendar = calendars.find((cal) => cal.primary);
      onCalendarChange(primaryCalendar?.id || calendars[0].id);
    }
  }, [calendars, selectedCalendarId, isCreating, onCalendarChange]);

  // Set calendar from selected event when viewing/editing
  React.useEffect(() => {
    if (
      selectedEvent?.calendarId &&
      selectedEvent.calendarId !== selectedCalendarId
    ) {
      onCalendarChange(selectedEvent.calendarId);
    }
  }, [selectedEvent, selectedCalendarId, onCalendarChange]);

  const confirmAndDelete = async (): Promise<void> => {
    const confirmed = await confirm({
      title: "Delete Event",
      message: `Are you sure you want to delete "${summary}"? This action cannot be undone.`,
      confirmText: "Delete",
      cancelText: "Cancel",
      variant: "destructive",
    });

    if (confirmed) {
      onDelete();
    }
  };

  return (
    <div className="flex h-full flex-col">
      <SidebarContent className="flex-1 overflow-y-auto px-6">
        <div className="space-y-4 pt-4">
          <EventTitleFields
            summary={summary}
            description={description}
            isCreating={isCreating}
            onSummaryChange={onSummaryChange}
            onDescriptionChange={onDescriptionChange}
          />

          <EventDateTimeSection
            isAllDay={isAllDay}
            startDate={startDate}
            endDate={endDate}
            onStartDateChange={onStartDateChange}
            onEndDateChange={onEndDateChange}
            onAllDayChange={onAllDayChange}
          />

          {/* Recurrence Selection (only when creating) */}
          {isCreating && (
            <RecurrenceSelector
              recurrenceType={recurrenceType}
              customRecurrenceDays={customRecurrenceDays}
              onRecurrenceTypeChange={onRecurrenceTypeChange}
              onCustomRecurrenceDaysChange={onCustomRecurrenceDaysChange}
            />
          )}

          {/* Calendar Selection */}
          {calendars.length > 0 && (
            <CalendarSelector
              calendars={calendars}
              selectedCalendarId={selectedCalendarId}
              onCalendarChange={onCalendarChange}
            />
          )}

          {/* Recurrence Info (only for existing recurring events) */}
          {!isCreating && selectedEvent?.recurrence && (
            <div className="rounded-lg border border-zinc-800/50 bg-zinc-800/20 p-3">
              <div className="flex items-center gap-2 text-sm">
                <RepeatIcon className="size-4 text-zinc-500" />
                <span className="font-medium text-zinc-400">
                  {formatRecurrence(selectedEvent.recurrence)}
                </span>
              </div>
            </div>
          )}

          {/* Additional Details Accordion (only for existing events) */}
          {!isCreating && selectedEvent && (
            <EventDetailsAccordion event={selectedEvent} />
          )}
        </div>
      </SidebarContent>

      <SidebarFooter className="space-y-3 px-6 py-6">
        {/* AI Actions (only for existing events) */}
        {!isCreating && selectedEvent && (
          <CalendarEventAIActions
            selectedEvent={selectedEvent}
            calendars={calendars}
          />
        )}

        {/* Create/Delete Actions */}
        <div className="flex items-center gap-3">
          {isCreating ? (
            <Button
              onPress={onCreate}
              isDisabled={isSaving || !summary.trim()}
              fullWidth
              isPending={isSaving}
              variant="primary"
            >
              {isSaving ? "Creating..." : "Create Event"}
            </Button>
          ) : (
            <>
              <div className="flex-1 text-center text-sm text-zinc-500">
                {isSaving ? "Saving changes..." : "Changes saved"}
              </div>
              <DeleteEventButton
                disabled={isSaving}
                onConfirmDelete={confirmAndDelete}
              />
            </>
          )}
        </div>
      </SidebarFooter>

      {/* Confirmation Dialog */}
      <ConfirmationDialog {...confirmationProps} />
    </div>
  );
};
