"use client";

import React from "react";

import { Button } from "@heroui/button";
import { Input, Textarea } from "@heroui/input";
import { Select, SelectItem } from "@heroui/select";
import { Switch } from "@heroui/switch";
import { ArrowDown, Repeat, Trash2 } from "lucide-react";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/shadcn/accordion";
import {
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
} from "@/components/ui/shadcn/sidebar";
import {
  Calendar01Icon,
  CalendarIcon,
  Cancel01Icon,
  PencilEdit02Icon,
  UserCircleIcon,
} from "@/components/shared/icons";
import { GoogleCalendarEvent } from "@/types/features/calendarTypes";
import { useCalendarStore } from "@/stores/calendarStore";
import { cn } from "@/lib/utils";
import { formatRecurrence } from "@/features/calendar/utils/recurrenceUtils";
import { DateTimePicker } from "@/features/calendar/components/DateTimePicker";
import { DatePickerWithRange } from "@/features/calendar/components/DatePickerWithRange";

interface EventSidebarProps {
  isOpen: boolean;
  isCreating: boolean;
  selectedEvent: GoogleCalendarEvent | null;
  summary: string;
  description: string;
  startDate: string;
  endDate: string;
  isAllDay: boolean;
  selectedCalendarId: string;
  isSaving: boolean;
  onSummaryChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
  onAllDayChange: (value: boolean) => void;
  onCalendarChange: (calendarId: string) => void;
  onCreate: () => void;
  onDelete: () => void;
  onClose: () => void;
}

export const EventSidebar: React.FC<EventSidebarProps> = ({
  isOpen,
  isCreating,
  selectedEvent,
  summary,
  description,
  startDate,
  endDate,
  isAllDay,
  selectedCalendarId,
  isSaving,
  onSummaryChange,
  onDescriptionChange,
  onStartDateChange,
  onEndDateChange,
  onAllDayChange,
  onCalendarChange,
  onCreate,
  onDelete,
  onClose,
}) => {
  const { calendars } = useCalendarStore();

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
      <SidebarHeader className="flex w-full items-end justify-end px-6 pt-4 pb-0">
        <button
          onClick={onClose}
          className="cursor-pointer rounded-lg p-2 text-zinc-400 transition-colors hover:bg-zinc-800/50 hover:text-zinc-200"
          aria-label="Close"
        >
          <Cancel01Icon className="size-4" />
        </button>
      </SidebarHeader>

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

          {/* Date & Time Section */}
          <div className="space-y-4">
            <div className="space-y-3">
              {isAllDay ? (
                <div>
                  <label className="mb-2 flex items-center gap-2 text-sm font-medium text-zinc-400">
                    Date Range
                  </label>
                  <DatePickerWithRange
                    from={startDate ? new Date(startDate) : undefined}
                    to={endDate ? new Date(endDate) : undefined}
                    onDateChange={(
                      from: Date | undefined,
                      to: Date | undefined,
                    ) => {
                      if (from) {
                        onStartDateChange(
                          from.toISOString().split("T")[0] + "T00:00",
                        );
                      }
                      if (to) {
                        onEndDateChange(
                          to.toISOString().split("T")[0] + "T23:59",
                        );
                      }
                    }}
                    placeholder="Select date range"
                  />
                </div>
              ) : (
                <div>
                  <div>
                    <label className="mb-1 text-xs text-zinc-500">Start</label>
                    <DateTimePicker
                      date={startDate ? new Date(startDate) : undefined}
                      onDateChange={(date: Date | undefined) => {
                        if (date) {
                          onStartDateChange(date.toISOString().slice(0, 16));
                        }
                      }}
                      placeholder="Select start date and time"
                    />
                  </div>

                  <div className="mt-3 -mb-2 flex w-full justify-center text-zinc-500">
                    <ArrowDown width={19} height={19} />
                  </div>

                  <div>
                    <label className="mb-1 text-xs text-zinc-500">End</label>
                    <DateTimePicker
                      date={endDate ? new Date(endDate) : undefined}
                      onDateChange={(date: Date | undefined) => {
                        if (date) {
                          onEndDateChange(date.toISOString().slice(0, 16));
                        }
                      }}
                      placeholder="Select end date and time"
                    />
                  </div>
                </div>
              )}
            </div>

            <Switch
              isSelected={isAllDay}
              onValueChange={onAllDayChange}
              size="sm"
              color="primary"
            >
              <span className="text-sm text-zinc-500">All-day event</span>
            </Switch>
          </div>

          {/* Recurrence Info (only for existing recurring events) */}
          {!isCreating && selectedEvent?.recurrence && (
            <div className="rounded-lg border border-zinc-800/50 bg-zinc-800/20 p-3">
              <div className="flex items-center gap-2 text-sm">
                <Repeat className="size-4 text-zinc-500" />
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

      <SidebarFooter className="px-6 py-6">
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
                onClick={onDelete}
                disabled={isSaving}
                className="rounded-lg bg-zinc-800/50 p-2.5 text-red-400 transition-all hover:bg-red-500/10 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
                aria-label="Delete event"
              >
                <Trash2 className="size-4" />
              </button>
            </>
          )}
        </div>
      </SidebarFooter>
    </div>
  );
};
