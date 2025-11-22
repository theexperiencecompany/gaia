"use client";

import { Button } from "@heroui/button";
import { Input, Textarea } from "@heroui/input";
import { Select, SelectItem } from "@heroui/select";
import { Switch } from "@heroui/switch";
import React from "react";

import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/shadcn/accordion";
import { SidebarContent, SidebarFooter } from "@/components/ui/shadcn/sidebar";
import {
  NaturalLanguageDateInput,
  NaturalLanguageDateRangeInput,
} from "@/features/calendar/components/NaturalLanguageDateInput";
import { formatRecurrence } from "@/features/calendar/utils/recurrenceUtils";
import { useConfirmation } from "@/hooks/useConfirmation";
import { Delete02Icon,RepeatIcon } from '@/icons';
import { UserCircleIcon } from "@/icons";
import { CalendarItem } from "@/types/api/calendarApiTypes";
import { GoogleCalendarEvent } from "@/types/features/calendarTypes";

import CalendarEventAIActions from "./CalendarEventAIActions";

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
  React.useEffect(() => {
    if (!selectedEvent || isCreating) return;

    const handleKeyDown = async (e: KeyboardEvent) => {
      // Check if Delete or Backspace key is pressed
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
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedEvent, isCreating, confirm, summary, onDelete]);

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

  return (
    <div className="flex h-full flex-col">
      <SidebarContent className="flex-1 overflow-y-auto px-6">
        <div className="space-y-4 pt-4">
          <div className="space-y-2">
            <Input
              type="text"
              value={summary}
              onChange={(e) => onSummaryChange(e.target.value)}
              placeholder="Event title"
              classNames={{
                input:
                  "text-2xl  bg-transparent text-zinc-100 placeholder:text-zinc-700",
                inputWrapper:
                  "bg-transparent shadow-none hover:bg-transparent focus:bg-transparent data-[focus=true]:bg-transparent data-[hover=true]:bg-transparent border-red-500!",
              }}
              variant="underlined"
              autoFocus={isCreating}
            />

            <Textarea
              value={description}
              onChange={(e) => onDescriptionChange(e.target.value)}
              placeholder="Add description"
              minRows={6}
              maxRows={6}
              classNames={{
                input: "bg-transparent text-zinc-200 placeholder:text-zinc-700",
                inputWrapper:
                  "bg-zinc-800/30 hover:bg-zinc-800/50 data-[hover=true]:bg-zinc-800/50 shadow-none",
              }}
              variant="flat"
            />
          </div>

          {/* All-day Toggle */}
          <Switch
            isSelected={isAllDay}
            onValueChange={onAllDayChange}
            size="sm"
            color="primary"
          >
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

                {/* <div className="-mb-2 flex w-full justify-center text-zinc-500">
                  <ArrowDown width={19} height={19} />
                </div> */}

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

          {/* Recurrence Selection (only when creating) */}
          {isCreating && (
            <div className="space-y-3">
              <Select
                label="Repeat"
                selectedKeys={recurrenceType ? [recurrenceType] : []}
                selectionMode="single"
                onSelectionChange={(keys) => {
                  const selected = Array.from(keys)[0] as string;
                  if (selected) onRecurrenceTypeChange(selected);
                }}
                classNames={{
                  trigger:
                    "bg-zinc-800/30 hover:bg-zinc-800/50 data-[hover=true]:bg-zinc-800/50 shadow-none",
                  value: "text-zinc-200",
                  popoverContent: "bg-zinc-900 border border-zinc-800",
                  label: "text-zinc-400",
                }}
                startContent={<RepeatIcon className="size-4 text-zinc-500" />}
              >
                <SelectItem key="none" textValue="Does not repeat">
                  Does not repeat
                </SelectItem>
                <SelectItem key="daily" textValue="Daily">
                  Daily
                </SelectItem>
                <SelectItem key="weekdays" textValue="Every weekday (Mon-Fri)">
                  Every weekday (Mon-Fri)
                </SelectItem>
                <SelectItem key="weekly" textValue="Weekly">
                  Weekly
                </SelectItem>
                <SelectItem key="monthly" textValue="Monthly">
                  Monthly
                </SelectItem>
                <SelectItem key="yearly" textValue="Yearly">
                  Yearly
                </SelectItem>
                <SelectItem key="custom" textValue="Custom (select days)">
                  Custom (select days)
                </SelectItem>
              </Select>

              {recurrenceType === "custom" && (
                <div className="space-y-2">
                  <label className="text-sm font-medium text-zinc-400">
                    RepeatIcon on
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {[
                      { label: "S", value: "SU" },
                      { label: "M", value: "MO" },
                      { label: "T", value: "TU" },
                      { label: "W", value: "WE" },
                      { label: "T", value: "TH" },
                      { label: "F", value: "FR" },
                      { label: "S", value: "SA" },
                    ].map((day) => (
                      <button
                        key={day.value}
                        onClick={() => {
                          const newDays = customRecurrenceDays.includes(
                            day.value,
                          )
                            ? customRecurrenceDays.filter(
                                (d) => d !== day.value,
                              )
                            : [...customRecurrenceDays, day.value];
                          onCustomRecurrenceDaysChange(newDays);
                        }}
                        className={`flex size-9 items-center justify-center rounded-full text-sm font-medium transition-colors ${
                          customRecurrenceDays.includes(day.value)
                            ? "bg-blue-600 text-white"
                            : "bg-zinc-800/50 text-zinc-400 hover:bg-zinc-700"
                        }`}
                      >
                        {day.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Calendar Selection */}
          {calendars.length > 0 && (
            <div className="space-y-3">
              <Select
                label="Calendar"
                selectedKeys={selectedCalendarId ? [selectedCalendarId] : []}
                selectionMode="single"
                onSelectionChange={(keys) => {
                  const selected = Array.from(keys)[0] as string;
                  if (selected) onCalendarChange(selected);
                }}
                isRequired
                classNames={{
                  trigger:
                    "bg-zinc-800/30 hover:bg-zinc-800/50 data-[hover=true]:bg-zinc-800/50 shadow-none",
                  value: "text-zinc-200",
                  popoverContent: "bg-zinc-900 border border-zinc-800",
                  label: "text-zinc-400",
                }}
                startContent={
                  selectedCalendarId && (
                    <div
                      className="size-3 rounded-full"
                      style={{
                        backgroundColor:
                          calendars.find((cal) => cal.id === selectedCalendarId)
                            ?.backgroundColor || "#3b82f6",
                      }}
                    />
                  )
                }
              >
                {calendars.map((cal) => (
                  <SelectItem
                    key={cal.id}
                    textValue={`${cal.name || cal.summary}${cal.primary ? " (Primary)" : ""}`}
                    startContent={
                      <div
                        className="size-3 rounded-full"
                        style={{
                          backgroundColor: cal.backgroundColor || "#3b82f6",
                        }}
                      />
                    }
                  >
                    {cal.name || cal.summary}
                    {cal.primary ? " (Primary)" : ""}
                  </SelectItem>
                ))}
              </Select>
            </div>
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
            <Accordion type="single" collapsible className="w-full">
              <AccordionItem value="details" className="border-zinc-800/50">
                <AccordionTrigger className="text-sm font-medium text-zinc-400 hover:text-zinc-300">
                  Additional Details
                </AccordionTrigger>
                <AccordionContent>
                  <div className="space-y-3 rounded-lg bg-zinc-800/20 p-4">
                    {selectedEvent.created && (
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-zinc-500">Created</span>
                        <span className="text-zinc-400">
                          {new Date(selectedEvent.created).toLocaleDateString()}
                        </span>
                      </div>
                    )}
                    {selectedEvent.updated && (
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-zinc-500">Updated</span>
                        <span className="text-zinc-400">
                          {new Date(selectedEvent.updated).toLocaleDateString()}
                        </span>
                      </div>
                    )}
                    {selectedEvent.organizer?.email && (
                      <div className="flex items-start justify-between gap-3 text-sm">
                        <div className="flex items-center gap-2 text-zinc-500">
                          <UserCircleIcon className="size-4" />
                          <span>Organizer</span>
                        </div>
                        <span className="truncate text-right text-zinc-400">
                          {selectedEvent.organizer.email}
                        </span>
                      </div>
                    )}
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
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
              disabled={isSaving || !summary.trim()}
              color="primary"
              fullWidth
              isLoading={isSaving}
            >
              {isSaving ? "Creating..." : "Create Event"}
            </Button>
          ) : (
            <>
              <div className="flex-1 text-center text-sm text-zinc-500">
                {isSaving ? "Saving changes..." : "Changes saved"}
              </div>
              <button
                onClick={async () => {
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
                }}
                disabled={isSaving}
                className="cursor-pointer rounded-lg bg-zinc-800/50 p-2.5 text-red-400 transition-all hover:bg-red-500/10 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
                aria-label="Delete event"
              >
                <Delete02Icon className="size-4" />
              </button>
            </>
          )}
        </div>
      </SidebarFooter>

      {/* Confirmation Dialog */}
      <ConfirmationDialog {...confirmationProps} />
    </div>
  );
};
