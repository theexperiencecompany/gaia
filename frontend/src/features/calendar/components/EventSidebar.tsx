"use client";

import React, { useState } from "react";

import { Switch } from "@heroui/switch";
import { Repeat, Trash2 } from "lucide-react";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/shadcn/accordion";
import {
  Calendar01Icon,
  CalendarIcon,
  Cancel01Icon,
  PencilEdit02Icon,
  UserCircleIcon,
} from "@/components/shared/icons";
import { GoogleCalendarEvent } from "@/types/features/calendarTypes";
import { useCalendarStore } from "@/stores/calendarStore";
import { formatRecurrence } from "@/features/calendar/utils/recurrenceUtils";

interface EventSidebarProps {
  isOpen: boolean;
  isCreating: boolean;
  selectedEvent: GoogleCalendarEvent | null;
  summary: string;
  description: string;
  startDate: string;
  endDate: string;
  isAllDay: boolean;
  isSaving: boolean;
  onSummaryChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
  onAllDayChange: (value: boolean) => void;
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
  isSaving,
  onSummaryChange,
  onDescriptionChange,
  onStartDateChange,
  onEndDateChange,
  onAllDayChange,
  onCreate,
  onDelete,
  onClose,
}) => {
  const { calendars, selectedCalendars, toggleCalendarSelection } =
    useCalendarStore();
  const [selectedCalendarId, setSelectedCalendarId] =
    useState<string>("primary");

  const formatDisplayDate = (date: string) => {
    if (!date) return "";
    const d = new Date(date);
    return d.toLocaleString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: isAllDay ? undefined : "numeric",
      minute: isAllDay ? undefined : "2-digit",
      hour12: true,
    });
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className={`fixed inset-0 z-40 bg-black/20 backdrop-blur-[2px] transition-opacity duration-300 ${
          isOpen ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={onClose}
      />

      {/* Sidebar Panel */}
      <div
        className={`fixed top-0 right-0 z-50 h-full w-[440px] border-l border-zinc-800/50 bg-zinc-900/95 shadow-2xl backdrop-blur-xl transition-transform duration-300 ease-out ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="flex h-full flex-col">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-zinc-800/50 px-6 py-4">
            <div className="flex items-center gap-3">
              <CalendarIcon className="size-5 text-zinc-400" />
              <h2 className="text-base font-semibold text-zinc-100">
                {isCreating ? "New Event" : "Event Details"}
              </h2>
            </div>
            <button
              onClick={onClose}
              className="rounded-lg p-2 text-zinc-400 transition-colors hover:bg-zinc-800/50 hover:text-zinc-200"
              aria-label="Close"
            >
              <Cancel01Icon className="size-4" />
            </button>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto px-6 py-6">
            <div className="space-y-6">
              {/* Event Title */}
              <div>
                <input
                  type="text"
                  value={summary}
                  onChange={(e) => onSummaryChange(e.target.value)}
                  placeholder="Event title"
                  className="w-full bg-transparent text-2xl font-semibold text-zinc-100 outline-none placeholder:text-zinc-700"
                  autoFocus={isCreating}
                />
              </div>

              {/* Calendar Selection (only for creating new events) */}
              {isCreating && calendars.length > 0 && (
                <div className="space-y-3">
                  <label className="flex items-center gap-2 text-sm font-medium text-zinc-400">
                    <Calendar01Icon className="size-4" />
                    Select Calendar
                  </label>
                  <select
                    value={selectedCalendarId}
                    onChange={(e) => setSelectedCalendarId(e.target.value)}
                    className="w-full rounded-lg border border-zinc-800 bg-zinc-800/30 px-3.5 py-2.5 text-sm text-zinc-200 transition-all outline-none focus:border-zinc-700 focus:bg-zinc-800/50"
                  >
                    {calendars.map((cal) => (
                      <option key={cal.id} value={cal.id}>
                        {cal.name || cal.summary}
                        {cal.primary ? " (Primary)" : ""}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {/* Date & Time Section */}
              <div className="space-y-4">
                <Switch
                  isSelected={isAllDay}
                  onValueChange={onAllDayChange}
                  size="sm"
                  classNames={{
                    wrapper: "group-data-[selected=true]:bg-blue-600",
                  }}
                >
                  <span className="text-sm font-medium text-zinc-300">
                    All-day event
                  </span>
                </Switch>

                <div className="space-y-3">
                  <div>
                    <label className="mb-2 block text-xs font-medium tracking-wide text-zinc-500 uppercase">
                      Start
                    </label>
                    <input
                      type={isAllDay ? "date" : "datetime-local"}
                      value={
                        isAllDay && startDate
                          ? startDate.split("T")[0]
                          : startDate
                      }
                      onChange={(e) =>
                        onStartDateChange(
                          isAllDay ? e.target.value + "T00:00" : e.target.value,
                        )
                      }
                      className="w-full rounded-lg border border-zinc-800 bg-zinc-800/30 px-3.5 py-2.5 text-sm text-zinc-200 transition-all outline-none focus:border-zinc-700 focus:bg-zinc-800/50"
                    />
                  </div>

                  <div>
                    <label className="mb-2 block text-xs font-medium tracking-wide text-zinc-500 uppercase">
                      End
                    </label>
                    <input
                      type={isAllDay ? "date" : "datetime-local"}
                      value={
                        isAllDay && endDate ? endDate.split("T")[0] : endDate
                      }
                      onChange={(e) =>
                        onEndDateChange(
                          isAllDay ? e.target.value + "T23:59" : e.target.value,
                        )
                      }
                      className="w-full rounded-lg border border-zinc-800 bg-zinc-800/30 px-3.5 py-2.5 text-sm text-zinc-200 transition-all outline-none focus:border-zinc-700 focus:bg-zinc-800/50"
                    />
                  </div>
                </div>
              </div>

              {/* Description */}
              <div>
                <label className="mb-2 flex items-center gap-2 text-sm font-medium text-zinc-400">
                  <PencilEdit02Icon className="size-4" />
                  Description
                </label>
                <textarea
                  value={description}
                  onChange={(e) => onDescriptionChange(e.target.value)}
                  placeholder="Add description"
                  rows={4}
                  className="w-full resize-none rounded-lg border border-zinc-800 bg-zinc-800/30 px-3.5 py-2.5 text-sm leading-relaxed text-zinc-200 transition-all outline-none placeholder:text-zinc-700 focus:border-zinc-700 focus:bg-zinc-800/50"
                />
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
                              {new Date(
                                selectedEvent.created,
                              ).toLocaleDateString()}
                            </span>
                          </div>
                        )}
                        {selectedEvent.updated && (
                          <div className="flex items-center justify-between text-sm">
                            <span className="text-zinc-500">Updated</span>
                            <span className="text-zinc-400">
                              {new Date(
                                selectedEvent.updated,
                              ).toLocaleDateString()}
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
          </div>

          {/* Footer */}
          <div className="border-t border-zinc-800/50 px-6 py-4">
            <div className="flex items-center gap-3">
              {isCreating ? (
                <button
                  onClick={onCreate}
                  disabled={isSaving || !summary.trim()}
                  className="flex-1 rounded-lg bg-blue-600 py-2.5 text-sm font-medium text-white transition-all hover:bg-blue-700 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-blue-600"
                >
                  {isSaving ? "Creating..." : "Create Event"}
                </button>
              ) : (
                <>
                  <button
                    onClick={onDelete}
                    disabled={isSaving}
                    className="rounded-lg border border-zinc-800 bg-zinc-800/50 p-2.5 text-red-400 transition-all hover:border-red-500/20 hover:bg-red-500/10 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
                    aria-label="Delete event"
                  >
                    <Trash2 className="size-4" />
                  </button>
                  <div className="flex-1 text-center text-sm text-zinc-500">
                    {isSaving ? "Saving changes..." : "Changes saved"}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
};
