import { Button } from "@heroui/button";
import { Input, Textarea } from "@heroui/input";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import {
  Bell,
  Calendar as CalendarIcon,
  Clock,
  Edit3,
  History,
  Info,
  Link2,
  LucideIcon,
  Repeat,
  User,
} from "lucide-react";
import React, { useEffect, useState } from "react";
import Twemoji from "react-twemoji";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/shadcn/accordion";
import { calendarApi } from "@/features/calendar/api/calendarApi";
import {
  formatEventDate,
  getEventIcon,
} from "@/features/calendar/utils/calendarUtils";
import {
  CalendarEventDialogProps,
  EventCreatePayload,
} from "@/types/features/calendarTypes";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "../../../components/ui/shadcn/dialog";

export default function CalendarEventDialog({
  event,
  open,
  onOpenChange,
  mode = "view",
}: CalendarEventDialogProps) {
  const [summary, setSummary] = useState("");
  const [description, setDescription] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [isAllDay, setIsAllDay] = useState(false);
  const [errors, setErrors] = useState<{
    summary?: string;
    date?: string;
  }>({});
  const [recurrence, setRecurrence] = useState<string>("none");

  // Reset form when dialog closes
  useEffect(() => {
    if (open) {
      return;
    }
    setSummary("");
    setDescription("");
    setStart("");
    setEnd("");
    setIsAllDay(false);
    setErrors({});
    setRecurrence("none");
    // setShowCustomRecurrence(false);
    // setCustomRecurrence({ interval: 1, unit: "day" });
  }, [open]);

  // If in edit mode, populate form with event data
  useEffect(() => {
    if (mode === "create" && event) {
      setSummary(event.summary || "");
      setDescription(event.description || "");
      if ("start" in event) {
        setStart(
          new Date(event.start.dateTime || event.start.date || "")
            .toISOString()
            .slice(0, 16),
        );
        setEnd(
          new Date(event.end.dateTime || event.end.date || "")
            .toISOString()
            .slice(0, 16),
        );
      }
    }
  }, [event, mode]);

  if (mode === "create") {
    const validateForm = () => {
      const newErrors: { summary?: string; date?: string } = {};
      if (!summary.trim()) newErrors.summary = "Summary is required";
      if (!isAllDay) {
        if (!start || !end) {
          newErrors.date = "Start and end times are required for timed events";
        } else {
          const startDate = new Date(start);
          const endDate = new Date(end);
          if (isNaN(startDate.getTime())) newErrors.date = "Invalid start date";
          else if (isNaN(endDate.getTime()))
            newErrors.date = "Invalid end date";
          else if (endDate <= startDate)
            newErrors.date = "End time must be after start time";
        }
      }
      setErrors(newErrors);
      return Object.keys(newErrors).length === 0;
    };

    const handleSubmit = async (e: React.FormEvent) => {
      e.preventDefault();
      if (!validateForm()) return;
      try {
        const eventPayload: EventCreatePayload = {
          summary,
          description,
          is_all_day: isAllDay,
        };
        if (isAllDay) {
          if (start) eventPayload.start = start.split("T")[0];
          if (end) eventPayload.end = end.split("T")[0];
        } else {
          eventPayload.start = new Date(start).toISOString();
          eventPayload.end = new Date(end).toISOString();
          eventPayload.fixedTime = true;
        }
        // TODO: Handle recurrence if needed
        await calendarApi.createEventDefault(eventPayload);
        onOpenChange(false);
      } catch (error) {
        // Error toast is handled by calendarApi
        console.error("Failed to create event:", error);
      }
    };

    return (
      <Modal isOpen={open} onClose={() => onOpenChange(false)}>
        <ModalContent className="max-w-xl rounded-2xl border-none bg-zinc-900">
          <ModalHeader className="flex items-center gap-3 pb-2">
            <CalendarIcon size={20} className="text-zinc-100" />
            <span className="text-xl font-bold text-zinc-100">
              Create Event
            </span>
          </ModalHeader>
          <ModalBody className="flex flex-col gap-6 pt-0">
            <Input
              placeholder="Event title"
              classNames={{
                input:
                  "text-2xl font-semibold bg-transparent border-0 text-zinc-100 placeholder:text-zinc-500",
                inputWrapper:
                  "border-0 bg-transparent shadow-none hover:bg-transparent focus:bg-transparent data-[focus=true]:bg-transparent",
              }}
              value={summary}
              variant="underlined"
              onChange={(e) => {
                setSummary(e.target.value);
                if (errors.summary)
                  setErrors({ ...errors, summary: undefined });
              }}
              required
              autoFocus
            />
            <Textarea
              placeholder="Add a description..."
              value={description || ""}
              onChange={(e) => setDescription(e.target.value)}
              minRows={1}
              maxRows={5}
              variant="underlined"
              classNames={{
                input:
                  "bg-transparent border-0 text-zinc-200 placeholder:text-zinc-500",
                inputWrapper:
                  "border-0 bg-transparent shadow-none hover:bg-transparent focus:bg-transparent data-[focus=true]:bg-transparent",
              }}
            />
            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                id="isAllDay"
                className="h-4 w-4 rounded border-zinc-700 bg-zinc-800"
                checked={isAllDay}
                onChange={(e) => {
                  setIsAllDay(e.target.checked);
                  if (errors.date) setErrors({ ...errors, date: undefined });
                }}
              />
              <label
                htmlFor="isAllDay"
                className="text-sm text-zinc-300 select-none"
              >
                All-day event
              </label>
            </div>
            {!isAllDay && (
              <div className="flex gap-4">
                <div className="flex-1">
                  <label className="mb-1 block font-medium text-zinc-300">
                    Start*
                  </label>
                  <Input
                    type="datetime-local"
                    value={start}
                    onChange={(e) => {
                      setStart(e.target.value);
                      if (errors.date)
                        setErrors({ ...errors, date: undefined });
                    }}
                    classNames={{
                      input: `bg-zinc-800 text-zinc-100 ${errors.date ? "border border-red-500" : ""}`,
                    }}
                    required={!isAllDay}
                  />
                </div>
                <div className="flex-1">
                  <label className="mb-1 block font-medium text-zinc-300">
                    End*
                  </label>
                  <Input
                    type="datetime-local"
                    value={end}
                    onChange={(e) => {
                      setEnd(e.target.value);
                      if (errors.date)
                        setErrors({ ...errors, date: undefined });
                    }}
                    classNames={{
                      input: `bg-zinc-800 text-zinc-100 ${errors.date ? "border border-red-500" : ""}`,
                    }}
                    required={!isAllDay}
                  />
                </div>
              </div>
            )}
            {isAllDay && (
              <div className="flex gap-4">
                <div className="flex-1">
                  <label className="mb-1 block font-medium text-zinc-300">
                    Start Date (optional)
                  </label>
                  <Input
                    type="date"
                    value={start ? start.split("T")[0] : ""}
                    onChange={(e) => {
                      setStart(e.target.value + "T00:00");
                      if (errors.date)
                        setErrors({ ...errors, date: undefined });
                    }}
                    classNames={{ input: "bg-zinc-800 text-zinc-100" }}
                  />
                </div>
                <div className="flex-1">
                  <label className="mb-1 block font-medium text-zinc-300">
                    End Date (optional)
                  </label>
                  <Input
                    type="date"
                    value={end ? end.split("T")[0] : ""}
                    onChange={(e) => {
                      setEnd(e.target.value + "T23:59");
                      if (errors.date)
                        setErrors({ ...errors, date: undefined });
                    }}
                    classNames={{ input: "bg-zinc-800 text-zinc-100" }}
                  />
                </div>
              </div>
            )}
            {errors.date && (
              <span className="mt-1 block text-sm text-red-500">
                {errors.date}
              </span>
            )}
            <div className="flex items-center gap-3">
              <label
                htmlFor="recurrence"
                className="text-sm text-zinc-300 select-none"
              >
                Recurrence
              </label>
              <select
                id="recurrence"
                className="rounded-xl border border-zinc-700 bg-zinc-800 p-2 text-sm outline-none"
                value={recurrence}
                onChange={(e) => setRecurrence(e.target.value)}
              >
                <option value="">Does not repeat</option>
                <option value="RRULE:FREQ=DAILY">Daily</option>
                <option value="RRULE:FREQ=WEEKLY">Weekly</option>
                <option value="RRULE:FREQ=MONTHLY">Monthly</option>
                <option value="RRULE:FREQ=YEARLY">Annually</option>
                <option value="RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR">
                  Every weekday (Mon-Fri)
                </option>
              </select>
            </div>
          </ModalBody>
          <ModalFooter className="flex justify-end gap-2">
            <Button
              variant="light"
              onPress={() => onOpenChange(false)}
              className="border-0 bg-zinc-800 text-zinc-300 hover:bg-zinc-700 hover:text-zinc-200"
            >
              Cancel
            </Button>
            <Button
              onPress={() =>
                handleSubmit(new Event("submit") as unknown as React.FormEvent)
              }
              className="border-0 bg-zinc-800 text-zinc-200 hover:bg-zinc-700 disabled:bg-zinc-800 disabled:text-zinc-500"
            >
              Create
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    );
  }

  // View mode: render event details.
  const InfoSection = ({
    title,
    children,
  }: {
    title: string;
    children: React.ReactNode;
  }) => (
    <div className="space-y-3 rounded-xl bg-zinc-800 p-4">
      {!!title && <span className="text-medium font-medium">{title}</span>}
      {children}
    </div>
  );

  const InfoItem = ({
    icon: Icon,
    label,
    value,
  }: {
    icon: LucideIcon; // Fixed: Using LucideIcon type instead of any
    label: string;
    value: string | null;
  }) => {
    if (!value) return null;
    return (
      <div className="flex items-center gap-3 text-zinc-300">
        <div className="flex h-6 w-6 items-center justify-center text-zinc-400">
          <Icon size={16} />
        </div>
        <span className="font-medium text-zinc-400">{label}:</span>
        <span className="text-zinc-200">{value}</span>
      </div>
    );
  };

  if (!event) return;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] max-w-lg overflow-y-auto border-none bg-zinc-900!">
        <DialogHeader className="border-b border-zinc-800 pb-4">
          <DialogTitle className="flex items-center gap-3">
            <Twemoji options={{ className: "twemoji max-w-[20px]" }}>
              <div className="rounded-xl bg-zinc-800 p-2">
                {event && getEventIcon(event)}
              </div>
            </Twemoji>
            <span className="text-xl font-bold text-zinc-100">
              {event?.summary}
            </span>
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <InfoSection title="Event Details">
            <InfoItem
              icon={Clock}
              label="Date"
              value={formatEventDate(event)}
            />
            {event?.description && (
              <div className="mt-2 flex gap-3">
                <div className="flex h-6 w-6 items-center justify-center text-zinc-400">
                  <Edit3 size={16} />
                </div>
                <div className="flex-1">
                  <span className="font-medium text-zinc-400">
                    Description:
                  </span>
                  <p className="mt-1 text-zinc-300">{event.description}</p>
                </div>
              </div>
            )}
            <InfoItem
              icon={CalendarIcon}
              label="Start"
              value={
                event?.start?.dateTime
                  ? new Date(event.start.dateTime).toLocaleString()
                  : event?.start?.date || null
              }
            />
            <InfoItem
              icon={CalendarIcon}
              label="End"
              value={
                event?.end?.dateTime
                  ? new Date(event.end.dateTime).toLocaleString()
                  : event?.end?.date || null
              }
            />
          </InfoSection>

          <Accordion collapsible className="my-2 space-y-4" type="single">
            <AccordionItem
              className="rounded-xl border-none bg-zinc-800"
              value="people"
            >
              <AccordionTrigger className="px-4 py-3 hover:no-underline">
                <span className="text-medium font-medium">People</span>
              </AccordionTrigger>
              <AccordionContent className="mt-1 rounded-b-lg bg-zinc-800 px-4 pb-4">
                <InfoItem
                  icon={User}
                  label="Creator"
                  value={event?.creator?.email || null}
                />
                <InfoItem
                  icon={User}
                  label="Organizer"
                  value={event?.organizer?.email || null}
                />
              </AccordionContent>
            </AccordionItem>

            {event?.recurrence && (
              <AccordionItem className="border-none" value="recurrence">
                <AccordionTrigger className="rounded-xl bg-zinc-800 px-4 py-3 hover:no-underline">
                  <span className="text-lg font-semibold">Recurrence</span>
                </AccordionTrigger>
                <AccordionContent className="mt-1 rounded-b-lg px-4 pb-4">
                  <InfoItem
                    icon={Repeat}
                    label="Pattern"
                    value={event.recurrence[0].replace("RRULE:", "")}
                  />
                </AccordionContent>
              </AccordionItem>
            )}

            <AccordionItem
              className="rounded-xl border-none bg-zinc-800"
              value="additional"
            >
              <AccordionTrigger className="px-4 py-3 hover:no-underline">
                <span className="text-medium font-medium">
                  Additional Details
                </span>
              </AccordionTrigger>
              <AccordionContent className="mt-1 rounded-b-lg px-4 pb-4">
                <InfoItem
                  icon={Info}
                  label="Status"
                  value={event?.status || null}
                />
                <InfoItem
                  icon={Bell}
                  label="Reminders"
                  value={event?.reminders?.useDefault ? "Default" : "Custom"}
                />
                <InfoItem
                  icon={Info}
                  label="Event Type"
                  value={event?.eventType || null}
                />
              </AccordionContent>
            </AccordionItem>

            <AccordionItem
              className="rounded-xl border-none bg-zinc-800"
              value="technical"
            >
              <AccordionTrigger className="px-4 py-3 hover:no-underline">
                <span className="text-medium font-medium">
                  Technical Details
                </span>
              </AccordionTrigger>
              <AccordionContent className="mt-1 space-y-3 rounded-b-lg px-4 pb-4">
                <InfoItem
                  icon={History}
                  label="Created"
                  value={
                    event?.created
                      ? new Date(event.created).toLocaleString()
                      : null
                  }
                />
                <InfoItem
                  icon={History}
                  label="Updated"
                  value={
                    event?.updated
                      ? new Date(event.updated).toLocaleString()
                      : null
                  }
                />
                <InfoItem
                  icon={Info}
                  label="iCalUID"
                  value={event?.iCalUID || null}
                />
                <InfoItem
                  icon={Info}
                  label="Sequence"
                  value={event?.sequence?.toString() || null}
                />
                {event?.htmlLink && (
                  <div className="flex items-center gap-3 text-zinc-300">
                    <div className="flex h-6 w-6 items-center justify-center text-zinc-400">
                      <Link2 size={16} />
                    </div>
                    <span className="font-medium text-zinc-400">Link:</span>
                    <a
                      className="max-w-[300px] truncate text-blue-400 underline hover:text-blue-300"
                      href={event.htmlLink}
                      rel="noopener noreferrer"
                      target="_blank"
                    >
                      {event.htmlLink}
                    </a>
                  </div>
                )}
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </div>
      </DialogContent>
    </Dialog>
  );
}
