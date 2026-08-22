"use client";

import type { Virtualizer } from "@tanstack/react-virtual";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { RefObject } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useHorizontalScrollObserver } from "@/features/calendar/hooks/useHorizontalScrollObserver";
import { useInfiniteCalendarLoader } from "@/features/calendar/hooks/useInfiniteCalendarLoader";
import { getInitialMonthlyDateRange } from "@/features/calendar/utils/dateRangeUtils";
import {
  useCalendarCurrentWeek,
  useCalendarSelectedDate,
  useDaysToShow,
  useSetVisibleMonthYear,
} from "@/stores/calendarStore";

interface UseWeeklyCalendarScrollArgs {
  selectedCalendars: string[];
  isInitialized: boolean;
  loadEvents: (
    calendarIds?: string[],
    reset?: boolean,
    customStartDate?: Date,
    customEndDate?: Date,
    direction?: "past" | "future",
  ) => Promise<unknown>;
}

interface UseWeeklyCalendarScrollResult {
  containerRef: RefObject<HTMLDivElement | null>;
  scrollContainerRef: RefObject<HTMLDivElement | null>;
  columnVirtualizer: Virtualizer<HTMLDivElement, Element>;
  extendedDates: Date[];
  isLoadingPast: boolean;
  isLoadingFuture: boolean;
}

/**
 * Owns the weekly calendar's scrolling machinery: the horizontally virtualized
 * date range, dynamic column width, scroll positioning (today/selected date),
 * infinite loading in both directions, and visible month/year sync. Lets
 * `WeeklyCalendarView` stay a thin render component.
 */
