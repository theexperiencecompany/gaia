import { RefObject, useEffect } from "react";

import { EventPosition } from "@/features/calendar/hooks/useCalendarEventPositioning";

interface UseCalendarScrollProps {
  scrollContainerRef: RefObject<HTMLDivElement | null>;
  dayEvents: EventPosition[];
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

      if (dayEvents.length > 0) {
        const firstEvent = dayEvents.reduce((earliest, current) =>
          current.top < earliest.top ? current : earliest,
        );

        const scrollPosition = Math.max(0, firstEvent.top - 100);

        scrollContainerRef.current.scrollTo({
          top: scrollPosition,
          behavior: "smooth",
        });
      } else {
        const scrollToHour = 8;
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
