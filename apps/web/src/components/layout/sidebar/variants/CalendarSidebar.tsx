"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Kbd } from "@heroui/kbd";
import { Tooltip } from "@heroui/tooltip";
import { useRouter } from "next/navigation";
import Spinner from "@/components/ui/spinner";
import CalendarSelector from "@/features/calendar/components/CalendarSelector";
import { useSharedCalendar } from "@/features/calendar/hooks/useSharedCalendar";
import { Alert02Icon, CalendarAdd01Icon } from "@/icons";
import { cn } from "@/lib";
import { accordionItemStyles } from "../constants";

export default function CalendarSidebar() {
  const router = useRouter();
  const { calendars, selectedCalendars, handleCalendarSelect, loading } =
    useSharedCalendar();

  const handleCreateEvent = () => {
    // Navigate to calendar page which will trigger the event creation
    router.push("/calendar?create=true");
  };

  if (loading.calendars) {
    return (
      <div className="flex h-40 w-full flex-1 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <Tooltip
        content={
          <span className="flex items-center gap-2">
            New Event
            <Kbd className="text-[10px]">C</Kbd>
          </span>
        }
        placement="right"
      >
        <Button
          color="primary"
          size="sm"
          fullWidth
          onPress={handleCreateEvent}
          className="mb-4 flex justify-start text-sm font-medium text-primary"
          variant="flat"
          data-keyboard-shortcut="create-event"
        >
          <CalendarAdd01Icon width={18} height={18} />
          New Event
        </Button>
      </Tooltip>

      <div>
        <div className={cn(accordionItemStyles.trigger)}>Your Calendars</div>

        {calendars.length > 0 && selectedCalendars.length === 0 && (
          <div className="flex justify-center mt-2 mb-1">
            <Chip
              className="mb-2 mx-auto pl-2"
              variant="flat"
              color="danger"
              size="sm"
              startContent={<Alert02Icon width={15} height={15} />}
            >
              You have no selected Calendars
            </Chip>
          </div>
        )}
        <CalendarSelector
          calendars={calendars}
          selectedCalendars={selectedCalendars}
          onCalendarSelect={handleCalendarSelect}
        />
      </div>
    </div>
  );
}
