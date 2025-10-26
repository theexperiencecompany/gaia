"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { CalendarGrid } from "@/features/calendar/components/CalendarGrid";
import { DateStrip } from "@/features/calendar/components/DateStrip";
import { useHorizontalScrollObserver } from "@/features/calendar/hooks/useHorizontalScrollObserver";
import { useInfiniteCalendarLoader } from "@/features/calendar/hooks/useInfiniteCalendarLoader";
import { useSharedCalendar } from "@/features/calendar/hooks/useSharedCalendar";
import {
  generateMonthDates,
  getInitialMonthlyDateRange,
  getMonthRange,
} from "@/features/calendar/utils/dateRangeUtils";
import { getEventColor } from "@/features/calendar/utils/eventColors";
import {
  useCalendarCurrentWeek,
  useCalendarSelectedDate,
  useDaysToShow,
} from "@/stores/calendarStore";
import { GoogleCalendarEvent } from "@/types/features/calendarTypes";

interface WeeklyCalendarViewProps {
  onEventClick?: (event: GoogleCalendarEvent) => void;
  onDateClick?: (date: Date) => void;
}

const WeeklyCalendarView: React.FC<WeeklyCalendarViewProps> = ({
  onEventClick,
  onDateClick,
}) => {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [columnWidth, setColumnWidth] = useState(150);

  const selectedDate = useCalendarSelectedDate();
  const currentWeek = useCalendarCurrentWeek();
  const daysToShow = useDaysToShow();

  const {
    events,
    loading,
    error,
    calendars,
    selectedCalendars,
    isInitialized,
    loadEvents,
  } = useSharedCalendar();

  const hours = useMemo(() => Array.from({ length: 24 }, (_, i) => i), []);

  // Initialize with current month ± 1 month (3 months total)
  const [extendedDates, setExtendedDates] = useState<Date[]>(() =>
    getInitialMonthlyDateRange(currentWeek),
  );

  // Use refs to track first/last dates to avoid dependency issues
  const firstDateRef = useRef<Date | null>(null);
  const lastDateRef = useRef<Date | null>(null);
  const hasInitialFetchedRef = useRef<boolean>(false);

  // Update refs when dates change
  useEffect(() => {
    if (extendedDates.length > 0) {
      firstDateRef.current = extendedDates[0];
      lastDateRef.current = extendedDates[extendedDates.length - 1];
    }
  }, [extendedDates]);

  // Initial fetch: Load events for all 3 displayed months (prev, current, next)
  useEffect(() => {
    if (
      selectedCalendars.length > 0 &&
      isInitialized &&
      !hasInitialFetchedRef.current
    ) {
      // Generate initial 3-month range
      const dates = getInitialMonthlyDateRange(currentWeek);
      const start = dates[0];
      const end = dates[dates.length - 1];

      loadEvents(selectedCalendars, true, start, end);
      hasInitialFetchedRef.current = true;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCalendars, isInitialized]);

  // Reset fetch flag when calendar selection changes
  useEffect(() => {
    hasInitialFetchedRef.current = false;
  }, [selectedCalendars]);

  // Scroll observer to detect when to load more
  const scrollMetrics = useHorizontalScrollObserver(
    scrollContainerRef,
    columnWidth,
    extendedDates,
  );

  // Infinite loader for bidirectional loading
  const { loadMorePast, loadMoreFuture, isLoadingPast, isLoadingFuture } =
    useInfiniteCalendarLoader({
      scrollMetrics,
      selectedCalendars,
      isInitialized,
    });

  // Load more when scrolling near edges
  useEffect(() => {
    if (
      scrollMetrics.shouldLoadPast &&
      !isLoadingPast &&
      firstDateRef.current
    ) {
      loadMorePast(firstDateRef.current).then((newDates) => {
        if (newDates.length > 0) {
          // Preserve scroll position when prepending dates
          const scrollContainer = scrollContainerRef.current;
          const prevScrollLeft = scrollContainer?.scrollLeft || 0;

          setExtendedDates((prev) => {
            // After state updates, adjust scroll to maintain visual position
            requestAnimationFrame(() => {
              if (scrollContainer) {
                scrollContainer.scrollLeft =
                  prevScrollLeft + newDates.length * columnWidth;
              }
            });
            return [...newDates, ...prev];
          });
        }
      });
    }
  }, [scrollMetrics.shouldLoadPast, isLoadingPast, loadMorePast, columnWidth]);

  useEffect(() => {
    if (
      scrollMetrics.shouldLoadFuture &&
      !isLoadingFuture &&
      lastDateRef.current
    ) {
      loadMoreFuture(lastDateRef.current).then((newDates) => {
        if (newDates.length > 0) {
          setExtendedDates((prev) => [...prev, ...newDates]);
        }
      });
    }
  }, [scrollMetrics.shouldLoadFuture, isLoadingFuture, loadMoreFuture]);

  const getEventColorForGrid = useCallback(
    (event: GoogleCalendarEvent) => {
      return getEventColor(event, calendars);
    },
    [calendars],
  );

  // Current time calculation (updates every minute)
  const [now, setNow] = React.useState<Date>(new Date());
  useEffect(() => {
    const interval = setInterval(() => {
      setNow(new Date());
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  const currentHour = now.getHours();
  const currentMinute = now.getMinutes();
  const currentTimeLabel = now.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  const PX_PER_MINUTE = 64 / 60;
  const currentTimeTop = (currentHour * 60 + currentMinute) * PX_PER_MINUTE;

  // Calculate dynamic column width based on container size
  useEffect(() => {
    const updateColumnWidth = () => {
      if (containerRef.current && scrollContainerRef.current) {
        const containerWidth = containerRef.current.offsetWidth;
        const timeColumnWidth = 80; // w-20
        const availableWidth = containerWidth - timeColumnWidth;
        const calculatedWidth = Math.floor(availableWidth / daysToShow);
        const newColumnWidth = Math.max(calculatedWidth, 120); // min 120px per column

        setColumnWidth((prevWidth) => {
          if (prevWidth === newColumnWidth) return prevWidth;

          // Calculate which column is currently at the left edge of the viewport
          const currentScrollLeft = scrollContainerRef.current!.scrollLeft;
          const currentLeftColumn = Math.floor(currentScrollLeft / prevWidth);

          // After width changes, snap to align columns properly
          requestAnimationFrame(() => {
            if (scrollContainerRef.current) {
              // Snap to the nearest column boundary that fills the viewport
              const newScrollLeft = currentLeftColumn * newColumnWidth;
              scrollContainerRef.current.scrollTo({
                left: newScrollLeft,
                behavior: "auto",
              });
            }
          });

          return newColumnWidth;
        });
      }
    };

    updateColumnWidth();

    const resizeObserver = new ResizeObserver(updateColumnWidth);
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      resizeObserver.disconnect();
    };
  }, [daysToShow]); // Remove columnWidth from dependencies

  return (
    <div className="flex h-full w-full justify-center p-4 pt-4">
      <div
        ref={containerRef}
        className="flex h-full w-full flex-col overflow-hidden"
      >
        <div
          ref={scrollContainerRef}
          className="relative flex h-full w-full flex-col overflow-auto"
          style={{
            scrollSnapType: "x proximity",
          }}
        >
          <DateStrip
            dates={extendedDates}
            selectedDate={selectedDate}
            onDateSelect={onDateClick}
            daysToShow={daysToShow}
            columnWidth={columnWidth}
            isLoadingPast={isLoadingPast}
            isLoadingFuture={isLoadingFuture}
          />

          <CalendarGrid
            hours={hours}
            dates={extendedDates}
            events={events}
            loading={loading}
            error={error}
            selectedCalendars={selectedCalendars}
            onEventClick={onEventClick}
            getEventColor={getEventColorForGrid}
            currentTimeTop={currentTimeTop}
            currentTimeLabel={currentTimeLabel}
            columnWidth={columnWidth}
            isLoadingPast={isLoadingPast}
            isLoadingFuture={isLoadingFuture}
          />
        </div>
      </div>
    </div>
  );
};

export default WeeklyCalendarView;
