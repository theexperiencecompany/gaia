import { RefObject, useEffect } from "react";

import { CalendarEventPositions } from "@/features/calendar/hooks/useCalendarEventPositioning";

interface UseCalendarScrollProps {
  scrollContainerRef: RefObject<HTMLDivElement | null>;
  dayEvents: CalendarEventPositions;
  selectedDate: Date;
}

export const useCalendarScroll = ({
  scrollContainerRef,
  dayEvents,
  selectedDate,
}: UseCalendarScrollProps) => {
  useEffect(() => {
    if (!scrollContainerRef.current) return;

    const timeoutId = setTimeout(() => {
      if (!scrollContainerRef.current) return;

      // Scroll to first timed event if it exists
      if (dayEvents.timedEvents.length > 0) {
        const firstEvent = dayEvents.timedEvents.reduce((earliest, current) =>
          current.top < earliest.top ? current : earliest,
        );

        const scrollPosition = Math.max(0, firstEvent.top - 100);

        scrollContainerRef.current.scrollTo({
          top: scrollPosition,
          behavior: "smooth",
        });
      } else {
        // Default to 12 AM if no timed events
        const scrollToHour = 0;
        const scrollPosition = scrollToHour * 64;

        scrollContainerRef.current.scrollTo({
          top: scrollPosition,
          behavior: "smooth",
        });
      }
    }, 100);

    return () => clearTimeout(timeoutId);
  }, [selectedDate, dayEvents, scrollContainerRef]);
};
