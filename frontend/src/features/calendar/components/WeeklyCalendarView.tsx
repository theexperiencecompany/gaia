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
  useSetVisibleMonthYear,
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
  // Refs
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const firstDateRef = useRef<Date | null>(null);
  const lastDateRef = useRef<Date | null>(null);
  const hasInitialFetchedRef = useRef<boolean>(false);
  const hasScrolledToTodayRef = useRef<boolean>(false);

  // State
  const [columnWidth, setColumnWidth] = useState(150);
  const [extendedDates, setExtendedDates] = useState<Date[]>(() =>
    getInitialMonthlyDateRange(new Date()),
  );

  // Store selectors
  const selectedDate = useCalendarSelectedDate();
  const currentWeek = useCalendarCurrentWeek();
  const daysToShow = useDaysToShow();
  const setVisibleMonthYear = useSetVisibleMonthYear();

  // Hooks
  const {
    events,
    loading,
    error,
    calendars,
    selectedCalendars,
    isInitialized,
    loadEvents,
  } = useSharedCalendar();

  // Memoized values
  const hours = useMemo(() => Array.from({ length: 24 }, (_, i) => i), []);

  const getEventColorForGrid = useCallback(
    (event: GoogleCalendarEvent) => {
      return getEventColor(event, calendars);
    },
    [calendars],
  );

  // Find today's index in the dates array for initial scroll
  const getTodayIndex = useCallback((dates: Date[]) => {
    const today = new Date();
    const todayStr = today.toISOString().split("T")[0];
    return dates.findIndex(
      (date) => date.toISOString().split("T")[0] === todayStr,
    );
  }, []);

  // Scroll observer and infinite loader
  const scrollMetrics = useHorizontalScrollObserver(
    scrollContainerRef,
    columnWidth,
    extendedDates,
  );

  const { loadMorePast, loadMoreFuture, isLoadingPast, isLoadingFuture } =
    useInfiniteCalendarLoader({
      scrollMetrics,
      selectedCalendars,
      isInitialized,
    });

  // Update date refs when dates change
  useEffect(() => {
    if (extendedDates.length > 0) {
      firstDateRef.current = extendedDates[0];
      lastDateRef.current = extendedDates[extendedDates.length - 1];
    }
  }, [extendedDates]);

  // Effect 1: Scroll to today on initial load
  useEffect(() => {
    if (
      !hasScrolledToTodayRef.current &&
      extendedDates.length > 0 &&
      scrollContainerRef.current &&
      columnWidth > 0
    ) {
      const todayIndex = getTodayIndex(extendedDates);
      if (todayIndex !== -1) {
        const scrollContainer = scrollContainerRef.current;
        const containerWidth = scrollContainer.clientWidth - 80;
        const visibleColumns = Math.floor(containerWidth / columnWidth);

        const targetScroll = Math.max(
          0,
          todayIndex * columnWidth - (visibleColumns / 2) * columnWidth,
        );

        setTimeout(() => {
          scrollContainer.scrollTo({
            left: targetScroll,
            behavior: "auto",
          });
          hasScrolledToTodayRef.current = true;
        }, 100);
      }
    }
  }, [extendedDates, columnWidth, getTodayIndex]);

  // Effect 2: Initial fetch of events for 3-month range
  useEffect(() => {
    if (
      selectedCalendars.length > 0 &&
      isInitialized &&
      !hasInitialFetchedRef.current
    ) {
      const dates = getInitialMonthlyDateRange(currentWeek);
      const start = dates[0];
      const end = dates[dates.length - 1];

      loadEvents(selectedCalendars, true, start, end);
      hasInitialFetchedRef.current = true;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCalendars, isInitialized]);

  // Effect 3: Reset fetch flag when calendars change
  useEffect(() => {
    hasInitialFetchedRef.current = false;
  }, [selectedCalendars]);

  // Effect 4: Load more past events when scrolling backwards
  useEffect(() => {
    if (
      scrollMetrics.shouldLoadPast &&
      !isLoadingPast &&
      firstDateRef.current
    ) {
      loadMorePast(firstDateRef.current).then((newDates) => {
        if (newDates.length > 0) {
          const scrollContainer = scrollContainerRef.current;
          const prevScrollLeft = scrollContainer?.scrollLeft || 0;

          setExtendedDates((prev) => {
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

  // Effect 5: Load more future events when scrolling forwards
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

  // Effect 6: Update visible month/year based on scroll position
  useEffect(() => {
    if (extendedDates.length > 0 && scrollMetrics.visibleStartIndex >= 0) {
      const visibleDateIndex = Math.min(
        scrollMetrics.visibleStartIndex + Math.floor(daysToShow / 2),
        extendedDates.length - 1,
      );
      const visibleDate = extendedDates[visibleDateIndex];

      if (visibleDate) {
        const month = visibleDate.toLocaleDateString("en-US", {
          month: "long",
        });
        const year = visibleDate.getFullYear().toString();
        setVisibleMonthYear(month, year);
      }
    }
  }, [
    scrollMetrics.visibleStartIndex,
    extendedDates,
    daysToShow,
    setVisibleMonthYear,
  ]);

  // Effect 7: Calculate dynamic column width based on container size
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

    return () => resizeObserver.disconnect();
  }, [daysToShow]);

  return (
    <div className="flex h-full w-full justify-center p-4 pt-4">
      <div
        ref={containerRef}
        className="flex h-full w-full flex-col overflow-hidden"
      >
        <div
          ref={scrollContainerRef}
          data-calendar-scroll
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
            getEventColor={(event) => getEventColor(event, calendars)}
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
