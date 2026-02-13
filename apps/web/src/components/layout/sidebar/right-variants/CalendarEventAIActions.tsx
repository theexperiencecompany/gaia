"use client";

import { Button, ButtonGroup } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/react";
import { ArrowDown01Icon } from "@icons";
import Image from "next/image";
import { useRouter } from "next/navigation";
import React from "react";
import {
  getEventColor,
  isTooDark,
} from "@/features/calendar/utils/calendarUtils";
import { useCalendarEventSelection } from "@/features/chat/hooks/useCalendarEventSelection";
import { useAppendToInput } from "@/stores/composerStore";
import type { CalendarItem } from "@/types/api/calendarApiTypes";
import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";

interface CalendarEventAIActionsProps {
  selectedEvent: GoogleCalendarEvent;
  calendars: CalendarItem[];
}

type ActionKey = "attach-event" | "modify" | "reschedule";

interface Action {
  label: string;
  description: string;
  prompt: string;
}

const ACTIONS: Record<ActionKey, Action> = {
  "attach-event": {
    label: "Attach Event to Chat",
    description: "Add this event as context",
    prompt: "Tell me about this event",
  },
  modify: {
    label: "Modify Event",
    description: "Change event details with AI",
    prompt: "Modify this event",
  },
  reschedule: {
    label: "Reschedule Event",
    description: "Find a better time",
    prompt: "Reschedule this event",
  },
};

export default function CalendarEventAIActions({
  selectedEvent,
  calendars,
}: CalendarEventAIActionsProps) {
  const { selectCalendarEvent } = useCalendarEventSelection();
  const appendToInput = useAppendToInput();
  const router = useRouter();
  const [selectedAction, setSelectedAction] = React.useState<Set<ActionKey>>(
    new Set(["attach-event"]),
  );

  const selectedActionKey = Array.from(selectedAction)[0];
  const currentAction = ACTIONS[selectedActionKey];

  const handleAction = () => {
    // Get background color the same way CalendarCard does
    const calendar = calendars?.find(
      (cal) => cal.id === selectedEvent?.organizer?.email,
    );
    const color =
      calendar?.backgroundColor ||
      getEventColor(selectedEvent as GoogleCalendarEvent) ||
      "#00bbff";
    const backgroundColor = isTooDark(color) ? "#ffffff" : color;

    // Select the calendar event first (will be persisted to localStorage)
    selectCalendarEvent({ ...selectedEvent, backgroundColor });

    // Append the prompt to the composer input
    appendToInput(currentAction.prompt);

    // Navigate to chat page
    router.push("/c");
  };

  return (
    <ButtonGroup variant="flat" color="primary" fullWidth>
      <Button
        onPress={handleAction}
        className="flex-1 cursor-pointer"
        startContent={
          <Image
            alt="GAIA Logo"
            src="/images/logos/logo.webp"
            width={18}
            height={18}
          />
        }
      >
        {currentAction.label}
      </Button>
      <Dropdown placement="bottom-end">
        <DropdownTrigger>
          <Button isIconOnly>
            <ArrowDown01Icon className="size-4" />
          </Button>
        </DropdownTrigger>
        <DropdownMenu
          disallowEmptySelection
          aria-label="AI Actions"
          className="min-w-[260px]"
          selectedKeys={selectedAction}
          selectionMode="single"
          onSelectionChange={(keys) =>
            setSelectedAction(keys as Set<ActionKey>)
          }
        >
          {Object.entries(ACTIONS).map(([key, action]) => (
            <DropdownItem key={key} description={action.description}>
              {action.label}
            </DropdownItem>
          ))}
        </DropdownMenu>
      </Dropdown>
    </ButtonGroup>
  );
}