export const useWeeklyCalendarScroll = ({
  selectedCalendars,
  isInitialized,
  loadEvents,
}: UseWeeklyCalendarScrollArgs): UseWeeklyCalendarScrollResult => {
  // Refs
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const firstDateRef = useRef<Date | null>(null);
  const lastDateRef = useRef<Date | null>(null);
  const hasInitialFetchedRef = useRef<boolean>(false);
  const hasScrolledToTodayRef = useRef<boolean>(false);

  // State
  const [columnWidth, setColumnWidth] = useState(150);
  const columnWidthRef = useRef(columnWidth);
  const [extendedDates, setExtendedDates] = useState<Date[]>(() =>
    getInitialMonthlyDateRange(new Date()),
  );

  // Store selectors
  const selectedDate = useCalendarSelectedDate();
  const currentWeek = useCalendarCurrentWeek();
  const daysToShow = useDaysToShow();
  const setVisibleMonthYear = useSetVisibleMonthYear();

  // Latest-value refs so effects that must react to only one value (e.g. the
  // selected-date effect below) still read fresh data when they run without
  // re-running on every change of these.
  const extendedDatesRef = useRef(extendedDates);
  const selectedCalendarsRef = useRef(selectedCalendars);
  useEffect(() => {
    selectedCalendarsRef.current = selectedCalendars;
  }, [selectedCalendars]);
  const loadEventsRef = useRef(loadEvents);
  useEffect(() => {
    loadEventsRef.current = loadEvents;
  });

  // Memoized values
  // Create single virtualizer instance for all components to share
  // Recreate when columnWidth changes to ensure proper column sizing
  const columnVirtualizer = useVirtualizer({
    horizontal: true,
    count: extendedDates.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: () => columnWidth,
    overscan: 5,
  });

  // Notify virtualizer when columnWidth or dates change so it recalculates
  useEffect(() => {
    columnWidthRef.current = columnWidth;
    columnVirtualizer.measure();
  }, [columnWidth, extendedDates.length, columnVirtualizer]);

  // Find today's index in the dates array for initial scroll
  const getTodayIndex = useCallback((dates: Date[]) => {
    const today = new Date();
    const todayStr = today.toISOString().split("T")[0];
    return dates.findIndex(
      (date) => date.toISOString().split("T")[0] === todayStr,
    );
  }, []);

  // Helper function to scroll to a specific date. Reads dates/width through
  // refs so its identity stays stable for the effects below.
  const scrollToDate = useCallback(
    (targetDate: Date, behavior: ScrollBehavior = "smooth") => {
      if (!scrollContainerRef.current || columnWidthRef.current === 0) return;

      const dates = extendedDatesRef.current;
      const width = columnWidthRef.current;
      const targetDateStr = targetDate.toISOString().split("T")[0];
      const dateIndex = dates.findIndex(
        (date) => date.toISOString().split("T")[0] === targetDateStr,
      );

      if (dateIndex !== -1) {
        const scrollContainer = scrollContainerRef.current;
        const containerWidth = scrollContainer.clientWidth - 80;
        const visibleColumns = Math.floor(containerWidth / width);

        // Center the target date in the viewport
        const targetScroll = Math.max(
          0,
          dateIndex * width - (visibleColumns / 2) * width,
        );

        scrollContainer.scrollTo({
          left: targetScroll,
          behavior,
        });
      }
    },
    [],
  );

  // Scroll observer and infinite loader
  const scrollMetrics = useHorizontalScrollObserver(
    scrollContainerRef,
    columnWidth,
    extendedDates,
  );

  const { loadMorePast, loadMoreFuture, isLoadingPast, isLoadingFuture } =
    useInfiniteCalendarLoader({
      selectedCalendars,
      isInitialized,
    });

  // Update date refs when dates change (extendedDatesRef also feeds the
  // scroll helpers above so they always see the latest list)
  useEffect(() => {
    extendedDatesRef.current = extendedDates;
    if (extendedDates.length > 0) {
      firstDateRef.current = extendedDates[0];
      lastDateRef.current = extendedDates[extendedDates.length - 1];
    }
  }, [extendedDates]);

  // Effect 1: Scroll to today on initial load
  useEffect(() => {
    let scrollTimer: ReturnType<typeof setTimeout> | undefined;
    if (
      !hasScrolledToTodayRef.current &&
      extendedDates.length > 0 &&
      scrollContainerRef.current &&
      columnWidth > 0
    ) {
      const todayIndex = getTodayIndex(extendedDates);
      if (todayIndex !== -1) {
        scrollTimer = setTimeout(() => {
          scrollToDate(new Date(), "auto");
          hasScrolledToTodayRef.current = true;
        }, 100);
      }
    }
    return () => {
      if (scrollTimer !== undefined) clearTimeout(scrollTimer);
    };
  }, [extendedDates, columnWidth, getTodayIndex, scrollToDate]);

  // Effect 1b: Handle selectedDate changes (chevron buttons, today button).
  // Deliberately keyed on selectedDate only — everything else is read through
  // refs so toggling calendars or loading more dates never yanks the scroll
  // position back to the selected date.
  useEffect(() => {
    let scrollTimer: ReturnType<typeof setTimeout> | undefined;
    // Skip initial load
    if (hasScrolledToTodayRef.current) {
      const dates = extendedDatesRef.current;
      if (dates.length > 0 && columnWidthRef.current > 0) {
        const selectedDateStr = selectedDate.toISOString().split("T")[0];
        const dateIndex = dates.findIndex(
          (date) => date.toISOString().split("T")[0] === selectedDateStr,
        );

        if (dateIndex !== -1) {
          // Date is in current range, scroll to it
          scrollToDate(selectedDate, "smooth");
        } else {
          // Date is not in range, need to load it
          // Reset dates to show a range around the selected date
          const newDates = getInitialMonthlyDateRange(selectedDate);
          setExtendedDates(newDates);

          // Load events for this range
          if (selectedCalendarsRef.current.length > 0) {
            const start = newDates[0];
            const end = newDates[newDates.length - 1];
            void loadEventsRef.current(
              selectedCalendarsRef.current,
              true,
              start,
              end,
            );
          }

          // Scroll to the date after dates are updated
          scrollTimer = setTimeout(() => {
            scrollToDate(selectedDate, "auto");
          }, 100);
        }
      }
    }
    return () => {
      if (scrollTimer !== undefined) clearTimeout(scrollTimer);
    };
  }, [selectedDate, scrollToDate]);

  // Effect 2: Initial fetch of events for 3-month range. Guarded by
  // hasInitialFetchedRef, so extra runs from changing deps are no-ops until
  // the calendar selection changes (Effect 3 resets the flag).
  useEffect(() => {
    if (
      selectedCalendars.length > 0 &&
      isInitialized &&
      !hasInitialFetchedRef.current
    ) {
      const dates = getInitialMonthlyDateRange(currentWeek);
      const start = dates[0];
      const end = dates[dates.length - 1];

      void loadEvents(selectedCalendars, true, start, end);
      hasInitialFetchedRef.current = true;
    }
  }, [selectedCalendars, isInitialized, currentWeek, loadEvents]);

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

          setExtendedDates((prev) => [...newDates, ...prev]);

          requestAnimationFrame(() => {
            if (scrollContainer) {
              scrollContainer.scrollLeft =
                prevScrollLeft + newDates.length * columnWidth;
            }
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
      if (!containerRef.current || !scrollContainerRef.current) return;
      const containerWidth = containerRef.current.offsetWidth;
      const timeColumnWidth = 80; // w-20
      const availableWidth = containerWidth - timeColumnWidth;
      const calculatedWidth = Math.floor(availableWidth / daysToShow);
      const newColumnWidth = Math.max(calculatedWidth, 120); // min 120px per column

      const prevWidth = columnWidthRef.current;
      if (prevWidth === newColumnWidth) return;

      // Calculate which column is currently at the left edge of the viewport
      const currentScrollLeft = scrollContainerRef.current.scrollLeft;
      const currentLeftColumn = Math.floor(currentScrollLeft / prevWidth);

      setColumnWidth(newColumnWidth);

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
    };

    updateColumnWidth();

    const resizeObserver = new ResizeObserver(updateColumnWidth);
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }

    return () => resizeObserver.disconnect();
  }, [daysToShow]);

  return {
    containerRef,
    scrollContainerRef,
    columnVirtualizer,
    extendedDates,
    isLoadingPast,
    isLoadingFuture,
  };
};
